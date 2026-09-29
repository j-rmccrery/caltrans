"""Track A deterministic checks: does what the sheet SAYS match what the sheet DRAWS?

For every bearing / distance label on the drawing, find the line it annotates (parallel, adjacent),
measure that line from the vector geometry through the georeferencing fit, and compare:
  bearing   printed N dd°mm'ss" E  vs  azimuth of the drawn line (grid north from the fit)
  distance  printed ft             vs  drawn length x scale (grid feet; sheet says ground = grid x 1.0000704)
Curve labels are checked for L = R * delta wherever R, delta and L are printed together.
Every failure or unmatched label becomes an exception with its sheet region. No OCR confidence is used:
the exception queue is driven by geometry, which is the point.
usage: [SHEET=<pdf>] python spike/checks.py   ->  spike/out[/<sheet>]/checks.csv, exceptions.json
       python spike/checks.py --selftest      (wrong_line_likely; no sheet needed)
"""
import csv
import hashlib
import itertools
import json
import math
import os
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, READS, PDF, frame, real_text_blocks, segments  # noqa: E402

BEAR = re.compile(r"^([NS])(\d{1,2})°(\d{2})'(\d{2})\"([EW])(\(R\))?$")
DIST = re.compile(r"^(\d{1,4}\.\d{2,3})'?(\(T\))?$|^(\d{1,3}(?:,\d{3})+\.\d{2,3})'(\(T\))?$")  # 2 decimals in
# feet, 3 on the metric sheets; second branch is the comma-grouped form (long R/W distances on some
# sheets, "18,966.64'"), gated on the trailing ' -- a coordinate is never quote-suffixed, so this can't
# eat a coordinate's trailing group the way a bare digit match would. Use dist_num(m) to read either branch.
ANG = re.compile(r"^(?:[Δ△]|A)?=?(\d{1,3})°(\d{2})'(\d{2})\"(\(T\))?$")  # delta's prefix is a symbol
# (Δ/△) on some sheets, the letter "A=" on this drafter's (CHaldenwang, north set): every curve-data
# block on R-10741.1/.2/.3 uses "A=", never Δ/△, and none of the south sheets use "A=" (checked), so
# accepting both generalises to the drafter rather than guessing a single sheet's convention
RAD = re.compile(r"^R=(\d{1,5}\.\d{2})'?$")
LEN = re.compile(r"^L=(\d{1,5}\.\d{2})'?(\(T\))?$")
TOKEN = re.compile(
    r"[NS]\d{1,2}°\d{2}'\d{2}\"[EW](?:\(R\))?"
    r"|(?<![\d.,+])\d{1,4}\.\d{2,3}'?(?:\(T\))?(?![\d])"
    r"|(?<![\d,])\d{1,3}(?:,\d{3})+\.\d{2,3}'(?:\(T\))?(?![\d])"  # comma-grouped distance, trailing ' mandatory
)
# token (searchable, not whole-line) forms of RAD/ANG/LEN: this drafter sometimes joins an angle and a
# length into one OCR line with no "|" split ("A=32°20'00" L=660.20'"), which the whole-line RAD/ANG/LEN
# above never match -- same fix as TOKEN already is for BEAR/DIST. RAD_TOK allows a comma-grouped radius
# ("R=1,920.00'"), which plain RAD does not. The negative lookbehind keeps R=/A= from matching mid-word
# ("TOTAL=22.366" has an "L=" inside it) or right after a radial bearing's "(R)" ("...E(R) R=8.72'" is a
# curve's radius beside its radial bearing, not a joined curve-data block, on the south sheets).
_NOT_MIDWORD = r"(?<![A-Za-z0-9)])"
RAD_TOK = re.compile(_NOT_MIDWORD + r"R=([\d,]{1,7}\.\d{2})'?")
# "=" stays mandatory (a bearing never carries one) so this can't match inside "S16°20'26"E"; the
# Δ/△/A marker in front of it stays optional, matching a bare "=2°13'32"" seen on r10434_1
ANG_TOK = re.compile(_NOT_MIDWORD + r"(?:[Δ△]|A)?=(\d{1,3})°(\d{2})'(\d{2})\"")
LEN_TOK = re.compile(_NOT_MIDWORD + r"L=(\d{1,5}\.\d{2})'?(\(T\))?")
STATION = re.compile(r"\d\+\d|\bSTA\b", re.I)  # a block naming a station: the number after + is never a distance,
# even when it and its +prefix land in separate annotations (checked on the whole block, not the token)
AREA_CTX = re.compile(r"SQ\.?\s?FT|ACRES?\b|\bAC\.|±", re.I)  # a parcel-area figure, in a bubble, an acreage
# table ("*28.31 AC.") or a legend: not a distance; "AC." (the abbreviation) is as common on this sheet as
# the spelled-out word and was not being caught -- an acreage table read as four false distance labels
NOTES_CTX = re.compile(r"\bEPOCH\b|\bDATUM\b", re.I)  # the coordinate-basis notes paragraph ("...CCS83
# Zone 3, EPOCH 1991.35...") a plain float inside it is never a line length; kept to the note's own
# vocabulary (EPOCH, DATUM) so a real distance elsewhere on the sheet is never touched
DETAIL_RE = re.compile(r"\bDETAIL\b", re.I)
_NTS_TOKEN = r"(?<![A-Za-z])(?:N\.?T\.?S\.?|NOT\s+TO\s+SCALE)(?![A-Za-z])"  # "N.T.S." or the spelled-out
# "NOT TO SCALE" as its own token: a bare substring match (no letter boundary) would also fire inside
# ordinary words that happen to contain "nts" -- agents, easements, monuments, instruments, all common
# on a survey sheet's boilerplate and legend. The spelled-out form is here because R-10434.1's DETAIL
# "D" is captioned "NOT TO SCALE", never "N.T.S." (checked: its "DETAIL "D"" text is never read at all
# at this drafter's font, only this line is) -- loop6 leg F
NTS_RE = re.compile(_NTS_TOKEN, re.I)
SCALE_NTS_RE = re.compile(r"SCALE.*?" + _NTS_TOKEN, re.I)
DIST_TOL = 0.30   # ft, plus 0.05 %
ASSOC = set(filter(None, os.environ.get("ASSOC", "").split(",")))  # remaining diagnostics: layers, orderdiag (tables.py)
NOT_LINEWORK = re.compile(r"LBL|anno|ANNO|TBL|SHEET|Sheet|Wipeout|PNT|border|TEXT|TXT|Format|Seal", re.I)  # ASSOC=layers: CAD layer names that are not linework
AZ_FILTER = 0.5   # deg: a candidate line must run within this of the printed bearing (grid), where one is printed


def dist_num(m):
    """(number string, is-total) from a DIST match, whichever branch (plain or comma-grouped) fired.
    Commas stripped, so callers can always just float() the first element."""
    return (m[1] or m[3]).replace(",", ""), bool(m[2] or m[4])


_QUOTE_SINGLE = re.compile(r"[’‘`′´]")
_QUOTE_DOUBLE = re.compile(r"[”“″]")


def normalize_quotes(blocks):
    """Loop16 leg F: the scan OCR reader (RapidOCR, read_rapid.json -- R-10741's sheets have no vector
    text, so this is the only source) sometimes recognises the seconds/inch mark as a typographic quote
    (U+201D, U+2033...) instead of a straight ASCII '"', and the minutes mark as a typographic apostrophe
    instead of a straight "'" -- every regex here (BEAR, ANG, ANG_TOK, ...) demands the straight form, so a
    label with a curly mark silently matches nothing: R-10741.1's "A=15°39'31”|L=319.73'" joined
    block (R=1169.90' printed alongside it) never produced a "curve L=R*delta" row, and its delta never
    reached labels.json/traverse.py, though R, delta and L were all genuinely printed and OCR'd. Fixed once
    here, at the one place every block's text enters this module's matching (see main()), rather than in
    each of the several regexes that would otherwise all need the same fix. Vector-text sheets (read_shx.json)
    measured clean of curly marks already; this is a no-op there. Mutates blocks in place."""
    for b in blocks:
        b["text"] = _QUOTE_DOUBLE.sub('"', _QUOTE_SINGLE.sub("'", b["text"]))


_LOOSE_BEARING = re.compile(r"([NSns])(\d{1,2})[°'*\"](\d{2})'(\d{2})\"([EWew])((?:\(R\))?)")


def fix_bearing_symbols(blocks):
    """Loop17 leg D: RapidOCR reads the degree glyph in a bearing as one of several other characters
    almost as often as it reads it right -- prime, asterisk, or a second straight quote indistinguishable
    from the seconds mark by character alone, only by position ("S72\"06'18\"E" for S72 deg 06'18"E,
    degree misread as a second quote mark) -- and reads the compass letters in lower case about as often
    as upper ("s15 deg 42'45\"w"). BEAR/TOKEN demand literal deg + uppercase N/S/E/W, so either miss is a
    silent zero match: not a wrong bearing, no bearing at all -- checks.py never even queues the row as an
    exception (own_block_has_bearing's bearing_regions never see it either), so it is invisible all the
    way to attribution's "bearing_from_drawing" bucket. Measured (loop17 leg C): every one of 14 keyed
    R-10741 dimensioned-boundary bearings reads correctly character-for-character; this was the reason
    none of them reached a row anyway. A scan across every sheet's own OCR json (read_rapid/read_v5) that
    already carries a genuine BEAR match elsewhere finds ~90 more near-miss bearings shaped exactly like
    this, degree in {deg,',*,\"} or compass case flipped -- so the fix is general, not 14-row-specific.
    Runs after normalize_quotes (curly marks already collapsed to '/\" here, so the loose match only has
    to cover degree-slot confusion + case, not quote curliness too) and canonicalises in place: the
    bearing's own text becomes exactly what BEAR/TOKEN already expect, so no downstream code (checks.py's
    line search, build_edges, inherit_bearings) needs to know this ever happened -- same "fix once where
    every consumer already reads" reasoning as normalize_quotes itself. Never touches ANG/RAD/LEN (no
    compass letters in that shape, so this pattern cannot match a curve-data block). Mutates in place."""
    for b in blocks:
        b["text"] = _LOOSE_BEARING.sub(lambda m: f"{m[1].upper()}{m[2]}°{m[3]}'{m[4]}\"{m[5].upper()}{m[6]}", b["text"])


def set_decimals(blocks):
    """A sheet prints its distances with two decimals (feet) or three (the metric sheets): take the
    majority and make DIST and TOKEN demand it, so the other form is not read as a distance."""
    global DIST, TOKEN
    two = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{2}(?!\d)", b["text"])) for b in blocks)
    three = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{3}(?!\d)", b["text"])) for b in blocks)
    n = "3" if three > two else "2"
    DIST = re.compile(r"^(\d{1,4}\.\d{" + n + r"})'?(\(T\))?$|^(\d{1,3}(?:,\d{3})+\.\d{" + n + r"})'(\(T\))?$")
    TOKEN = re.compile(
        r"[NS]\d{1,2}°\d{2}'\d{2}\"[EW](?:\(R\))?"
        r"|(?<![\d.,+])\d{1,4}\.\d{" + n + r"}'?(?:\(T\))?(?![\d])"
        r"|(?<![\d,])\d{1,3}(?:,\d{3})+\.\d{" + n + r"}'(?:\(T\))?(?![\d])"
    )
    return n
BEAR_TOL = 0.05   # degrees (3 arc-minutes)
LINEWORK_W = 0.7  # pt: a drawn piece's own half-width plus one rendering unit -- the positional slop
# an endpoint carries, whatever the piece's length (loop6 leg C, leg B's finding: 4 bearing labels sat
# on the right line and failed by 6-22 arcmin only because the drawn piece was short)
BEAR_TOL_CAP = 0.5    # deg (30 arcmin): leg C follow-up -- the scaled tolerance must not grow so wide
# on a short piece that it swallows a genuine disagreement as a pass
MIN_BEARING_LEN_PT = 10.0  # pt: below this a straight piece's own azimuth is too uncertain to check a
# bearing against at all (leg C follow-up) -- queued, never passed or failed
ARC_TOUCH_PT = 1.0  # pt: "touch" for at_tip's arc-kind proximity fallback means within this of the tip
ARC_TOUCH_CLEAR_PT = 2.0  # pt: a second candidate this close (or closer) makes the nearest one a tie, not a touch (loop15b)


def bearing_tol_deg(len_pt):
    """A piece len_pt long has its azimuth known only to about atan(w / len_pt) -- the shorter the
    piece, the less two endpoints each off by w pin down the direction between them. Never tighter
    than the base BEAR_TOL, never looser than BEAR_TOL_CAP; scales with no per-sheet constant."""
    return min(max(BEAR_TOL, math.degrees(math.atan2(LINEWORK_W, max(len_pt, 1e-6)))), BEAR_TOL_CAP)


def wrong_line_likely(kind, off, printed=None):
    """True when a FAIL's own size looks like the checker measured the wrong line/arc rather than the
    record really disagreeing -- loop 14. Cuts calibrated on the keyed FAILs in spike/gold/presidio_assoc.json
    and spike/gold/r10434_3_assoc.json (measure.py, not kept): chosen to keep every keyed real
    disagreement a FAIL, not to catch every wrong-line one -- the two distributions overlap throughout
    (bearing: keyed real max 54.6', next wrong 250.1'; distance: keyed real max 330.77 ft / 128.8% of
    printed; arc length: no (ft, %) pair split cleanly, so both conditions must hold; radius: keyed real
    max 94.0%). A fail beyond the cut is queued, not failed -- see wrong_line_likely's callers."""
    pct = abs(off) / abs(printed) * 100 if printed else None
    if kind == "bearing":
        return abs(off) > 180              # arcmin
    if kind == "distance":
        # off/printed saturates at 100% as the drawn piece shrinks to 0, so it can only ever flag an
        # OVERSHOOT (drawn several times printed) -- an undershoot (a wrong-line pick landing on a
        # short stub/tick well under a long record distance) slipped past both cuts (loop17 leg B:
        # Presidio 359.00' matched to a 28 ft tick, off 331 ft / 92% of printed, under 400 ft and
        # under 200%). off/drawn is the same ratio the other way round -- identical to pct whenever
        # drawn >= printed (an overshoot, where it's always <= pct), so no previously-kept overshoot
        # FAIL changes; it only ever adds coverage on the undershoot side.
        drawn = printed + off if printed is not None else None  # off = drawn - printed
        pct_vs_drawn = abs(off) / abs(drawn) * 100 if drawn else None
        return abs(off) > 400 or (pct is not None and pct > 200) or (pct_vs_drawn is not None and pct_vs_drawn > 200)
    if kind == "arc length":
        return abs(off) > 175 and pct is not None and pct > 90
    if kind == "radius":
        return abs(off) > 110              # off is already a percent


def dms(d, m, s):
    return int(d) + int(m) / 60 + int(s) / 3600


def attach_shared_curve_radius(labels_by_region, region_key, R, D):
    """Loop17 leg H: the curve-data joined-triple pass (main()'s curve_blocks loop) can validate a
    genuine (R, delta, L) triple for an "L=..." block that was ALREADY resolved into its own "arc" label
    by the standalone L=/(T) or bare-distance-as-arc branches earlier in main() -- previously this R/delta
    was thrown away outright (len_checked's own "continue", meant only to stop a duplicate length re-
    check) because a fresh label was never created for an already-resolved block. Every already-placed
    "arc" label is indexed by its own region (labels_by_region, built once in main() before this loop);
    this attaches R/delta onto whichever of THOSE labels still lacks R, keyed by the SAME region the
    length check used, never a guess by proximity or ordering. Returns the count filled (0 or 1: a region
    holds at most one "arc" label without R, since a region is one printed annotation block)."""
    filled = 0
    for lab in labels_by_region.get(region_key, []):
        if "R" not in lab:
            lab["R"], lab["delta"] = R, D
            filled += 1
    return filled


def azimuth(b):
    m = BEAR.match(b)
    a = dms(m[2], m[3], m[4])
    return {("N", "E"): a, ("S", "E"): 180 - a, ("S", "W"): 180 + a, ("N", "W"): 360 - a}[(m[1], m[5])]


def fmt_bearing(az):
    az %= 360
    q = ("N", "E", az) if az <= 90 else ("S", "E", 180 - az) if az <= 180 else ("S", "W", az - 180) if az <= 270 else ("N", "W", 360 - az)
    d = q[2]; dd = int(d); mm = int((d - dd) * 60); ss = round(((d - dd) * 60 - mm) * 60)
    return f"{q[0]}{dd}°{mm:02d}'{ss:02d}\"{q[1]}"


GAP = 9.0  # pt: a line is interrupted where it passes through a point-symbol circle


def lines_on_sheet(segs, circles, max_turn_deg=0.6):
    """Maximal collinear chains of segments: the lines a label describes. Chains bridge the gap where a
    line passes through a circle symbol, and a chain that ends at a circle is extended to its centre,
    because the circle marks the vertex the printed distance runs to."""
    ends = np.array([q for a, b, _, _ in segs for q in (a, b)])
    tree = cKDTree(ends)
    idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    ctree = cKDTree(circles) if len(circles) else None
    used, chains = set(), []
    for k0 in range(len(segs)):
        if k0 in used:
            continue
        a0, b0, w0, _ = segs[k0]
        d0 = (b0 - a0) / np.hypot(*(b0 - a0))
        chain = [k0]; used.add(k0)
        for start, direction in ((a0, -1), (b0, 1)):
            cur, cur_dir = start, d0 * direction
            while True:
                nxt = None
                for j in sorted(tree.query_ball_point(cur, GAP), key=lambda j: np.hypot(*(ends[j] - cur))):
                    k, e = idx[j]
                    if k in used:
                        continue
                    a, b = segs[k][:2]
                    near, far = (a, b) if e == 0 else (b, a)
                    gap = np.hypot(*(near - cur))
                    d = (far - cur) / max(np.hypot(*(far - cur)), 1e-9)
                    if gap > 0.6 and (abs((near - cur) @ np.array([-cur_dir[1], cur_dir[0]])) > 0.8 or (near - cur) @ cur_dir < 0):
                        continue  # a gap must be straight ahead, not sideways or backwards
                    if d @ cur_dir > math.cos(math.radians(max_turn_deg)):
                        nxt = (k, far)
                        cur_dir = d
                        break
                if nxt is None:
                    break
                used.add(nxt[0]); chain.append(nxt[0]); cur = nxt[1]
        pts = np.array([q for k in chain for q in segs[k][:2]])
        if max_turn_deg > 1:  # a curved chain: keep the polyline, its length is the arc length
            order = np.argsort((pts - a0) @ d0)
            P = pts[order]
            chains.append({"pts": P, "len_pt": float(sum(np.hypot(*(segs[k][1] - segs[k][0])) for k in chain)), "n": len(chain),
                           "radius_pt": float("nan"), "width": w0})
            continue
        al = (pts - a0) @ d0
        p0, p1 = a0 + d0 * al.min(), a0 + d0 * al.max()
        if ctree is not None:  # end at a circle: the vertex is its centre
            for end, sign in ((0, -1), (1, 1)):
                pt = p1 if end else p0
                dist, j = ctree.query(pt)
                if dist < 6 and (circles[j] - pt) @ d0 * sign > -0.5:
                    if end:
                        p1 = a0 + d0 * ((circles[j] - a0) @ d0)
                    else:
                        p0 = a0 + d0 * ((circles[j] - a0) @ d0)
            al = np.array([(p0 - a0) @ d0, (p1 - a0) @ d0])
        # this chain's raw segment endpoints, (al, x, y) relative to the final p0 (the same origin
        # split_chains cuts against): a cut piece downstream (split_chains, span_for) refits its own
        # local direction from just its slice of these, instead of inheriting d0 -- the seed segment's
        # raw direction, arbitrary among however many segments got chained -- for its whole span, which
        # is wrong wherever a multi-piece record line has a real kink partway along it
        al0 = (pts - p0) @ d0
        samples = sorted(zip(al0.tolist(), pts[:, 0].tolist(), pts[:, 1].tolist()))
        chains.append({"p0": p0, "p1": p1, "dir": d0, "len_pt": float(al.max() - al.min()), "width": w0, "n": len(chain), "_pts": samples})
    return chains


def local_fit_dir(samples, s0, s1, fallback, pad=1.0):
    """A cut piece's own heading, fit (least squares) through only the raw segment endpoints whose
    position along the parent chain falls in [s0, s1] (padded 1 pt for the endpoints right at a cut) --
    not the parent's single seed-segment direction, which a multi-piece record line can wander well away
    from by the time the label's own piece is reached. Falls back to the parent direction where a span
    (a very short piece, or one that bridged a gap with no interior samples) can't support its own fit."""
    pts = np.array([[x, y] for al, x, y in samples if s0 - pad <= al <= s1 + pad])
    if len(pts) < 2:
        return fallback
    mean = pts.mean(axis=0)
    d = pts[-1] - pts[0] if len(pts) == 2 else np.linalg.svd(pts - mean)[2][0]
    n = np.hypot(*d)
    if n < 1e-9:
        return fallback
    d = d / n
    return d if d @ fallback >= 0 else -d


def linework_segments(page, max_gray=0.6):
    """Like georef.segments, but without glyph strokes: a character is a small multi-stroke path."""
    segs = []
    for pid, d in enumerate(page.get_drawings()):
        r = d["rect"]
        if max(r.width, r.height) <= 12 and len(d["items"]) > 1:
            continue
        c = d.get("color")
        if c is None or max(c) > max_gray:
            continue  # white masks and light grey hatch are not lines a label describes
        if "layers" in ASSOC and NOT_LINEWORK.search(d.get("layer") or ""):
            continue  # CAD layer says annotation, table, sheet furniture, wipeout, point mark: not a line a label describes
        for it in d["items"]:
            if it[0] == "l":
                a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
                if np.hypot(*(a - b)) > 1.0:
                    segs.append((a, b, round(d.get("width") or 0, 2), pid))
    return segs


def circumradius3(P):
    """Three-point circle through a piece's first, middle and last points (pt units)."""
    A, B, C = P[0], P[len(P) // 2], P[-1]
    den = 2 * abs((A[0] - C[0]) * (B[1] - A[1]) - (A[0] - B[0]) * (C[1] - A[1]))
    return float(np.hypot(*(A - B)) * np.hypot(*(B - C)) * np.hypot(*(C - A)) / den) if den > 1e-6 else float("inf")


def circle_center3(P):
    """Centre of the same three-point circle (pt units), or None for three near-collinear points."""
    (ax, ay), (bx, by), (cx, cy) = P[0], P[len(P) // 2], P[-1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-6:
        return None
    ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d
    uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    return np.array([ux, uy])


def circle_fit_lsq(P):
    """(centre, radius) from a least-squares (algebraic) circle through EVERY point of P, not just three
    samples: circumradius3's first/middle/last picks a shallow arc's tiny sagitta out of whatever noise
    sits at exactly those three points, which drifts far worse the longer and straighter (lower-curvature)
    the piece -- measured on Presidio's C21 candidate, a compound curve of many points: circumradius3 gave
    2192 ft, the full least-squares fit 1419 ft, for a curve whose record is 1380 ft. Used wherever a
    stitch join's radius needs to survive a many-point whole curve (chain_curve_paths' wider bridge, leg9A
    attempt 2), not for split_at's own per-piece candidates, which stay on circumradius3 as before. Falls
    back to circumradius3/circle_center3 under 4 points, where a least-squares fit has no more information
    than the three-point one anyway."""
    if len(P) < 4:
        return circle_center3(P), circumradius3(P)
    x, y = P[:, 0], P[:, 1]
    sol, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x ** 2 + y ** 2, rcond=None)
    cx, cy, c = sol
    r = math.sqrt(max(c + cx ** 2 + cy ** 2, 0))
    return (np.array([cx, cy]), float(r)) if 0 < r < 1e7 else (None, float("inf"))


def arcs_on_sheet(page):
    """Curved lines: runs of bezier items in a path, sampled; length and a circumradius estimate."""
    from overlay import bezier
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if max(r.width, r.height) <= 12 and len(d["items"]) > 1:
            continue  # a small multi-stroke path is a character (same rule as linework_segments): a
            # curved digit/letter draws bezier items too, and was being read as a tiny false "arc" that a
            # leader tip near its own label text could land on (loop2 leg C)
        c = d.get("color")
        if c is None or max(c) > 0.6:
            continue
        run = []
        for it in d["items"] + [("end",)]:
            if it[0] == "c":
                pts = bezier(*[np.array([p.x, p.y]) for p in it[1:5]], n=16)
                run = (run[:-1] if run else []) + list(pts)
            elif run:
                P = np.array(run)
                L = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
                if L > 6:
                    out.append({"pts": P, "len_pt": L, "radius_pt": circumradius3(P), "width": round(d.get("width") or 0, 2), "color": c})
                run = []
    return out


def nearest_arc(b, arcs, tol_perp, tol_deg=8.0):
    """Arc whose nearest point lies beside the label with its tangent along the label's reading direction.
    The coarse distance prefilter below is a search-space cut, not the real perpendicular test (that's
    `perp < tol_perp` further down) -- it stays a fixed, label-size-scaled reach on its own so a caller
    passing a tight tol_perp (leg5 legB2: a label must sit close beside a curve to become an arc-length
    candidate at all) doesn't also silently shrink how far along the curve the nearest point may fall."""
    c, u, n = frame(b)
    best = None
    for arc in arcs:
        P = arc["pts"]
        d = np.hypot(*(P - c).T)
        k = int(d.argmin())
        if d[k] > 5.0 * b["glyph_h"] + b["w"]:
            continue
        t = P[min(k + 1, len(P) - 1)] - P[max(k - 1, 0)]
        t = t / max(np.hypot(*t), 1e-9)
        if abs(t @ n) > math.sin(math.radians(tol_deg)):
            continue
        perp = abs((P[k] - c) @ n)
        if perp < tol_perp and (best is None or perp < best[0]):
            best = (perp, arc)
    return None if best is None else best[1]


def nearest_arc_end(b, arcs):
    """Loop18 leg 4: the arc whose own drawn END (p0 or p1, never a point along its body) sits nearest
    a label -- for a printed radial ("(R)") bearing, which marks a curve's own END direction and so
    sits beside that END specifically, not tangent-aligned with the curve's flank the way a chord
    citation does. nearest_arc() (used for chord citations) requires the label's reading direction to
    run along the curve's OWN tangent there (tol_deg) -- a radial commonly sits off at another angle
    entirely (it names a RADIAL direction, perpendicular-ish to the tangent), so that filter rejected
    most genuine radials outright: census (spike/out/leg184_census_*.json) found 80 of 123 printed
    radials on the three south gate sheets parsed clean (BEAR matched, "(R)" group present) but found
    no curve this way. No proximity cap here -- unlike nearest_arc's tight tol_perp, a radial can sit
    a genuine distance from its own curve on a busy sheet (r10434_3 measured real matches out to 229 pt
    against a false-table-row cluster starting at 143 pt with no other separating signal available at
    this stage); this function only PROPOSES the pairing, same as nearest_arc already does for a chord
    citation -- traverse.complete_curve_chords' own tangent + centre-agreement test (loop18 leg 4) is
    what actually accepts or refuses it before any check result or recon output ever depends on it, so
    a wrong nearby pick here costs nothing but a discarded radials.json row."""
    c = np.array([b["cx"], b["cy"]])
    best = None
    for arc in arcs:
        pts = arc["pts"]
        if len(pts) < 2:
            continue
        for end_pt in (pts[0], pts[-1]):
            d = float(np.hypot(*(end_pt - c)))
            if best is None or d < best[0]:
                best = (d, arc)
    return None if best is None else best[1]


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
    return float(np.hypot(*(p - (a + t * ab))))


def poly_dist(p, P):
    """Distance from p to a polyline's segments (R/W curves are 15-40 pt facets, vertices are not enough)."""
    A, B = P[:-1], P[1:]
    AB = B - A
    t = np.clip(((p - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0, 1)
    return float(np.hypot(*(p - (A + t[:, None] * AB)).T).min())


def az_diff(a, b):
    """Angle between two undirected lines, degrees, from their azimuths."""
    return abs((a - b + 90) % 180 - 90)


def nearest_line(b, chains, tol_perp, want_ft=None, scale=None, tol_deg=4.0, want_az=None, az_of=None):  # a rotated label box carries 1-3 deg of angle error
    """The line a label describes: parallel, overlapping it along the reading direction, close beside it.
    A label often sits between two parallel lines; when a printed distance is known, a neighbour whose
    drawn length matches it within 1 ft is preferred (the bearing check stays independent).
    Where a bearing is printed with the label, only lines running within AZ_FILTER of it (through the
    georeferencing rotation) are candidates; none = no line, not a guess.
    Civil 3D anchors a bearing/distance label at the segment's midpoint: a chain whose midpoint sits within
    2.5 glyph heights of the label centre (perpendicular) and 0.6 label widths along the reading direction
    is also a candidate even where the overlap test below rejects it, scored on that midpoint distance
    (a bearing+distance pair is one already-joined block, so its centre is the pair's own centre)."""
    c, u, n = frame(b)
    cands, anchored = [], []
    for ln in chains:
        strict_ok = abs(ln["dir"] @ n) <= math.sin(math.radians(tol_deg))  # the label's own box rotation:
        # a real signal only where no printed bearing exists to check against instead
        if want_az is None:
            if not strict_ok:
                continue
        elif az_diff(az_of(ln), want_az) > (BEAR_TOL if not strict_ok and want_ft is None else max(AZ_FILTER, math.degrees(math.atan2(0.3, ln["len_pt"] * scale)))):
            # a short line drawn 0.3 ft off at one end is not a different bearing -- EXCEPT for a relaxed
            # (box-misaligned) candidate with no printed distance to cross-check by length at all (loop15
            # leg2, orchestrator review): the label's own box rotation already isn't backing this one up,
            # so nothing but azimuth agreement says it's the right line, and the length-scaled window is
            # wide enough on a long line to admit a genuinely different nearby record bearing (measured:
            # r10434_3's S79-01-10W, 11.4 arcmin off, inside the 0.212 deg window a 262 ft candidate gets
            # -- a real wrong-pass on review, its correctly-matched neighbour S79-12-32W' own printed
            # bearing sitting just 11 arcmin off the wrong one's). Held to BEAR_TOL (3 arcmin, the
            # tightest bearing tolerance this file already trusts for a well-determined long line)
            # instead -- not a new magic number. Every relaxed pass with its own paired distance keeps
            # the ordinary window (want_ft is not None): span_for's length match is real corroboration
            # there; a relaxed bearing-only pick with none measured well inside this bound regardless
            # (r10434_1's N48-13-57W: 1.2 arcmin).
            continue
        # loop15 leg2: where a bearing IS printed, az_diff against the georeferenced grid azimuth already
        # is the real "is this the label's line" test, tighter (<=~2 deg typically) and measured against
        # the record, not the OCR/glyph reader's guess at the label box's own rotation -- strict_ok (the
        # box-rotation test) is kept only to decide, below, whether admitting a box-misaligned candidate
        # is a NEW find (never previously reachable, so it's marked "relaxed_angle" and may only ever
        # surface as a pass or a queued "association unproven", not a FAIL) or one the old rule already
        # picked (byte-identical, whenever a strict_ok candidate also passes az_diff). Measured: a stacked
        # bearing+distance block's box angle can read 10-15 deg off the drawn line's true heading (this
        # drafter's two-line blocks; loop15 leg2 crops) even though the printed bearing matches the line
        # within 0.01 deg -- the old box-angle-only prefilter silently dropped that correct candidate.
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        perp = abs((ln["p0"] - c) @ n)
        if not (hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]) and perp < tol_perp:
            cands.append((perp, ln, strict_ok))
            continue
        mid = (ln["p0"] + ln["p1"]) / 2
        mperp, malong = abs((mid - c) @ n), abs((mid - c) @ u)
        if mperp < 2.5 * b["glyph_h"] and malong < 0.6 * b["w"]:
            anchored.append((mperp, ln, strict_ok))
    cands += anchored
    if any(s for _, _, s in cands):
        cands = [(p, ln) for p, ln, s in cands if s]  # a strict (old-rule) candidate survived: reproduce
        # the pre-loop15-leg2 pool exactly, never let a looser admission change an already-resolvable pick
        relaxed = False
    else:
        cands = [(p, ln) for p, ln, s in cands]
        relaxed = bool(cands)  # every survivor here is new-only: tag the eventual pick below
    if want_az is not None and az_of is not None and len(cands) > 1:
        # a label often sits between two parallel candidates; the one whose OWN heading agrees with the
        # printed bearing (within its own length-scaled tolerance, loop6 leg C rule 1) wins over mere
        # proximity, and one disagreeing by more than 3x that tolerance is dropped even if it's nearest
        # (loop6 leg C rule 3: a wrong parallel neighbour). Only narrows what the earlier az filter above
        # already admitted -- that filter already rejects most wrong candidates outright, so this mostly
        # re-ranks survivors by agreement instead of leaving the last tiebreak to proximity alone.
        scored = [(p, ln, az_diff(az_of(ln), want_az), bearing_tol_deg(ln["len_pt"])) for p, ln in cands]
        survivors = [(p, ln, d, t) for p, ln, d, t in scored if d <= 3 * t]
        if survivors:
            agree = [(p, ln) for p, ln, d, t in survivors if d <= t]
            # loop15 leg2 (retry): a relaxed pick with no printed length to arbitrate by (want_ft is None,
            # so nothing below can tell two same-direction candidates apart by size) must be the ONE
            # candidate whose heading agrees -- several agreeing candidates beside a many-facet corridor
            # (one long tessellated alignment, its parallel duplicate, or a neighbouring record line 11
            # arcmin off) is direction alone failing to single out a piece, not a decided pick (a real
            # wrong-pass on review: two nearly-parallel printed bearings 0.19 deg apart, only one drawn).
            if relaxed and want_ft is None and len(agree) != 1:
                return None
            cands = agree if agree else [(p, ln) for p, ln, d, t in survivors]
    if not cands:
        return None
    on = [(p, ln) for p, ln in cands if p < 0.35 * b["glyph_h"]]  # the label is written on the line itself (some drafters)
    if on:
        cands = on
    result = None
    if want_ft is not None:
        close = [(p, ln) for p, ln in cands if abs(ln["len_pt"] * scale - want_ft) < 1.0]
        if close:
            result = min(close, key=lambda t: t[0])[1]
        else:
            spanned = [(p, s) for p, ln in cands for s in [span_for(ln, want_ft, scale, chains)] if s is not ln]  # no piece is the right length: try the span on every candidate's run
            if spanned:
                result = min(spanned, key=lambda t: t[0])[1]
    if result is None:
        result = min(cands, key=lambda t: t[0])[1]
    return {**result, "relaxed_angle": True} if relaxed else result


def leaders(page, circles=()):
    """Leaders: thin stroked paths (this drafter's are curly, 15-30 pt, the same 1.02 weight as the
    lettering) that end at a filled arrowhead triangle, or at a point-symbol circle (coordinate
    callouts). (start, tip, arrow direction) and the path ids."""
    heads, sizes, paths = [], [], []
    for cx, cy in circles:  # a circle as a "head": its centre is the tip, 3 corners at the centre
        heads.append(np.array([[cx, cy]] * 3)); sizes.append(0.0)  # a circle callout is exact, no widening
    for pid, d in enumerate(page.get_drawings()):
        c, w = d.get("color"), round(d.get("width") or 0, 2)
        if c is None or max(c) > 0.6:
            continue
        r = d["rect"]
        if d["type"] in ("f", "fs") and len(d["items"]) == 3 and max(r.width, r.height) < 12:
            corners = np.array([[it[1].x, it[1].y] for it in d["items"]])  # the triangle's corners
            heads.append(corners)
            sizes.append(float(max(np.hypot(*(corners[i] - corners[j])) for i in range(3) for j in range(i + 1, 3))))
        elif d["type"] == "s" and 0 < w < 1.1:
            items = [it for it in d["items"] if it[0] in ("l", "c")]
            if items:
                pts = [np.array([it[1].x, it[1].y]) for it in items] + [np.array([items[-1][-1].x, items[-1][-1].y])]
                paths.append((pts[0], pts[-1], sum(np.hypot(*(q - p)) for p, q in zip(pts, pts[1:])), pid))
    if not heads:
        return [], set()
    tree = cKDTree(np.array([h.mean(0) for h in heads]))
    out, pids = [], set()
    for p0, p1, total, pid in paths:
        if not 8 < total < 120:
            continue
        for start, end in ((p0, p1), (p1, p0)):
            dist, j = tree.query(end)
            if dist < 7:  # the leader stops at the triangle's base; the tip is the corner farthest from it
                tip = heads[j][int(np.hypot(*(heads[j] - end).T).argmax())]
                v = tip - heads[j].mean(0)
                out.append((start, tip, v / max(np.hypot(*v), 1e-9), sizes[j])); pids.add(pid)
    return out, pids


def label_box(t):
    """Centre, axes, half sizes of a label: a text block (w, h) or a tag (text length)."""
    gh = t.get("gh") or t["glyph_h"]
    c = np.array([t["cx"], t["cy"]])
    th = np.radians(t["angle"])
    u, n = np.array([np.cos(th), np.sin(th)]), np.array([-np.sin(th), np.cos(th)])
    hw = t["w"] / 2 + 0.3 * gh if "w" in t else 0.45 * gh * len(t["tag"]) + 0.3 * gh
    hh = t["h"] / 2 + 0.2 * gh if "h" in t else 0.7 * gh
    return c, u, n, hw, hh, gh


def tag_leaders(labels, paths):
    """Each leader to the one label whose box its start is nearest (stacked tags L4/L5/L7 share a
    neighbourhood; a leader is claimed once). {label index: (arrowhead tip, arrow direction, arrowhead
    size)}."""
    pairs = []
    for k, t in enumerate(labels):
        c, u, n, hw, hh, gh = label_box(t)

        def outside(p):  # distance from the label's box, 0 inside
            d = p - c
            return float(np.hypot(max(abs(d @ u) - hw, 0), max(abs(d @ n) - hh, 0)))
        for j, (start, head, _, _) in enumerate(paths):
            dn = outside(start)
            if dn < 1.5 * gh and outside(head) > dn:
                pairs.append((dn, k, j))
    out, taken = {}, set()
    for dn, k, j in sorted(pairs):
        if k not in out and j not in taken:
            out[k] = paths[j][1:]; taken.add(j)
    return out


def split_chains(chains, circles, tol=2.0):
    """A straight line on the sheet is one drawn run through several record segments: the record breaks
    it at every vertex circle and wherever another line ends on it or crosses it at an angle. Cut the
    chains there so a label's segment is a chain of its own (22.56 ft, not the 214 ft run)."""
    A = np.array([c["p0"] for c in chains]); B = np.array([c["p1"] for c in chains])
    D = np.array([c["dir"] for c in chains]); LN = np.hypot(*(B - A).T)
    C = np.asarray(circles).reshape(-1, 2)
    sin10 = math.sin(math.radians(10))
    out = []
    for k, c in enumerate(chains):
        p, t, L = c["p0"], c["dir"], c["len_pt"]
        n = np.array([-t[1], t[0]])
        cuts = set()
        if len(C):
            d = C - p
            al, pe = d @ t, d @ n
            cuts.update(al[(np.abs(pe) < 3) & (al > 1) & (al < L - 1)].tolist())
        angled = np.abs(t[0] * D[:, 1] - t[1] * D[:, 0]) > sin10
        angled[k] = False
        for E in (A, B):  # another line's end lying on this one
            d = E - p
            al, pe = d @ t, d @ n
            cuts.update(al[angled & (np.abs(pe) < tol) & (al > 1) & (al < L - 1)].tolist())
        den = t[0] * D[:, 1] - t[1] * D[:, 0]  # crossings: p + s t = a + r d
        ok = angled
        ap = A - p
        s = np.where(ok, (ap[:, 0] * D[:, 1] - ap[:, 1] * D[:, 0]) / np.where(ok, den, 1), -1)
        r = np.where(ok, (ap[:, 0] * t[1] - ap[:, 1] * t[0]) / np.where(ok, den, 1), -1)
        cuts.update(s[ok & (s > 1) & (s < L - 1) & (r > tol) & (r < LN - tol)].tolist())
        stops = [0.0] + sorted(cuts) + [L]
        for s0, s1 in zip(stops, stops[1:]):
            if s1 - s0 >= 1:
                out.append({**c, "p0": p + t * s0, "p1": p + t * s1, "dir": local_fit_dir(c["_pts"], s0, s1, t),
                            "len_pt": float(s1 - s0), "run": k, "s0": float(s0), "s1": float(s1)})
    return out


def split_at(P, circles, chains, tol=2.0, ticks=()):
    """A curved chain runs on through its tangent points. What the drawing puts where one record arc ends:
    a vertex circle, a boundary line ENDING on the curve at an angle (not merely crossing it), or, on a
    thin alignment curve, a short radial tick. Where nothing is drawn (the C15/C16 boundary on the
    R=1470 curve) the record alone knows, so the caller compares the run against the sum of its arcs.
    Cuts are the exact meeting points, not the nearest facet vertex."""
    A = np.array([c["p0"] for c in chains]); B = np.array([c["p1"] for c in chains])
    D = np.array([c["dir"] for c in chains]); LN = np.hypot(*(B - A).T)
    T, TD = (np.array([m for m, _ in ticks]), np.array([d for _, d in ticks])) if len(ticks) else (np.zeros((0, 2)), np.zeros((0, 2)))
    ctree = cKDTree(circles) if len(circles) else None
    # a curve's sampled points can sit within tol of one circle for several consecutive samples (a small
    # curve right next to a vertex, or dense sampling on a tight fillet); cut once there, at the sample
    # nearest the circle, not at every sample in the run -- else a short curve near one circle came out
    # as a spray of near-zero slivers instead of the one real cut at that vertex. But a long compound
    # curve can have a circle at EVERY record-arc boundary with no plain facet between two of them (loop2
    # leg C attempt 2: presidio's R=1470 curve has 6 distinct vertex circles back to back) -- group by
    # which circle is nearest, not merely by "near some circle", so consecutive samples nearest to
    # different circles still cut once each instead of collapsing into a single run
    circle_near = np.zeros(len(P), dtype=bool)
    if ctree is not None:
        cd, ci = ctree.query(P)
        near = cd < 2 * tol
        i = 0
        while i < len(P):
            if near[i]:
                j = i
                while j < len(P) and near[j] and ci[j] == ci[i]:
                    j += 1
                circle_near[i + int(np.argmin(cd[i:j]))] = True
                i = j
            else:
                i += 1
    sin30 = math.sin(math.radians(30))
    pts, cut = [P[0]], [True]
    for i in range(len(P) - 1):
        p, q = P[i], P[i + 1]
        t = q - p
        L = max(np.hypot(*t), 1e-9); t = t / L
        n = np.array([-t[1], t[0]])
        cuts = []
        den = t[0] * D[:, 1] - t[1] * D[:, 0]  # lines meeting this facet: p + s t = a + r d, with r at one of the line's ends
        ok = np.abs(den) > sin30
        ap = A - p
        s = np.where(ok, (ap[:, 0] * D[:, 1] - ap[:, 1] * D[:, 0]) / np.where(ok, den, 1), -1)
        r = np.where(ok, (ap[:, 0] * t[1] - ap[:, 1] * t[0]) / np.where(ok, den, 1), -1)
        ends = (np.abs(r) < tol) | (np.abs(r - LN) < tol)
        cuts += s[ok & ends & (s > 0.3) & (s < L - 0.3)].tolist()
        if len(T):
            d = T - p
            al, pe = d @ t, d @ n
            across = np.abs(TD @ t) < 0.5  # a real radial tick runs across the curve (near its normal); a
            # dash from a line running alongside it (a dashed easement, a parallel property line close
            # to a curve for a few dashes) shares the tangent instead and is not a boundary mark
            cuts += al[(np.abs(pe) < tol) & (al > 0.3) & (al < L - 0.3) & across].tolist()
        for sk in sorted(set(round(x, 2) for x in cuts)):
            pts.append(p + sk * t); cut.append(True)
        pts.append(q)
        cut.append(bool(circle_near[i + 1]))
    cut[-1] = True
    pieces, start = [], 0
    for i in range(1, len(pts)):
        if cut[i]:
            pieces.append(np.array(pts[start:i + 1]))  # one facet is still an arc: C18 is 6 ft on R=1470
            start = i
    return pieces


STITCH_GAP = 1.0        # pt: curve paths whose ends meet this close are one drawn curve, not two
STITCH_TANGENT_DEG = 3.0  # deg: end tangents must agree this closely across the join
STITCH_RADIUS_FRAC = 0.02  # fraction: fitted (three-point) radii must agree this closely across the join
STITCH_ON_CIRCLE = 1.0  # pt: a bridged join's far point must land this close to the near path's own
# fitted circle (leg9A attempt 2: a gap wider than STITCH_GAP needs its own evidence that the arc
# actually continues through the gap, not just that the two paths happen to point the same way)


def _end_tangent(P, end, k=4):
    """Unit heading at P's start (end=0, direction of travel leaving p0) or finish (end=1, direction of
    travel arriving at p1), k points in from the tip (capped to what the piece has)."""
    k = min(k, len(P) - 1)
    v = (P[k] - P[0]) if end == 0 else (P[-1] - P[-1 - k])
    n = np.hypot(*v)
    return v / n if n > 1e-9 else v


STITCH_END_SPAN = 40  # points: a join test needs the curvature AT the end that's joining, not the whole
# raw path's own overall fit -- a "curve" that is itself several record arcs plus a near-straight tangent
# stretch end to end (Presidio's own C21 candidate: one 134-point raw chain whose middle third fits a
# 15,900 ft "radius", essentially straight) fits nothing sensible as one circle, even though the specific
# end actually joining a neighbour is a clean, consistent arc on its own


def _end_circle(P, end, span=STITCH_END_SPAN):
    """(centre, radius) fit to just the `span` points nearest this end (all of them, short of that): the
    LOCAL curvature at the end that would do the joining, immune to whatever the rest of a long or
    compound raw path does elsewhere."""
    return circle_fit_lsq(P[:span] if end == 0 else P[-span:])


def chain_curve_paths(raws, bridge=0.0):
    """Loop9 leg A rule 1: chain curve paths (bezier or polyline, build_pool's own raw whole-curve
    candidates, before split_at ever cuts one) whose ends meet within STITCH_GAP (or within `bridge` --
    a text wipeout or a crossing callout leader can blank a thin alignment curve for a few glyph heights,
    same reasoning as dash_trains' own bridge), whose end tangents agree within STITCH_TANGENT_DEG (the
    two paths' headings run continuously through the shared point, whichever end of each meets) and
    whose fitted three-point-circle radii (circumradius3) agree within STITCH_RADIUS_FRAC, into one
    parent -- a compound record curve some drafters draw as several separate PDF paths end to end
    (Presidio's C21: R=1380.00', L=876.88', measured as 449.84 because the parent used to be whichever
    single path the label's own piece happened to fall on). A join past STITCH_GAP additionally needs the
    far path's start to land within STITCH_ON_CIRCLE of the near path's own fitted circle (attempt 2):
    two paths can point the same way and share a radius by coincidence at a wider reach, but only a join
    where the far point actually sits ON the near arc's circle is evidence the SAME arc continues through
    the gap, not just that some other similar-radius curve happens to sit nearby pointing the same way.
    `raws`: [{"pts": Nx2 array, "width": float, "ticks_ok": bool, "source": "bezier"|"poly"}], each one
    of build_pool's existing raw curve candidates (unchanged). Returns groups in the same shape plus
    "n_merged" (paths joined into this one, 1 = untouched) and, for a merged group, "source" dropped
    (mixed-source groups are legitimate: a bezier facet meeting a polyline one is still one drawn curve).
    A singleton group carries its original dict back unchanged (by value), so nothing about an unmerged
    curve's downstream treatment can drift from before this rule existed."""
    n = len(raws)
    info = []
    for r in raws:
        P = r["pts"]
        # the ORIGINAL, tight-join test (gap <= STITCH_GAP) keeps circumradius3's own whole-path fit,
        # byte-for-byte as the first version of this rule -- proven safe (leg9A bench: no tag pass lost
        # anywhere) before the wider bridge ever existed. Only a join past STITCH_GAP falls back to the
        # local end fit; touching the tight join's own radius source regressed a passing tag on
        # r10434_3 (C33) even with bridge=0, from nothing but the different fitting method
        info.append({"p0": P[0], "p1": P[-1], "h0": _end_tangent(P, 0), "h1": _end_tangent(P, 1),
                     "radius": circumradius3(P) if len(P) >= 3 else float("nan"),
                     "ends": [_end_circle(P, 0), _end_circle(P, 1)] if len(P) >= 3 else [(None, float("nan"))] * 2})
    uf = list(range(n))

    def find(x):
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    reach = max(STITCH_GAP, bridge)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            for ei, pi in ((0, info[i]["p0"]), (1, info[i]["p1"])):
                for ej, pj in ((0, info[j]["p0"]), (1, info[j]["p1"])):
                    gap = float(np.hypot(*(pi - pj)))
                    if gap > reach:
                        continue
                    if gap <= STITCH_GAP:
                        ri, rj = info[i]["radius"], info[j]["radius"]
                        if not (math.isfinite(ri) and math.isfinite(rj)) or abs(ri - rj) > STITCH_RADIUS_FRAC * max(ri, rj):
                            continue
                    else:
                        ci, ri = info[i]["ends"][ei]
                        cj, rj = info[j]["ends"][ej]
                        if not (math.isfinite(ri) and math.isfinite(rj)) or abs(ri - rj) > STITCH_RADIUS_FRAC * max(ri, rj):
                            continue  # the curvature AT this end, not the raw path's overall (possibly
                            # compound) fit -- see _end_circle
                        on_i = ci is None or abs(float(np.hypot(*(pj - ci))) - ri) < STITCH_ON_CIRCLE
                        on_j = cj is None or abs(float(np.hypot(*(pi - cj))) - rj) < STITCH_ON_CIRCLE
                        if not (on_i and on_j):
                            continue
                    hi = info[i]["h0"] if ei == 0 else info[i]["h1"]
                    hj = info[j]["h0"] if ej == 0 else info[j]["h1"]
                    # one path arrives where the other leaves (ei=1,ej=0 or ei=0,ej=1): headings must
                    # point the SAME way through the join; two paths meeting end-to-end or start-to-start
                    # are drawn in opposite directions, so one heading must be reversed to compare
                    same_dir = (ei == 1 and ej == 0) or (ei == 0 and ej == 1)
                    agree = (hi @ hj) if same_dir else -(hi @ hj)
                    ang = math.degrees(math.acos(np.clip(agree, -1.0, 1.0)))
                    if ang <= STITCH_TANGENT_DEG:
                        pairs.append((gap, i, ei, j, ej))
    pairs.sort(key=lambda t: t[0])
    used_end, join_map = set(), {}
    for gap, i, ei, j, ej in pairs:
        if (i, ei) in used_end or (j, ej) in used_end or find(i) == find(j):
            continue  # an endpoint joins at most one other path; a path never chains into its own group twice
        used_end.add((i, ei)); used_end.add((j, ej))
        join_map[(i, ei)] = (j, ej); join_map[(j, ej)] = (i, ei)
        ri, rj = find(i), find(j)
        uf[ri] = rj
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    groups = []
    for members in comps.values():
        if len(members) == 1:
            groups.append({**raws[members[0]], "n_merged": 1})
            continue
        free = [(i, e) for i in members for e in (0, 1) if (i, e) not in join_map]
        cur_i, enter_e = free[0] if free else (members[0], 0)  # a closed loop (shouldn't happen for a
        # drawn boundary curve) falls back to an arbitrary start rather than walking forever
        pts_out, visited = [], set()
        while True:
            visited.add(cur_i)
            P = raws[cur_i]["pts"]
            seg = P if enter_e == 0 else P[::-1]
            pts_out.extend(seg.tolist() if not pts_out else seg[1:].tolist())
            nxt = join_map.get((cur_i, 1 - enter_e))
            if nxt is None or nxt[0] in visited:
                break
            cur_i, enter_e = nxt
        groups.append({"pts": np.array(pts_out), "width": raws[members[0]]["width"],
                       "ticks_ok": any(raws[i]["ticks_ok"] for i in members), "n_merged": len(members)})
    return groups


CHORD_REJECTS = [0]  # module-level counter: candidate spans dropped by chord_ok below, for the bench report


def chord_ok(p0, p1, want_ft, scale, tol):
    """An arc (or a run of facets standing in for one) is never shorter than the straight chord between
    its own ends -- a candidate span whose endpoints are already farther apart than the printed length is
    not that length's run, whatever its facet lengths sum to (R-10434.1's 31.80' matching a 306 ft curve
    run this way, loop6 leg B)."""
    ok = float(np.hypot(*(np.asarray(p1) - np.asarray(p0)))) * scale <= want_ft + tol
    if not ok:
        CHORD_REJECTS[0] += 1
    return ok


def span_for(piece, want_ft, scale, chains):
    """The breaks on a drawn run (circles, line ends, crossings) are candidate endpoints; the printed
    distance says which pair. Among the contiguous spans of pieces on the piece's run, the one whose
    length matches the printed distance, if exactly one does; else the piece itself. The span carries
    a note of how many pieces it joined."""
    if want_ft is None or "run" not in piece:
        return piece
    run = sorted((c for c in chains if c.get("run") == piece["run"]), key=lambda c: c["s0"])
    if len(run) < 2:
        return piece
    k = next(i for i, c in enumerate(run) if c["s0"] == piece["s0"])
    tol = 1.0 + 0.001 * want_ft
    hits = []
    for i in range(0, k + 1):
        for j in range(k, len(run)):
            L = (run[j]["s1"] - run[i]["s0"]) * scale
            if abs(L - want_ft) <= tol and chord_ok(run[i]["p0"], run[j]["p1"], want_ft, scale, tol):
                hits.append((i, j))
    if len(hits) != 1:
        return piece
    i, j = hits[0]
    if (i, j) == (k, k):
        return piece
    s0, s1 = run[i]["s0"], run[j]["s1"]
    return {**piece, "p0": run[i]["p0"], "p1": run[j]["p1"], "dir": local_fit_dir(piece["_pts"], s0, s1, piece["dir"]),
            "len_pt": float(s1 - s0), "s0": s0, "s1": s1, "joined": j - i + 1}


def chord_span(seed, want_ft, scale, arcs):
    """A label beside a curved piece cites the CHORD between the piece's ends, not the arc length
    (loop6 leg C rule 2). Where the printed distance is known, the contiguous run of same-parent pieces
    (leg A/leg6A's parent/seq grouping) whose chord -- the straight line between the run's own two end
    pieces' endpoints -- matches it within SMALL wins, if exactly one run does; else the seed piece's
    own ends. Loop4's chord rule keyed off a parenthesised arc value and was deleted; this one is keyed
    on geometry (the label sits along a curve), so it fires on a different, disjoint set of labels."""
    if want_ft is None or "seq" not in seed:
        return seed
    run = sorted((x for x in arcs if x.get("parent") == seed.get("parent") and "seq" in x), key=lambda x: x["seq"])
    if len(run) < 2:
        return seed
    k = next(i for i, x in enumerate(run) if x is seed)
    tol = 1.0 + 0.001 * want_ft
    hits = [(i, j) for i in range(0, k + 1) for j in range(k, len(run))
            if abs(float(np.hypot(*(run[j]["pts"][-1] - run[i]["pts"][0]))) * scale - want_ft) <= tol]
    if len(hits) != 1 or hits[0] == (k, k):
        return seed
    i, j = hits[0]
    return {**seed, "_p0": run[i]["pts"][0], "_p1": run[j]["pts"][-1]}


def touches_label(chain, labels_tree, labels):
    """A chain running along a label with an end inside its box is that label's underline (a callout's
    separator line), not a line the label describes."""
    for p in (chain["p0"], chain["p1"]):
        for k in labels_tree.query_ball_point(p, 60):
            c, u, n, hw, hh, gh = label_box(labels[k])
            d = p - c
            inside = abs(d @ u) < hw + 0.5 * gh and abs(d @ n) < hh + 0.5 * gh
            if inside and abs(chain["dir"] @ u) > 0.9:  # an underline
                return True
    return False


NO_TAG_RE = re.compile(r"^([LC])(\d+)(\(T\))?$")


def line_curve_table_regions(blocks, reach=250):
    """Bounding box of each L#/C# course table (read_shx.build_tables' own NO.-column reader), re-derived
    independently per table. That reader caps a row's rightward reach at the next same-lettered NO. column
    found ANYWHERE on the sheet, with no check that the two are the same table -- on this sheet three
    separate curve tables (C1-5, C6-12, C13-29) all start their NO. column near x 718-721, one of them
    700+ pt below the L34-45 line table, so L34-45's row cap lands at x 707, short of its own distance
    column at x 724: tables.json's _regions for that row is then too narrow and the distance cell is
    never masked -- it gets read as a second, spurious distance label. Chain consecutive L#/C# tags at one
    x and one pitch (same rule read_shx.py uses, so a scattered look-alike still can't fake it) and widen
    each row to its own furthest cell within `reach`: never another column's x, so a same-lettered column
    elsewhere on the sheet can't cap this one."""
    tagged = [(b, m[1], int(m[2])) for b in blocks for m in [NO_TAG_RE.match(b["text"].strip())] if m]
    used, regions = set(), []
    for i, (b0, letter0, num0) in enumerate(tagged):
        if i in used:
            continue
        col = [(i, b0, num0)]
        pitch = None
        while True:
            by = col[-1][1]["cy"]
            nxt = [(j, bj, nj) for j, (bj, lj, nj) in enumerate(tagged)
                   if j not in used and j not in {c[0] for c in col} and lj == letter0 and nj == num0 + len(col)
                   and abs(bj["cx"] - b0["cx"]) < 8 and 6 < bj["cy"] - by < 30 and (pitch is None or abs(bj["cy"] - by - pitch) < 4)]
            if not nxt:
                break
            j, bj, nj = nxt[0]
            pitch = pitch or (bj["cy"] - by)
            col.append((j, bj, nj))
        if len(col) < 4:
            continue
        used.update(c[0] for c in col)
        band = max(6.0, 0.6 * (pitch or 14))
        xs = [c[1]["cx"] for c in col]
        ys = [c[1]["cy"] for c in col]
        x1 = max(xs)
        for _, brow, _ in col:
            row = [ob for ob in blocks if ob is not brow and not NO_TAG_RE.match(ob["text"].strip())
                   and 0 < ob["cx"] - brow["cx"] < reach and abs(ob["cy"] - brow["cy"]) < band]
            if row:
                x1 = max(x1, max(ob["cx"] + ob.get("w", 40) / 2 for ob in row))
        regions.append([round(min(xs) - 20), round(min(ys) - 16), round(x1 + 20), round(max(ys) + 16)])
    return regions


def alignment_table_regions(blocks, gap=30):
    """Bounding box of each 'ALIGNMENT DATA' (or coordinates) table keyed by its STATION/NORTHING/EASTING
    header row: alphabet.py's tables.json only reads the L#/C# line and curve tables, so this one's station
    numbers and coordinates would otherwise be read as sheet labels. Header row, then every block below it
    in that column band, stopping at a gap -- same shape as tables.json's own _regions."""
    headers = [b for b in blocks if b["text"].strip() in ("STATION", "NORTHING", "EASTING")]
    regions = []
    for st in (h for h in headers if h["text"].strip() == "STATION"):
        row = [st] + [h for h in headers if h is not st and abs(h["cy"] - st["cy"]) < 15 and h["cx"] > st["cx"]]
        x0 = min(h["cx"] - h.get("w", 40) / 2 for h in row) - 60  # room for the row letters (A, B, C...)
        x1 = max(h["cx"] + h.get("w", 60) / 2 for h in row) + 20
        col = sorted((b for b in blocks if x0 <= b["cx"] <= x1 and b["cy"] > st["cy"]), key=lambda b: b["cy"])
        y1 = st["cy"] + 15
        for b in col:
            if b["cy"] - y1 > gap:
                break
            y1 = max(y1, b["cy"] + 15)
        regions.append((round(x0), round(st["cy"] - 25), round(x1), round(y1)))
    return regions


def sheet_lines(page, blocks):
    """What a label can describe: black linework, minus leaders (their curly paths, then their stubs and
    the callout underlines, which end inside a label's box), minus thin 7-pt stationing ticks; split
    at junctions. Returns (chains, circles, leader paths, segments)."""
    _, circles = segments(page)
    paths, leader_pids = leaders(page, circles)
    segs = [s for s in linework_segments(page, max_gray=0.2) if s[3] not in leader_pids]
    ltree = cKDTree(np.array([[b["cx"], b["cy"]] for b in blocks]))
    starts = cKDTree(np.array([p[0] for p in paths])) if paths else None
    stub = lambda c: starts is not None and c["len_pt"] < 30 and min(starts.query(c["p0"])[0], starts.query(c["p1"])[0]) < 0.6  # joined to a leader
    chains = [c for c in lines_on_sheet(segs, circles) if c["len_pt"] >= 1 and not (c["width"] < 0.8 and c["len_pt"] < 9)  # a 1.60 ft segment is 1.2 pt
              and not stub(c) and not (c["len_pt"] < 150 and touches_label(c, ltree, blocks))]
    return split_chains(chains, circles), circles, paths, segs



def _dash_points(page, blocks):
    """Every short stroke endpoint (dashes.py's own <10 pt line-item decomposition, any CAD layer --
    unlike collect_dashes(), which only trusts the named easement/parcel-segment layers) that isn't
    part of a real text block's own oriented box. A detail inset's dashed ring can live on any
    furniture layer, and at some drafters' scale (R-10434.1's DETAIL "D") the ring's own dash marks are
    exactly glyph-sized, so the usual 'small multi-stroke path is a character' rect-size rule
    (linework_segments/arcs_on_sheet) can't tell a dash from a digit there -- excluding by the blocks
    the reader already placed can."""
    from dashes import _strokes
    if not blocks:
        return []
    centers = np.array([[b["cx"], b["cy"]] for b in blocks])
    btree = cKDTree(centers)
    reach = max(float(np.median([b["w"] for b in blocks])), 20.0)

    def in_text(p):
        for j in btree.query_ball_point(p, reach):
            b = blocks[j]
            c, u, n = frame(b)
            if abs((p - c) @ u) < b["w"] / 2 and abs((p - c) @ n) < b["h"] / 2:
                return True
        return False

    out = []
    for d in page.get_drawings():
        if d["type"] != "s":
            continue
        for a, b in _strokes(d):
            if not in_text((a + b) / 2):
                out.append((a, b))
    return out


def _circle_clusters(strokes, reach=15.0, min_pts=8):
    """Connected components of dash points within `reach` pt of one another, each fitted to a circle
    (Kasa least squares): radius, residual, and arc coverage (360 minus the widest angular gap around
    the fitted centre). A dashed ring made of two tangent loops (a bowtie -- R-10434.1's DETAIL "D")
    comes back as one wider, higher-residual circle spanning both; that still clears the radius/
    coverage gates below and still masks both loops' labels, so it is kept as one region rather than
    solved as two true circles."""
    pts = np.array([q for a, b in strokes for q in (a, b)])
    if len(pts) < min_pts:
        return []
    tree = cKDTree(pts)
    pairs = tree.query_pairs(reach, output_type="ndarray")
    if len(pairs) == 0:
        return []
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(pts), len(pts)))
    ncomp, labels = connected_components(g, directed=False)
    out = []
    for k in range(ncomp):
        P = pts[labels == k]
        if len(P) < min_pts:
            continue
        x, y = P[:, 0], P[:, 1]
        sol, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x ** 2 + y ** 2, rcond=None)
        cx, cy, cc = sol
        r = math.sqrt(max(cc + cx ** 2 + cy ** 2, 0))
        if not (0 < r < 1e4):
            continue
        resid = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - r) ** 2)))
        ang = np.sort(np.degrees(np.arctan2(y - cy, x - cx)) % 360)
        gaps = np.diff(np.concatenate([ang, ang[:1] + 360]))
        cov = 360 - float(gaps.max())
        out.append({"cx": float(cx), "cy": float(cy), "r": r, "resid": resid, "cov": cov, "n": len(P)})
    return out


def _rim_crossing(cx, cy, r, gh, leader_paths, segs):
    """A leader or plain line with one end inside this circle and the other clearly (2 glyph heights)
    outside its rim -- the 'see detail' tie (rule b) used when no caption reads. R-10741.2's DETAIL "A"
    has no readable caption (OCR reads it as CJK glyphs) but its own N51 deg 26'23"E boundary runs from
    the inset's vertex, out through the dashed rim, onto the main sheet -- that crossing is the tie."""
    c = np.array([cx, cy])
    tol = 2.0 * gh
    pairs = [(p0, p1) for p0, p1, *_ in leader_paths] + [(a, b) for a, b, w, pid in segs]
    for a, b in pairs:
        da, db = float(np.hypot(*(a - c))), float(np.hypot(*(b - c)))
        if (da < r and db > r + tol) or (db < r and da > r + tol):
            return True
    return False


_CJK_RE = re.compile(r"[一-鿿]")  # this drafter's DETAIL "A" caption OCRs as CJK ideographs
# (R-10741.2, loop6 leg F) -- a real signal that a caption block sits there but reads corrupted, unlike
# a bare "no non-ASCII text nearby" test, which would also trip on every ordinary degree-sign bearing

INSET_GH_MULT = 5.0  # radius must exceed this many local glyph heights. The rule of thumb was 8x;
# measured against R-10434.1's DETAIL "D" (the only readable-caption case on hand, two tangent dashed
# loops) its true radius is 5.6-9.5x its own interior label's glyph height depending on which loop --
# 8x excludes the loop that holds 14.91', so this is calibrated down to 5x. Still clears R-10741.2's
# DETAIL "A" (15x) by a wide margin; a vertex circle never reaches this test at all (solid, not dashed,
# so it never enters _dash_points' pool), and an open R/W curve is excluded by the coverage gate below
INSET_GH_MAX = 30.0  # and radius must stay under this many local glyph heights: a detail inset is a
# LOCAL enlargement, never sheet-spanning -- caught on R-10434.3, whose sparse dash points near one
# real "NOT TO SCALE" caption chained, through a wide connected-components reach, into one 665 pt
# (62x) blob covering 765 labels and most of the sheet (resid 44% of r, plainly not a circle at all).
# The two real insets on hand top out at 15x (R-10741.2's DETAIL "A"); 30x leaves a wide margin


def detail_insets(blocks, page, glyph_h_med):
    """Not-to-scale detail insets, found by their drawn geometry instead of a readable caption: a
    dashed closed curve (any CAD layer, dashes.py's short-stroke decomposition) whose fitted circle has
    radius > INSET_GH_MULT glyph heights and arc coverage > 300 deg, containing real text, tied to
    being an inset either by a caption ('N.T.S.'/'NOT TO SCALE' -- NTS_RE) within 5 glyph heights of
    its rim, or -- when no caption reads -- a leader or plain line crossing from its rim to a point
    clearly outside it. Works where OCR garbles the caption into CJK glyphs (R-10741.2's DETAIL "A")
    and where 'DETAIL "X"' is never read at all at this drafter's font, only the plainer 'NOT TO SCALE'
    beside it (R-10434.1's DETAIL "D"). Returns (regions, report): regions are the fired circles
    [{"cx","cy","r","gh"}], for masking labels and excluding linework inside them from every candidate
    pool; report is every candidate circle this sheet's geometry produced, fired or not, with its
    radius in glyph heights and coverage (leg6F_insets.png)."""
    clusters = _circle_clusters(_dash_points(page, blocks))
    btree = cKDTree(np.array([[b["cx"], b["cy"]] for b in blocks])) if blocks else None
    leader_paths, _ = leaders(page)
    segs = linework_segments(page, max_gray=0.6)
    report, regions = [], []
    for cl in clusters:
        cx, cy, r, cov = cl["cx"], cl["cy"], cl["r"], cl["cov"]
        inside = []
        if btree is not None and r > 0:
            for j in btree.query_ball_point([cx, cy], r):
                b = blocks[j]
                if math.hypot(b["cx"] - cx, b["cy"] - cy) < r:
                    inside.append(b)
        gh = float(np.median([b["glyph_h"] for b in inside])) if inside else glyph_h_med
        row = {"cx": cx, "cy": cy, "r_pt": r, "r_gh": r / gh, "cov": cov, "resid": cl["resid"],
               "n_labels": len(inside), "fired": False, "reason": ""}
        if not inside or r <= INSET_GH_MULT * gh or r > INSET_GH_MAX * gh or cov <= 300:
            report.append(row)
            continue
        inside_ids = {id(x) for x in inside}
        near = [b for b in blocks if id(b) not in inside_ids and math.hypot(b["cx"] - cx, b["cy"] - cy) < r + 5 * gh]
        cap = next((b for b in near if NTS_RE.search(b["text"])), None)
        # a readable caption that names a *different* scale ("SCALE: 1"=100'", a to-scale enlargement,
        # not a not-to-scale one -- R-10434.1's real DETAIL "E") is positive evidence this circle is NOT
        # an NTS inset: the leader-tie fallback (rule b) is for when no caption reads at all (garbled
        # OCR), not for overriding one that reads and says something else
        other_caption = cap is None and any(re.search(r"\bSCALE\b", b["text"], re.I) or DETAIL_RE.search(b["text"]) for b in near)
        garbled = any(_CJK_RE.search(b["text"]) for b in near)  # a caption block IS there, reading corrupted
        if cap is not None:
            row["fired"], row["reason"] = True, f"caption {cap['text']!r}"
        elif not other_caption and garbled and _rim_crossing(cx, cy, r, gh, leader_paths, segs):
            row["fired"], row["reason"] = True, "garbled caption + leader/line crosses rim"
        report.append(row)
        if row["fired"]:
            regions.append({"cx": cx, "cy": cy, "r": r, "gh": gh})
    return regions, report


def run_sum(drawn, Ls):
    """Whether a drawn run equals the sum of several record arcs that share it because the boundary
    between them isn't drawn (loop2 legC / STATE.md D3-6 / loop5 legB): the "pass as a run of N" rule.
    Shared by the inline L= labels below and by tables.py's table-tag curves."""
    total = sum(Ls)
    return total, len(Ls) > 1 and abs(drawn - total) <= DIST_TOL + 0.0005 * total


def parent_window(arcs, seed, want, scale):
    """The contiguous window of same-parent pieces (in seq order) around `seed` whose printed length
    `want` it alone -- not shared with any other label/tag -- uniquely matches (leg6A's search): tried
    before a label or table tag is ever grouped with a neighbour (leg8A). `seed` must be one of
    split_at's own pieces (carries "seq"), never the whole unsplit candidate, which is never itself
    part of a sum-group. Returns the window as a list of pieces in seq order, or None."""
    if "seq" not in seed:
        return None
    run = sorted((x for x in arcs if x.get("parent") == seed["parent"] and "seq" in x), key=lambda x: x["seq"])
    k = next(i for i, x in enumerate(run) if x is seed)
    tol = DIST_TOL + 0.0005 * want
    hits = [(i, j) for i in range(0, k + 1) for j in range(k, len(run))
            if abs(sum(x["len_pt"] for x in run[i:j + 1]) * scale - want) <= tol
            and chord_ok(run[i]["pts"][0], run[j]["pts"][-1], want, scale, tol)]
    if len(hits) == 1 and hits[0] != (k, k):
        i, j = hits[0]
        return run[i:j + 1]
    return None


def _pool_cache_key(blocks):
    """Cache identity for build_pool's (page, blocks): the PDF's own path + mtime (the page content) plus
    the exact blocks list and the ASSOC diagnostic flags, which are the only things build_pool's result
    can depend on. Hashed with hashlib (not the builtin hash()), which is salted per-process and would
    never agree between checks.py's and tables.py's separate interpreters."""
    h = hashlib.sha256()
    h.update(str(PDF).encode())
    h.update(str(PDF.stat().st_mtime_ns).encode())
    h.update(json.dumps(blocks, sort_keys=True, default=str).encode())
    h.update(",".join(sorted(ASSOC)).encode())
    for src in sorted(Path(__file__).parent.glob("*.py")):  # any code edit invalidates: a stale pool must never
        h.update(src.read_bytes())                           # outlive the code that built it
    return h.hexdigest()


POOL_CACHE_FILE = "_pool_cache.pkl"


def build_pool(page, blocks):
    """Every candidate a label can be checked against: straight-line chains (split at junctions/circles),
    curved-piece arcs (bezier/polyline curves and dashed trains, split the same way), leader tips, the
    furniture/NTS mask regions. Shared by main() and by any crop/report tool that needs the identical
    pool checks.py itself measured against (leg6A_crops.py), so a diagnostic never silently drifts from
    what the checker actually saw.
    Loop11 perf fix: checks.py and tables.py both call this with the identical (PDF, blocks) -- curve
    stitching, dash-dot chaining and every split_at cut redone from scratch a second time, ~all of
    tables.py's own runtime. Cached to disk (OUT/_pool_cache.pkl) keyed on _pool_cache_key; a stale,
    missing or unreadable cache just recomputes, so nothing is ever trusted unread."""
    key = _pool_cache_key(blocks)
    cache_path = OUT / POOL_CACHE_FILE
    if cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                cached_key, cached_pool = pickle.load(f)
            if cached_key == key:
                return cached_pool
        except Exception:
            pass  # any read/unpickle problem: fall through and recompute, same as a cold cache
    pool = _build_pool_uncached(page, blocks)
    try:
        with open(cache_path, "wb") as f:
            pickle.dump((key, pool), f)
    except OSError:
        pass
    return pool


def _build_pool_uncached(page, blocks):
    chains, circles, paths, segs = sheet_lines(page, blocks)
    glyph_h_med = float(np.median([b["glyph_h"] for b in blocks])) if blocks else 6.0
    # curves on this sheet are mostly polylines (Civil 3D export), a few are beziers; a drawn curve runs
    # through several record arcs, so it is cut where lines meet it and at vertex circles
    junction_lines = [c for c in chains if c["len_pt"] >= 9]
    # radial ticks mark a record-arc boundary on the thin alignment curves same as tables.py (loop2 leg C:
    # neither branch below used to pass ticks to split_at, so a curve with no line/circle at the boundary
    # -- most of them -- was never cut there at all); kept with their own direction so split_at can tell
    # a real tick (crosses the curve) from a dash of a line merely running alongside it. Built from `segs`
    # (leaders already excluded), not a fresh linework_segments() call -- a leader's own curly path has
    # 5-9 pt straight sub-segments right at its tip, which is exactly where a check looks for a cut
    ticks = [((s0 + s1) / 2, (s1 - s0) / np.hypot(*(s1 - s0))) for s0, s1, w, _ in segs if w < 0.8 and 5 < np.hypot(*(s1 - s0)) < 9]
    # a bezier path is one drawn object and can be a compound curve spanning several record arcs (the
    # long R/W curves): it used to be kept whole here while the polyline branch below was already split,
    # so a leader tip landed dead-on but the "arc" was the whole compound run. But a short chain's end
    # lands near a curve by coincidence far more often than a real boundary line meets one, and a curve
    # that was never compound in the first place needs no cut at all -- so the whole path is always kept
    # as a candidate too, and its split pieces are added alongside it, not in place of it: whichever one
    # actually matches the printed length wins, on a curve-by-curve basis instead of one sheet-wide rule
    # every piece split_at cuts from one original curve object carries a "parent" tag shared by every
    # piece cut from that SAME object: radius_pt can't serve as the sibling key (lines_on_sheet's
    # polyline branch -- most of this drafter's curves -- hardcodes it NaN, only the bezier branch fits a
    # real one), and a fresh circle re-fit per piece (leg6A, first attempt) is too noisy over a long,
    # many-point compound-curve sliver to match its own siblings reliably. A plain counter, not id() of
    # the loop's own x/c/t dict (leg6A, second attempt): those are unreferenced the moment their loop
    # body ends, and CPython's allocator reused the freed address for the very next same-sized dict often
    # enough to splice unrelated curves' pieces into one "parent" (measured on r10434_1: an 869 ft curve's
    # group pulled in an 800 ft piece from a different curve entirely) -- a strictly incrementing int
    # can't collide.
    # loop9 leg A rule 1: a compound record curve some drafters draw as several separate PDF paths end to
    # end (not merely several record arcs along one path, which split_at already handles) is chained into
    # ONE raw candidate here, before any of them are cut -- so a window search can cross the join. Only
    # the raw whole-curve candidates feed this (bezier objects, polyline curved chains); a merged group's
    # own three-point-circle radius/width stand in for the whole run's, same as a single bezier path's
    # always did. Untouched (n_merged == 1) curves replay byte-for-byte identical to before this rule.
    bez_raw = [{"pts": x["pts"], "len_pt": x["len_pt"], "radius_pt": x["radius_pt"], "width": x["width"],
                "ticks_ok": x["width"] < 0.8, "source": "bezier"}
               for x in arcs_on_sheet(page) if max(x["color"]) < 0.2 and np.hypot(*(x["pts"][0] - x["pts"][-1])) > 2]
    poly_raw = [{"pts": c["pts"], "len_pt": c["len_pt"], "radius_pt": c["radius_pt"], "width": c["width"],
                 "ticks_ok": c["width"] < 0.8, "source": "poly"}
                for c in lines_on_sheet(segs, circles, max_turn_deg=20.0) if c["n"] >= 3 and c["len_pt"] > 12]
    # leg9A attempt 2: tried a 6-glyph-height bridge (join across a wipeout/crossing-leader gap, gated
    # on end tangent + radius + the far point landing on the near arc's own fitted circle -- see
    # chain_curve_paths). Measured, not kept: C21's own nearest candidate at that reach (10.65 pt away)
    # fails all three gates at once (tangent off 8.4 deg, radius off 9.3%, on-circle residual 2.4 pt) --
    # a genuinely different curve, not C21 obscured by a wipeout -- so the bridge gains C21 nothing, and
    # it cost a real regression elsewhere: r10434_3's C33 (radius pass at 2884' record / 2879.66' measured,
    # -0.15%) re-parents under the wider reach to a piece measuring 2925.48' (+1.44%), crossing tables.py's
    # 1% RADIUS_TOL and losing a pass. Bridge back to 0 (the original, proven-safe tight join only); the
    # widened form stays in chain_curve_paths (bridge=<pt>) for the record and for re-measuring later.
    curve_groups = chain_curve_paths(bez_raw + poly_raw, bridge=0.0)
    stitch_merges = sum(1 for g in curve_groups if g["n_merged"] > 1)
    stitch_paths = sum(g["n_merged"] for g in curve_groups if g["n_merged"] > 1)
    parent_id = itertools.count()
    arcs = []
    for g in curve_groups:
        parent = next(parent_id)
        merged = g["n_merged"] > 1
        radius_pt = circle_fit_lsq(g["pts"])[1] if merged else g["radius_pt"]  # a merged group's own fit
        # (least-squares over every point -- circumradius3's 3-point sample is unreliable this long, same
        # reasoning as chain_curve_paths' own join test); an untouched path keeps exactly the value it
        # always carried (real for a bezier, NaN for a polyline)
        if merged or g["source"] == "bezier":
            arcs.append({"pts": g["pts"], "len_pt": float(np.sum(np.hypot(*np.diff(g["pts"], axis=0).T))),
                         "radius_pt": radius_pt, "width": g["width"], "parent": parent})  # the whole, unsplit: no "seq" (never itself part of a sum-group)
        pieces = split_at(g["pts"], circles, junction_lines, ticks=ticks if g["ticks_ok"] else ())
        # a merged group, like a polyline curve always did, is checkable piece by piece even where
        # split_at found no internal cut at all (a single-piece "run of 1"); an untouched bezier path
        # keeps its old rule -- only add pieces when it's actually cut, since its whole entry above
        # already covers the uncut case and a duplicate identical candidate would just be noise
        if merged or g["source"] == "poly" or len(pieces) > 1:
            for i, P in enumerate(pieces):
                arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "radius_pt": radius_pt, "width": g["width"], "parent": parent, "seq": i})
    # the dashed easement/parcel line (leg B, widened leg 5b): each dash is its own path, so nothing
    # above sees it; chained into trains (dashes.py) and split at the same circles/junctions as the
    # solid curves, so a train spanning several record segments (compound curve) becomes one arc per
    # segment. Most of this drafter's dashed runs are a curve (an easement alongside a R/W arc), but
    # some are straight (a dashed lot/parcel line): those go into the straight-line `chains` pool too,
    # tagged "dashed", so a bearing/distance label beside one is checkable there, not only as an arc.
    # A short fragment (dash-chaining noise, or a genuinely short dash run) must not become an arc
    # candidate either way -- it can win "nearest" over the real, longer curve/line by sheer proximity
    # (loop3 leg5 attempt 1: a stray 12 ft dash piece beat the correct 573 ft arc for an unrelated
    # label) -- so every piece is held to the same 5-glyph-height floor the standalone-L arc search uses.
    from dashes import collect_dashes, dash_trains, dashdot_trains
    dash_floor = 5.0 * glyph_h_med
    RESID_TOL = 2.0  # pt: a fitted line's max perpendicular residual, for a bridged train whose raw
    # heading spread reads >2 deg even though it is straight -- the spread test measures dash-to-dash
    # turn one step at a time and a few tenths of a degree of chaining noise compounds over many dashes,
    # while the fit sees the whole run at once; still twice SIDE_TOL (the per-step lateral tolerance
    # chaining itself already enforces), so a run that is genuinely curved (not noisy-straight) still fails
    # loop9 leg A rule 2: a dash-dot boundary (Presidio's C20) chains into a train the same way, joining
    # the same candidate pool -- split at the same circles/junctions, held to the same floor, admitted as
    # a straight chain the same way a train that turns out not to be curved already is
    dd_trains = dashdot_trains(page, blocks, bridge=6.0 * glyph_h_med)
    # each piece from a dash-dot train (not a plain single-pattern dash) is marked "dashdot": True -- a
    # dash-dot pattern this generic ("any layer", loop9 leg A rule 2's own docstring) is far more likely
    # to be a road-alignment centerline than the specific record boundary a nearby unrelated small curve's
    # table row names (measured on r10434_3: C6/C32/C9/C33 all picked up the SAME wide alignment
    # centerline train as their nearest "beside" candidate, none of them actually its record). tables.py's
    # own no-leader "beside" curve search excludes this marker; a leader landing squarely on the piece
    # (Presidio's C20) is a much stronger signal and still uses it.
    for t, is_dashdot in [(t, False) for t in dash_trains(collect_dashes(page), bridge=6.0 * glyph_h_med)] + [(t, True) for t in dd_trains]:
        if len(t["pts"]) < 3:
            continue
        parent = next(parent_id)
        for i, P in enumerate(split_at(t["pts"], circles, junction_lines)):
            L = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
            if L <= dash_floor:
                continue
            arcs.append({"pts": P, "len_pt": L, "radius_pt": t["radius_pt"], "width": 0.84, "parent": parent, "seq": i, "dashdot": is_dashdot})
            seg = np.diff(P, axis=0)
            headings = np.degrees(np.arctan2(seg[:, 1], seg[:, 0]))
            ref = headings[0]
            straight = np.all(np.abs((headings - ref + 180) % 360 - 180) < 2.0)  # every dash within 2 deg of one heading
            if not straight and len(P) >= 3:
                c = P.mean(axis=0)
                _, _, vt = np.linalg.svd(P - c)
                n = np.array([-vt[0][1], vt[0][0]])
                straight = float(np.max(np.abs((P - c) @ n))) < RESID_TOL
            if straight:
                d = P[-1] - P[0]
                chord = float(np.hypot(*d))
                if chord > 3:
                    chains.append({"p0": P[0], "p1": P[-1], "dir": d / chord, "len_pt": chord, "width": 0.84, "n": len(P), "dashed": True})
    tips = tag_leaders(blocks, paths)
    from overlay import FURNITURE
    FURNITURE = list(FURNITURE) + alignment_table_regions(blocks) + line_curve_table_regions(blocks)  # tables.json's _regions plus tables it doesn't cover
    NTS, NTS_REPORT = detail_insets(blocks, page, glyph_h_med)
    if NTS:  # linework INSIDE a fired inset is excluded from every candidate pool (loop6 leg F): the
        # bubble's own little enlarged jog must never become a candidate for a main-sheet label. A
        # single midpoint sample is the wrong test for a long, unsplit compound curve that merely
        # passes near/through an inset drawn overlapping the main plan (r10434_1 lost 2 real arc passes
        # this way, first attempt) -- a piece is excluded only when it is essentially the inset's own
        # linework: both chain endpoints inside, or almost all of an arc's sampled points inside
        def _inside_nts(p):
            return any(math.hypot(p[0] - c["cx"], p[1] - c["cy"]) < c["r"] for c in NTS)
        chains = [c for c in chains if not (_inside_nts(c["p0"]) and _inside_nts(c["p1"]))]
        arcs = [x for x in arcs if np.mean([_inside_nts(p) for p in x["pts"]]) < 0.8]
    return {"chains": chains, "circles": circles, "paths": paths, "segs": segs, "arcs": arcs, "tips": tips,
            "FURNITURE": FURNITURE, "NTS": NTS, "NTS_REPORT": NTS_REPORT, "junction_lines": junction_lines,
            "ticks": ticks, "glyph_h_med": glyph_h_med, "dashdot_trains": dd_trains,
            "stitch_merges": stitch_merges, "stitch_paths": stitch_paths}


def selftest():
    """Loop17 leg B: wrong_line_likely's distance rule must catch an undershoot (a wrong-line pick
    whose drawn piece is a small fraction of a long printed record) exactly as readily as it already
    catches the mirror-image overshoot -- and must never flag the calibrated real-disagreement example
    its own docstring cites (330.77 ft off / 128.8% of printed, an overshoot, kept a FAIL on purpose)."""
    # Presidio S70d50'46"W 359.00' matched to a 28 ft tick (loop17 leg B): off = drawn - printed
    assert wrong_line_likely("distance", 28.23 - 359.00, 359.00) is True, "undershoot must be caught"
    # symmetric mirror: the same ratio the other way round (a candidate ~12.7x too long) already was
    off = 359.00 * 12.7 - 28.23
    assert wrong_line_likely("distance", off, 28.23) is True, "overshoot side unchanged"
    # the calibration example this cut must never flip (an overshoot inside the old 200% cut already)
    assert wrong_line_likely("distance", 330.77, 256.75) is False, "calibrated real disagreement must stay a FAIL"

    # loop17 leg H: attach_shared_curve_radius must carry R/delta onto an already-placed "arc" label
    # sharing the curve-data block's own region (the len_checked case) -- never onto an unrelated region,
    # never overwrite a label that already has its own (possibly different-source) R, and fill at most
    # the one label lacking R in that region.
    region_a, region_b = (10, 10, 20, 20), (500, 500, 510, 510)
    lab_needs_r = {"kind": "arc", "printed": "L=59.06'", "ft": 59.06, "region": region_a}
    lab_has_r = {"kind": "arc", "printed": "L=13.27'", "ft": 13.27, "region": region_a, "R": 15.0, "delta": 50.7}
    lab_elsewhere = {"kind": "arc", "printed": "L=999.00'", "ft": 999.0, "region": region_b}
    by_region = {}
    for lab in (lab_needs_r, lab_has_r, lab_elsewhere):
        by_region.setdefault(lab["region"], []).append(lab)
    n = attach_shared_curve_radius(by_region, region_a, 1470.0, 2.3)
    assert n == 1, f"expected exactly the one region-A label lacking R to fill, got {n}"
    assert lab_needs_r["R"] == 1470.0 and lab_needs_r["delta"] == 2.3, "R/delta must land on the label missing them"
    assert lab_has_r["R"] == 15.0, "a label that already has its own R must never be overwritten"
    assert "R" not in lab_elsewhere, "a different region's label must never gain a radius it wasn't checked against"
    print("checks.py selftest: attach_shared_curve_radius OK (fills only the same-region label missing R, never overwrites, never leaks to another region)")
    # a small, real-looking disagreement on either side of 1.0x must never be flagged
    assert wrong_line_likely("distance", -21.62, 76.46) is False        # 28.3% undershoot
    assert wrong_line_likely("distance", 29.06, 22.56) is False         # 128.8% overshoot

    # loop17 leg D: fix_bearing_symbols canonicalises every degree/case OCR variant seen on the archive
    # (prime, asterisk, straight-quote-as-degree; lowercase compass letters) to exactly what BEAR/TOKEN
    # already expect, and must never touch a block with no bearing-shaped text in it at all.
    cases = [
        {"text": "S15°42'45\"w"},          # r10741.1: correct degree, lowercase compass
        {"text": "S42′35'48\"E"},          # r10741.1: prime as degree (curly, pre-normalize_quotes)
        {"text": "S25*49'47\"E 214.92'"},  # r10741.1: asterisk as degree, joined with its own distance
        {"text": "N18\"06'50\"E"},         # r10741: straight quote as degree (position, not char, tells it apart from the seconds mark)
        {"text": "no bearing here 165.86'"},
    ]
    normalize_quotes(cases)
    fix_bearing_symbols(cases)
    assert cases[0]["text"] == "S15°42'45\"W", cases[0]["text"]
    assert cases[1]["text"] == "S42°35'48\"E", cases[1]["text"]
    assert cases[2]["text"] == "S25°49'47\"E 214.92'", cases[2]["text"]
    assert cases[3]["text"] == "N18°06'50\"E", cases[3]["text"]
    assert cases[4]["text"] == "no bearing here 165.86'", cases[4]["text"]
    assert BEAR.match(TOKEN.findall(cases[0]["text"])[0])
    print("checks.py selftest: pass")


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    rot = np.degrees(np.arctan2(bb, a))
    blocks = json.loads((READS).read_text(encoding="utf-8")) + real_text_blocks(page)
    normalize_quotes(blocks)
    fix_bearing_symbols(blocks)
    set_decimals(blocks)
    pool = build_pool(page, blocks)
    chains, circles, paths, segs, arcs, tips = pool["chains"], pool["circles"], pool["paths"], pool["segs"], pool["arcs"], pool["tips"]
    FURNITURE, NTS = pool["FURNITURE"], pool["NTS"]

    def az_of(ln):
        """Grid azimuth of a drawn line (deg, clockwise from grid north), through the fit's rotation."""
        dx, dy = ln["dir"][0], -ln["dir"][1]
        return math.degrees(math.atan2(a * dx - bb * dy, bb * dx + a * dy)) % 360

    def dir_az(d):
        """Same as az_of, for a bare direction vector (a chord, not a chain)."""
        dx, dy = float(d[0]), -float(d[1])
        return math.degrees(math.atan2(a * dx - bb * dy, bb * dx + a * dy)) % 360
    rows, exceptions, labels, len_pending = [], [], [], []  # labels: every checked value with the line it
    # was measured on (sheet pt), for the traverse; len_pending: standalone L=/(T) labels whose own
    # length matched no drawn piece, resolved by run-sum grouping after every block is scanned (below)
    radials = []  # loop16 leg F: printed radial ("(R)") bearings, real record data with no drawn line
    # to check them against -- written to radials.json for traverse.py, never into labels.json (never
    # touches an existing check result; see the "bearing (R)" branch below)
    len_checked = set()  # id() of every block the standalone L=/(T) branch (below) already matched to a
    # drawn piece and passed. The curve-data fillet check (further down) skips only these: a joined block
    # whose L= is ALSO its own separate single-line block would otherwise pass twice for the identical
    # drawn piece. A block the standalone branch missed or deferred is NOT marked -- the fillet check's
    # radius match is a genuinely different search and gets its own try at exactly those

    def at_tip(bi, kind, want=None, want_az=None):
        """The line or arc a label's leader points at (within 4 pt of the arrowhead), if it has a leader.
        Busy vertex (loop6 leg B): several drawn lines can share the identical arrowhead. The piece(s)
        whose own endpoint truly IS the tip (not one merely passing near it) come first; where more than
        one does -- a real vertex, several record lines ending together -- the printed bearing (want_az,
        the OTHER value already sitting in the same bearing+distance block) decides among THEM before any
        length is even looked at, since a sibling piece's length can match the printed distance by sheer
        coincidence (measured: R-10434.3's 11.05' stub, wrong direction, beat its own 10.95' by chance).
        Only once bearing has picked (or had nothing to say) does length, then nearest, apply. Returns
        (led, segment, proven); led False = no leader, or the leader belongs to another value in the
        same block: fall back to 'beside'. proven (loop15, arc kind only -- always True for a line, out
        of this leg's scope) is False when the pick came from bare proximity (no length match) and the
        tip's own reach holds more than one candidate: a guess among several, not a leader landing on
        the one thing it points at."""
        if bi not in tips:
            return False, None, False
        tip, _, hsize = tips[bi]
        # a line's tip test stays a fixed 4 pt; an arc's tangent curves away under the arrowhead, so a
        # bigger drawn arrowhead can leave a bigger real gap between the tip corner and the curve -- still
        # a tip rule (scaled to what's actually drawn there), not a nearest-arc-by-distance guess
        reach = 4.0 if kind == "line" else max(4.0, 0.6 * hsize)
        if kind == "line":
            cands = [(seg_dist(tip, c["p0"], c["p1"]), c) for c in chains if seg_dist(tip, c["p0"], c["p1"]) < reach]
        else:
            cands = [(poly_dist(tip, x["pts"]), x) for x in arcs if poly_dist(tip, x["pts"]) < reach]
        if not cands:
            return True, None, False
        if want is not None:
            close = [t for t in cands if abs(t[1]["len_pt"] * scale - want) < 1.0]
            if close:
                return True, min(close, key=lambda t: t[0])[1], True  # length-verified: proven
            if sum(1 for t in blocks[bi]["text"].replace(" ", "").split("|") if DIST.match(t)) > 1:
                return False, None, False  # two dimensions in one block, the leader is the other one's
        if kind == "line" and want_az is not None and len(cands) > 1:
            # busy vertex: several record lines end at the identical arrowhead, and no length match
            # settled it above -- prefer the piece(s) whose own endpoint IS the tip (not one merely
            # passing near it), and among those let the printed bearing pick (loop6 leg B). Tried ahead
            # of the length check instead (bearing always first): regressed a different, previously-
            # correct label sharing the same busy vertex on R-10434.3 (S71 deg 08' 19" W, legitimately
            # length-picked) -- so this only ever narrows the fallback, never overrides a length match
            landing = [t for t in cands if min(np.hypot(*(t[1]["p0"] - tip)), np.hypot(*(t[1]["p1"] - tip))) < reach] or cands
            fit = [t for t in landing if az_diff(az_of(t[1]), want_az) < max(AZ_FILTER, math.degrees(math.atan2(0.3, t[1]["len_pt"] * scale)))]
            if fit:
                return True, min(fit, key=lambda t: t[0])[1], True
        # proximity: fallback only -- proven (arc kind) when the nearest candidate touches the tip
        # (<= ARC_TOUCH_PT) and no other candidate also touches (every other is > ARC_TOUCH_CLEAR_PT):
        # a real leader lands ON its piece; a tie of two or more touching pieces is a guess among them
        # (loop15b: candidate count alone wrongly queued R-10434.3's 29.14', whose only other candidate
        # sits 3.4 pt out -- not a tie -- while the genuinely wrong picks tie at <= 0.5 pt or land > 2 pt
        # out entirely)
        ordered = sorted(cands, key=lambda t: t[0])
        # loop15 close: a lone candidate in reach is proven whatever its gap (the leader has nothing else to name;
        # Presidio's keyed-real 59.06' lands 2.7 pt off its only candidate); several are proven only by a clear touch
        proven = kind != "arc" or len(ordered) == 1 or (ordered[0][0] <= ARC_TOUCH_PT and ordered[1][0] > ARC_TOUCH_CLEAR_PT)
        return True, ordered[0][1], proven

    def region(b):
        return [round(b["cx"] - b["w"] / 2 - 4), round(b["cy"] - b["h"] / 2 - 4), round(b["cx"] + b["w"] / 2 + 4), round(b["cy"] + b["h"] / 2 + 4)]

    def shape(seg):
        """The drawn line or arc a check measured, as points (pt), so the exception page can show it."""
        P = seg["pts"][:: max(1, len(seg["pts"]) // 20)] if "pts" in seg else [seg["p0"], seg["p1"]]
        return [[round(float(x), 1), round(float(y), 1)] for x, y in P]

    def paired_bearing(b):
        """A bearing from a block stacked directly beside b (same reading angle, aligned along the
        reading axis, close along the perpendicular) when b's own text carries none of its own -- the
        common drafting convention of a bearing on one line and its distance on the next, read as two
        separate blocks rather than one "|"-joined block (leg H2, for a bare (T) run total whose own
        block is just the distance)."""
        c, u, n = frame(b)
        best = None
        for o in blocks:
            if o is b or abs(((o["angle"] - b["angle"] + 90) % 180) - 90) > 2:
                continue
            d = np.array([o["cx"], o["cy"]]) - c
            along, perp = abs(d @ u), abs(d @ n)
            if along < 0.6 * max(b["w"], o["w"]) and perp < 2.0 * b["glyph_h"]:
                for t in o["text"].replace(" ", "").split("|"):
                    if BEAR.match(t) and not BEAR.match(t)[6] and (best is None or perp < best[0]):
                        best = (perp, azimuth(t))
        return best[1] if best else None

    for bi, b in enumerate(blocks):
        if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in FURNITURE):
            continue  # table cells and title block: the record, not labels on the drawing
        if NTS and any(math.hypot(b["cx"] - c["cx"], b["cy"] - c["cy"]) < c["r"] + 2 * c["gh"] for c in NTS):
            if any(TOKEN.search(t) or LEN.match(t) for t in b["text"].replace(" ", "").split("|")):
                exceptions.append({"kind": "nts", "issue": "not to scale: inside detail inset", "region": region(b)})
            continue  # a not-to-scale detail inset: drawn deliberately wrong, never checkable
        lines = b["text"].replace(" ", "").split("|")
        curve_data = any(ANG_TOK.search(t) or RAD_TOK.search(t) or LEN_TOK.search(t) or re.match(r"^[RL][=\-:]", t) for t in lines)
        if len(lines) == 1 and LEN.match(lines[0]):
            # a standalone "L=573.93'" annotation (one block per annotation, since leg 1): TOKEN strips
            # the "L=" prefix off its digit token, so this would otherwise fall into the DIST branch
            # below and be dropped there (curve_data is always true for it) -- check it against the
            # drawn arc directly: leader tip first, else the arc whose length matches within DIST_TOL
            # among arcs within 5 glyph heights (never the nearest arc by distance alone).
            m = LEN.match(lines[0])
            want = float(m[1])
            is_total = bool(m[2])
            # (T) used to be skipped here ("a run total over several tags, not a single arc"), but a
            # standalone (T) is just this one annotation's own drawn run between its vertex circles --
            # STATE.md measured that run against the printed (T) to 0.02 ft -- so it checks the same way
            led, arc, arc_proven = at_tip(bi, "arc", want)
            near = far = None
            if arc is None and not led:
                near = [x for x in arcs if poly_dist(np.array([b["cx"], b["cy"]]), x["pts"]) < 5.0 * b["glyph_h"]]
                close = [x for x in near if abs(x["len_pt"] * scale - want) <= DIST_TOL + 0.0005 * want]
                if not close:  # some curve-data callouts (the tunnel-easement corridor, a busy curve
                    # elsewhere) are drafted well clear of their curve for room, past 5 glyph heights;
                    # widen the search but keep the same tight length match, so a coincidence this far
                    # out would need to land within DIST_TOL by pure chance
                    far = [x for x in arcs if poly_dist(np.array([b["cx"], b["cy"]]), x["pts"]) < 160.0]
                    close = [x for x in far if abs(x["len_pt"] * scale - want) <= DIST_TOL + 0.0005 * want]
                # same tie-break as tables.py's whole-vs-piece pick (leg E): a length-match tie used to
                # fall to close's own order (arcs' get_drawings()/split_at build order, not the geometry).
                # Tie-break on point count (prefer the specific piece over the whole path) then the
                # candidate's own start coordinate, both properties of the candidate, not of list position
                found = min(close, key=lambda x: (abs(x["len_pt"] * scale - want), len(x["pts"]), float(x["pts"][0][0]), float(x["pts"][0][1]))) if close else None
                if found is not None:
                    arc, arc_proven = found, True  # length-verified: proven
            if arc is not None:
                drawn = arc["len_pt"] * scale
                ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                if ok:  # own length matches a drawn piece directly: done, no need to look for a run-mate
                    rows.append(["arc length", lines[0], f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass"])
                    labels.append({"kind": "arc", "printed": lines[0], "ft": want, "line": shape(arc), "ok": True, "how": "leader" if led else "beside", "region": region(b)})
                    len_checked.add(id(b))  # already resolved geometrically: the curve-data fillet check
                    # further down (leg5 legB2) skips this block rather than re-measuring the same piece
                    continue
            # own length matches no single drawn piece: a compound curve/fillet whose record boundary
            # isn't drawn is cut by split_at at every circle/tick/crossing it DOES find (leg6A: including
            # stationing ties along MAIN LINE curves, which read as ordinary radial ticks) into slivers no
            # single one of which is the printed length. The leader-tip run-sum below (len_pending/by_run)
            # only ever fires between labels that already found a piece via at_tip's own fallback; a label
            # whose leader is a plain curved bracket with no arrowhead/circle (tag_leaders never sees it,
            # so led is False here) or whose tip lands in the gap between two slivers gets no seed at all
            # under the old code and was a flat, silent MISS 25 times on the 3 south sheets (loop5 legB).
            # Fix: seed from the leader tip if there is one, else the nearest piece to the label -- same
            # "leader tip or nearest piece" seed the fillet-radius check below already uses for a joined
            # R=/L= block, generalised to a lone L=/(T) with no printed R of its own. Every piece sharing
            # the seed's "parent" (build_pool's own id, one per original curve object before split_at cut
            # it) is a genuine sibling slice of that same physical curve -- checked, not assumed (a fresh
            # circle re-fit per piece, attempt 1, was too noisy over a long many-point sliver to recover
            # its own siblings). But the WHOLE parent isn't always one printed curve: `lines_on_sheet`'s
            # generous max_turn_deg (20 deg, for curves) chains tangent road edges through a busy
            # interchange into one long parent spanning several named curves end to end (measured on
            # r10434_1: an 869 ft label's parent also carried an unrelated 800 ft piece from the next road
            # over) -- summing every same-parent sibling regardless of position matched nothing on either
            # north-facing south sheet (attempt 2, zero fires off the seed's own curve). Each piece keeps
            # its "seq" (order along the parent, the same order split_at emitted it in); only CONTIGUOUS
            # windows of seq around the seed are tried, exactly as span_for already does for a straight
            # line's own record-segment run -- and only accepted when exactly one window's sum matches
            # (a tie is not a match, same rule span_for and run_sum both already use). Only ever asserted
            # on a match -- never a single wrong piece -- so this can't repeat legB's reverted length-blind
            # fallback (which asserted the nearest piece outright and cost wrong_line +3/+3/+6 for zero
            # pass gain on the three south sheets).
            group_arc = None
            if arc is None:
                seed_at = tips[bi][0] if led and bi in tips else np.array([b["cx"], b["cy"]])
                # same 160pt cap the near/far single-piece search above already uses -- measured (leg6A)
                # that widening this past 160pt is where the safety net stops being safe: at 500pt one
                # south-sheet label's "unique" matching window belonged to a curve 179pt away, a visibly
                # different physical curve, with the true drawn piece for that label simply missing from
                # the pool (crop-verified false positive, reverted). Below 160pt every fire crop-checked
                # against the sheet: the blue run always sits right beside the red label.
                wide = sorted((x for x in arcs if poly_dist(seed_at, x["pts"]) < 160.0 and "seq" in x),
                              key=lambda x: poly_dist(seed_at, x["pts"]))
                # the nearest piece is usually the seed, but not always the one WHOSE parent contains the
                # printed run (a nearer, unrelated stub can sit closer to the label than the target curve
                # itself does): try the 20 nearest in order (all of them, in practice -- 160pt rarely
                # holds more) and take the first whose own parent yields a unique matching window
                # (parent_window, shared with tables.py's table-tag curves -- leg8A)
                for seed in wide[:20]:
                    window = parent_window(arcs, seed, want, scale)
                    if window is not None:
                        group_arc = window
                        break
            if group_arc is not None:
                drawn = sum(x["len_pt"] for x in group_arc) * scale
                biggest = max(group_arc, key=lambda x: x["len_pt"])
                sum_str = f"{drawn:.2f} = " + " + ".join(f"{x['len_pt'] * scale:.2f}" for x in group_arc)
                rows.append(["arc length", lines[0], sum_str, f"{drawn - want:+.2f}",
                             f"pass as a run of {len(group_arc)}: contiguous slivers of one curve, no leader/length seed"])
                labels.append({"kind": "arc", "printed": lines[0], "ft": want, "line": shape(biggest), "ok": True,
                               "how": "leader" if led else "beside", "region": region(b)})
                len_checked.add(id(b))
                continue
            # a compound curve whose record boundary isn't drawn can also be checked as the run between
            # drawn marks against the SUM of the record arcs sharing it -- the rule tables.py already
            # applies to table tags. A leader tip already pins the drawn run above (at_tip finds the
            # nearest candidate at the tip regardless of length); queue it for grouping with every other
            # unresolved L=/(T) label that lands on the identical drawn object, resolved once every block
            # is scanned.
            if arc is None:
                exceptions.append({"kind": "arc length", "text": lines[0], "issue": "leader points at no arc" if led else "no arc within 5 glyph heights matches the printed length", "region": region(b)})
            elif not arc_proven:
                # loop15: the leader touches more than one arc and nothing (length, a contiguous window)
                # settled which one -- a fail measured against this pick would be a claim about the wrong
                # curve, not evidence the record disagrees
                exceptions.append({"kind": "arc length", "text": lines[0], "issue": f"association unproven: measured {arc['len_pt'] * scale:.2f} vs printed {want:.2f} ft", "region": region(b), "line": shape(arc)})
                len_checked.add(id(b))
            else:
                len_pending.append({"text": lines[0], "want": want, "total": is_total, "arc": arc, "led": led, "region": region(b)})
                len_checked.add(id(b))  # a candidate WAS found here (just the wrong length): the fillet
                # check's own radius-based search would only re-measure the identical piece and re-fail it
            continue
        # a bearing and its distance often come back as one OCR line: take the tokens inside each line
        parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines

        def chord_curve(bi, led):
            """The curved piece a label beside a curve cites: at the leader tip (same search at_tip's
            own "arc" kind already does for a leader), else nearest to the label itself."""
            if led:
                return at_tip(bi, "arc")[1]
            return nearest_arc(b, arcs, 1.5 * b["glyph_h"])

        def chord_bearing(bi, led, part, mate):
            """No straight line found, or the one found doesn't match: if the label's nearest linework is
            actually a curved piece, it's a chord citation (loop6 leg C rule 2), not an unmatched or
            wrongly-matched label. Only ever tried once the straight-line search has already failed, so a
            label that already resolves correctly via a chain is never touched by this -- the safest gate,
            measured: an unconditional "nearest pool wins" race grabbed short irrelevant curve fragments
            (tick marks, dash noise) ahead of a real nearby line and turned passes into fails."""
            curve = chord_curve(bi, led)
            if curve is None:
                return None
            want_az = azimuth(part)
            d0 = curve["pts"][-1] - curve["pts"][0]
            n0 = float(np.hypot(*d0))
            if n0 < 1e-6 or az_diff(dir_az(d0 / n0), want_az) > 45.0:
                return None  # nearest_arc only checks the curve's tangent against the label's reading
                # direction, not the printed bearing; this sanity check rejects the rare unrelated grab
            piece = chord_span(curve, mate, scale, arcs)
            p0, p1 = piece.get("_p0", piece["pts"][0]), piece.get("_p1", piece["pts"][-1])
            chord_pt = float(np.hypot(*(p1 - p0)))
            if chord_pt < 1e-6:
                return None
            az = dir_az((p1 - p0) / chord_pt)
            diff = min(abs((az - want_az + 180) % 360 - 180), abs((az + 180 - want_az + 180) % 360 - 180))
            tol = bearing_tol_deg(chord_pt)
            cline = [[round(float(x), 1), round(float(y), 1)] for x, y in (p0, p1)]
            return az, diff, tol, cline

        def chord_distance(bi, led, want, baz):
            """Same fallback as chord_bearing, for the distance half of a bearing+distance block beside
            a curve: the chord between the piece's ends (or its run, matched on this same printed
            distance), only once the straight-line search has already failed to find its match."""
            curve = chord_curve(bi, led)
            if curve is None:
                return None
            d0 = curve["pts"][-1] - curve["pts"][0]
            n0 = float(np.hypot(*d0))
            if n0 < 1e-6 or (baz is not None and az_diff(dir_az(d0 / n0), baz) > 45.0):
                return None
            piece = chord_span(curve, want, scale, arcs)
            p0, p1 = piece.get("_p0", piece["pts"][0]), piece.get("_p1", piece["pts"][-1])
            drawn = float(np.hypot(*(p1 - p0))) * scale
            cline = [[round(float(x), 1), round(float(y), 1)] for x, y in (p0, p1)]
            return drawn, cline

        for part in parts:
            if BEAR.match(part) and BEAR.match(part)[6]:
                rows.append(["bearing (R)", part, "", "", "radial: not checked"])
                # loop16 leg F: still real record data (there is no drawn LINE to check a radial
                # against -- it marks a curve's own end direction, not a course) -- checks.py used to
                # drop it here outright, which is why traverse.py's own radial source (leg E's plan,
                # never wired up) had no data to read. Written to radials.json instead: the curve
                # nearest this label (leader tip if it has one, else chord_curve's own nearest_arc
                # search, reused) and whichever of its two drawn ends sits closer to the label is the
                # end this radial names. This is only ever a geometric PAIRING, not a claim about
                # direction -- traverse.complete_curve_chords() still separately confirms the printed
                # radial's own +/-90 deg tangent candidate agrees with that end's drawn tangent
                # (arc_end_tangent_az, the same TANGENT_TOL_DEG discipline the tangent-line source
                # already uses) before ever using it, so a wrong pairing here can misdirect that later
                # check but never bypass it into a guess.
                led_r, arc_r, _ = at_tip(bi, "arc")
                curve = arc_r if led_r and arc_r is not None else nearest_arc_end(b, arcs)
                if curve is not None and len(curve["pts"]) >= 2:
                    p0, p1 = curve["pts"][0], curve["pts"][-1]
                    lp = np.array([b["cx"], b["cy"]])
                    end_pt = p0 if np.hypot(*(p0 - lp)) <= np.hypot(*(p1 - lp)) else p1
                    radials.append({"printed": part, "az": azimuth(part), "region": region(b),
                                     "point": [round(float(end_pt[0]), 1), round(float(end_pt[1]), 1)]})
                continue
            if BEAR.match(part):
                mate = next((float(dist_num(DIST.match(t))[0]) for t in parts if DIST.match(t)), None)
                led, ln, _ = at_tip(bi, "line", mate, want_az=azimuth(part))
                if not led:
                    ln = nearest_line(b, chains, 5.0 * b["glyph_h"], mate, scale, want_az=azimuth(part), az_of=az_of)
                if ln is not None:
                    ln = span_for(ln, mate, scale, chains)
                if ln is not None and ln["len_pt"] < MIN_BEARING_LEN_PT:
                    # too short to carry a bearing at all (leg C follow-up): queued, not passed or
                    # failed, and not handed to the chord fallback either -- a genuinely too-short piece
                    # stays too-short whatever curve happens to sit nearby
                    exceptions.append({"kind": "bearing", "text": part, "issue": f"piece too short to carry a bearing ({ln['len_pt']:.1f} pt)", "region": region(b)}); continue
                ok = None
                if ln is not None:
                    dx, dy = ln["dir"][0], -ln["dir"][1]                      # sheet direction, y up
                    gx, gy = a * dx - bb * dy, bb * dx + a * dy                # into the grid frame
                    az = math.degrees(math.atan2(gx, gy)) % 360               # from grid north, clockwise
                    want = azimuth(part)
                    diff = min(abs((az - want + 180) % 360 - 180), abs((az + 180 - want + 180) % 360 - 180))
                    tol = bearing_tol_deg(ln["len_pt"])
                    ok = diff <= tol
                if not ok:
                    # a chord result is only ever taken when it PASSES -- never used to relabel one FAIL
                    # (a wrongly-matched straight line, or no line at all) as a different FAIL (kept the
                    # wrong-curve false-positive rate this rule measured out of wrong_line entirely: a
                    # real chord citation agrees with the printed value; an accidental grab of an
                    # unrelated curve essentially never does, so "only accept a pass" is also how the rule
                    # tells a genuine chord label apart from a label that just has no match)
                    chord = chord_bearing(bi, led, part, mate)
                    if chord is not None:
                        caz, cdiff, ctol, cline = chord
                        if cdiff <= ctol:
                            rows.append(["chord bearing", part, fmt_bearing(caz if abs((caz - azimuth(part) + 180) % 360 - 180) < 90 else caz + 180), f"{cdiff * 60:.1f}'", "pass"])
                            labels.append({"kind": "chord bearing", "printed": part, "az": azimuth(part), "line": cline, "ok": True, "how": "beside", "region": region(b)})
                            continue
                if ln is None:
                    exceptions.append({"kind": "bearing", "text": part, "issue": "leader points at no line" if led else "no line found beside label", "region": region(b)}); continue
                if not ok and ln.get("relaxed_angle"):
                    # loop15 leg2: this candidate is reachable only because the label's own box rotation
                    # (an OCR/glyph guess, not the record) was set aside in favour of the printed bearing --
                    # a new association path may only ever add a pass, never a fail, so a disagreement here
                    # is queued as unproven rather than asserted as a claim about the record
                    exceptions.append({"kind": "bearing", "text": part, "issue": f"association unproven: measured {fmt_bearing(az)} vs printed {part} ({diff * 60:.1f}' off)", "region": region(b), "line": shape(ln)}); continue
                if not ok and wrong_line_likely("bearing", diff * 60):
                    exceptions.append({"kind": "bearing", "text": part, "issue": f"wrong line likely: measured {fmt_bearing(az)} vs printed {part} ({diff * 60:.1f}' off)", "region": region(b), "line": shape(ln)}); continue
                rows.append(["bearing", part, fmt_bearing(az if abs((az - want + 180) % 360 - 180) < 90 else az + 180), f"{diff * 60:.1f}'", "pass" if ok else "FAIL"])
                labels.append({"kind": "bearing", "printed": part, "az": want, "line": shape(ln), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                if not ok:
                    # tol_arcmin travels with the exception so wrong-line classification downstream
                    # (bench.py) uses the same scaled tolerance, not a flat cutoff, for this piece
                    exceptions.append({"kind": "bearing", "text": part, "drawn": fmt_bearing(az), "off_arcmin": round(diff * 60, 1), "tol_arcmin": round(tol * 60, 1), "region": region(b), "line": shape(ln)})
            elif DIST.match(part):
                m = DIST.match(part)
                num_str, is_total = dist_num(m)
                if curve_data or STATION.search(b["text"]) or AREA_CTX.search(b["text"]) or NOTES_CTX.search(b["text"]):
                    continue  # curve data (R=, Δ, L=), a station number, a parcel-area figure, or a
                    # coordinate-basis note: not a line length. A bare "NNN.NN'(T)" run total (no "L="
                    # prefix -- that one is caught above, in the standalone-L= branch) used to be
                    # skipped outright here too ("a run total over several tags, not a single line"),
                    # dropping 20 genuine, measurable tokens (spike/out_coverage/attribution.md,
                    # bucket a-runtotal -- every one confirmed a real drawn-line run beside real
                    # linework). It is checked below exactly like an ordinary distance: the same
                    # leader-tip/nearest-line search finds a seed piece on its run (want won't match
                    # the seed's own single-piece length, so at_tip/nearest_line's own proximity
                    # fallback picks it), then span_for's existing contiguous-sum search -- the same
                    # machinery a standalone "L=...(T)" label already uses -- accepts it only when
                    # exactly one contiguous span of that run sums to the printed total (leg H)
                want = float(num_str)
                baz = next((azimuth(t) for t in parts if BEAR.match(t) and not BEAR.match(t)[6]), None)  # the bearing printed with it
                if baz is None and is_total:
                    baz = paired_bearing(b)  # leg H2: the bearing can sit in its OWN adjacent block
                led, ln, _ = at_tip(bi, "line", want, want_az=baz)
                if not led:
                    ln = nearest_line(b, chains, 5.0 * b["glyph_h"], want, scale, want_az=baz, az_of=az_of)
                if ln is not None:
                    ln = span_for(ln, want, scale, chains)
                    if is_total and ln is not None and baz is not None and az_diff(az_of(ln), baz) > bearing_tol_deg(ln["len_pt"] * scale):
                        # leg H2: a bare (T) run total whose block carries a bearing must be measured on
                        # a run whose OWN direction -- after span_for's own possibly multi-piece join --
                        # actually passes that bearing, not just the seed piece's coarser per-piece
                        # pre-filter a joined span can drift away from (a window on a DIFFERENT, similar-
                        # bearing line coincidentally summed to the same printed total: r10434_3's
                        # "195.48'(T)" measured on the ticked N86 deg 41'46" line sharing its left circle
                        # with the true "247.31'(T)" run, 0.4 deg off -- close enough to pass the coarse
                        # filter, wrong enough to be a different physical line). Reject; falls through to
                        # the chord/arc fallbacks, then a plain "no line" exception, same as any other
                        # unmatched total -- never a guessed pass.
                        ln = None
                if (ln is None or abs(ln["len_pt"] * scale - want) > 1.0) and baz is not None:
                    # a bearing+distance block beside a curve: the distance is the same chord the paired
                    # bearing above measures, not an arc length (loop6 leg C rule 2) -- tried whenever the
                    # straight line came up empty or doesn't match (same trigger the arc-length fallback
                    # below uses), only kept when it PASSES (same never-trade-a-fail-for-a-fail rule
                    # chord_bearing above uses)
                    chord = chord_distance(bi, led, want, baz)
                    if chord is not None:
                        drawn, cline = chord
                        if abs(drawn - want) <= DIST_TOL + 0.0005 * want:
                            rows.append(["chord distance", part, f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass"])
                            labels.append({"kind": "chord distance", "printed": part, "ft": want, "line": cline, "ok": True, "how": "beside", "region": region(b)})
                            continue
                if ln is None or abs(ln["len_pt"] * scale - want) > 1.0:
                    # a bare distance only becomes an arc-length candidate when the label itself sits
                    # ON a curve (leg5 legB2, orchestrator): a leader tip landing on a curved piece, or
                    # (no leader) the label centre within 1.5 glyph heights of one with its reading
                    # direction within 15 deg of the piece's own tangent there -- not the old 5-glyph-
                    # height, length-blind search, which was turning ordinary line distances beside a
                    # curve-dense area (a bearing+distance label whose line search merely failed) into
                    # fake arc-length fails against whatever curve happened to be nearest
                    # tol_deg stays nearest_arc's own default (8): measured, a 15 deg allowance (as
                    # first tried) let a genuinely unrelated label 30+ ft from any real match through --
                    # every true arc match seen while tuning this sits under 6 deg, so 8 loses nothing
                    # loop15: a leader's own touch (arc_proven) is real proof; "beside" here has none --
                    # nearest_arc picks by position and tangent alone, never by length, so a FAIL built on
                    # it is a claim about whichever curve happened to be nearest, not a measured one
                    arc, arc_proven = at_tip(bi, "arc", want)[1:3] if led else (nearest_arc(b, arcs, 1.5 * b["glyph_h"]), False)
                    if arc is not None and (ln is None or abs(arc["len_pt"] * scale - want) < abs(ln["len_pt"] * scale - want)):
                        drawn = arc["len_pt"] * scale
                        ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                        if not ok and is_total:  # a bare (T) run total was only ever meant to accept a
                            # pass on this fallback too, whichever kind (line or arc) it lands on
                            exceptions.append({"kind": "arc length", "text": part, "issue": f"association unproven: measured {drawn:.2f} vs printed {want:.2f} ft (T)", "region": region(b), "line": shape(arc)}); continue
                        if not ok and not arc_proven:
                            exceptions.append({"kind": "arc length", "text": part, "issue": f"association unproven: measured {drawn:.2f} vs printed {want:.2f} ft", "region": region(b), "line": shape(arc)}); continue
                        if not ok and wrong_line_likely("arc length", drawn - want, want):
                            exceptions.append({"kind": "arc length", "text": part, "issue": f"wrong line likely: measured {drawn:.2f} vs printed {want:.2f} ft", "region": region(b), "line": shape(arc)}); continue
                        rows.append(["arc length", part, f"{drawn:.2f} (R={arc['radius_pt'] * scale:.1f})", f"{drawn - want:+.2f}", "pass" if ok else "FAIL"])
                        labels.append({"kind": "arc", "printed": part, "ft": want, "line": shape(arc), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                        if not ok:
                            exceptions.append({"kind": "arc length", "text": part, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - want, 2), "region": region(b), "line": shape(arc)})
                        continue
                if ln is None:
                    exceptions.append({"kind": "distance", "text": part, "issue": "leader points at no line" if led else "no line found beside label", "region": region(b)}); continue
                W = page.rect.width
                if min(ln["p0"][0], ln["p1"][0]) < 262 or max(ln["p0"][0], ln["p1"][0]) > W - 50:
                    exceptions.append({"kind": "distance", "text": part, "issue": "line runs to the sheet edge (matchline); not checkable on this sheet", "region": region(b)}); continue
                drawn = ln["len_pt"] * scale
                ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                if not ok:
                    # a bare "NNN.NN'(T)" run total (leg H2) is only ever meant to accept a pass -- any
                    # fail on it is unproven association, not evidence of a real disagreement, whatever
                    # its size; every other distance keeps the ordinary gold-calibrated cut (loop 14)
                    if is_total:
                        exceptions.append({"kind": "distance", "text": part, "issue": f"association unproven: measured {drawn:.2f} vs printed {want:.2f} ft (T)", "region": region(b), "line": shape(ln)}); continue
                    if ln.get("relaxed_angle"):
                        # loop15 leg2: same rule as the bearing branch -- this candidate is reachable only
                        # because the label's own box rotation was set aside for the printed bearing beside
                        # it (baz); a new association path may only ever add a pass, never a fail
                        exceptions.append({"kind": "distance", "text": part, "issue": f"association unproven: measured {drawn:.2f} vs printed {want:.2f} ft", "region": region(b), "line": shape(ln)}); continue
                    if wrong_line_likely("distance", drawn - want, want):
                        exceptions.append({"kind": "distance", "text": part, "issue": f"wrong line likely: measured {drawn:.2f} vs printed {want:.2f} ft", "region": region(b), "line": shape(ln)}); continue
                result = "pass" if ok else "FAIL"
                if is_total and ok and ln.get("joined", 1) > 1:
                    result = f"pass as a run of {ln['joined']}: the boundary between these segments is not drawn"
                rows.append(["distance", part, f"{drawn:.2f}", f"{drawn - want:+.2f}", result])
                labels.append({"kind": "distance", "printed": part, "ft": want, "line": shape(ln), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                if not ok:
                    exceptions.append({"kind": "distance", "text": part, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - want, 2), "region": region(b), "line": shape(ln)})

    # resolve the deferred standalone L=/(T) labels: group by the drawn arc OBJECT each one landed on
    # (id() equality -- the same object means the same physical drawn run, tables.py's own by_run key)
    by_run = {}
    for p in len_pending:
        by_run.setdefault(id(p["arc"]), []).append(p)
    for group in by_run.values():
        arc = group[0]["arc"]
        drawn = arc["len_pt"] * scale
        for p in group:  # a (T) total names this whole run itself, not a share of it: check it directly
            if p["total"]:
                ok = abs(drawn - p["want"]) <= DIST_TOL + 0.0005 * p["want"]
                if not ok and wrong_line_likely("arc length", drawn - p["want"], p["want"]):
                    exceptions.append({"kind": "arc length", "text": p["text"], "issue": f"wrong line likely: measured {drawn:.2f} vs printed {p['want']:.2f} ft", "region": p["region"], "line": shape(arc)}); continue
                rows.append(["arc length", p["text"], f"{drawn:.2f}", f"{drawn - p['want']:+.2f}", "pass" if ok else "FAIL"])
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": ok, "how": "leader" if p["led"] else "beside", "region": p["region"]})
                if not ok:
                    exceptions.append({"kind": "arc length", "text": p["text"], "drawn_ft": round(drawn, 2), "off_ft": round(drawn - p["want"], 2), "region": p["region"], "line": shape(arc)})
        piece = [p for p in group if not p["total"]]
        Ls = [p["want"] for p in piece]
        total, by_sum = run_sum(drawn, Ls)
        if len(piece) <= 1:
            # a standalone L= with no neighbour sharing its run stays as it is: a plain FAIL, same as
            # before this leg (nothing to sum it with)
            for p in piece:
                if wrong_line_likely("arc length", drawn - p["want"], p["want"]):
                    exceptions.append({"kind": "arc length", "text": p["text"], "issue": f"wrong line likely: measured {drawn:.2f} vs printed {p['want']:.2f} ft", "region": p["region"], "line": shape(arc)}); continue
                rows.append(["arc length", p["text"], f"{drawn:.2f}", f"{drawn - p['want']:+.2f}", "FAIL"])
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": False, "how": "leader" if p["led"] else "beside", "region": p["region"]})
                exceptions.append({"kind": "arc length", "text": p["text"], "drawn_ft": round(drawn, 2), "off_ft": round(drawn - p["want"], 2), "region": p["region"], "line": shape(arc)})
        elif by_sum:
            sum_str = f"{drawn:.2f} = " + " + ".join(f"{x:.2f}" for x in Ls)
            for p in piece:
                rows.append(["arc length", p["text"], sum_str, f"{drawn - total:+.2f}",
                             f"pass as a run of {len(piece)}: the boundary between these arcs is not drawn"])
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": True, "how": "leader" if p["led"] else "beside", "region": p["region"]})
        elif wrong_line_likely("arc length", drawn - total, total):  # the run doesn't match the sum either
            exceptions.append({"kind": "arc length", "text": " + ".join(p["text"] for p in piece), "issue": f"wrong line likely: measured {drawn:.2f} vs printed total {total:.2f} ft", "region": piece[0]["region"], "line": shape(arc)})
        else:  # fail once against the sum, not once per label
            texts = " + ".join(p["text"] for p in piece)
            rows.append(["arc length", texts, f"{drawn:.2f}", f"{drawn - total:+.2f}", "FAIL"])
            for p in piece:
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": False, "how": "leader" if p["led"] else "beside", "region": p["region"]})
            exceptions.append({"kind": "arc length", "text": texts, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - total, 2), "region": piece[0]["region"], "line": shape(arc)})

    # curves: R, delta and L printed together (same block or stacked, or joined into one OCR line
    # with no "|" split -- RAD_TOK/ANG_TOK/LEN_TOK find those the same way TOKEN finds BEAR/DIST)
    curve_blocks = [b for b in blocks if any(RAD_TOK.search(t) or ANG_TOK.search(t) or LEN_TOK.search(t) for t in b["text"].replace(" ", "").split("|"))]
    bidx = {id(bb): i for i, bb in enumerate(blocks)}  # curve_blocks entries are blocks' own dicts; a
    # leader-tip lookup (tips, keyed by index into blocks) needs the index back

    def n_curve_toks(text):
        return sum(1 for pat in (RAD_TOK, ANG_TOK, LEN_TOK) for _ in pat.finditer(text))
    seen = set()
    # loop17 leg H: every "arc" label already placed by the standalone L=/(T) or bare-distance-as-arc
    # branches above, keyed by its own region -- so the joined-triple pass below can find and finish an
    # ALREADY-RESOLVED label's row instead of discarding a genuine, already-checked (and possibly
    # already-passing, see rows.append above) radius purely because that label happened to resolve first.
    # Census (spike/legG17_census.py): 25 of 50 "no R" rows had their own exact (R, delta, L) triple
    # sitting right there in checks.csv, already computed and PASSING -- len_checked's own "continue"
    # threw the radius away every time instead of carrying it onto the label that already exists.
    labels_by_region = {}
    for lab in labels:
        if lab["kind"] == "arc" and lab.get("region"):
            labels_by_region.setdefault(tuple(lab["region"]), []).append(lab)
    for b in curve_blocks:
        parts = b["text"].replace(" ", "").split("|")
        joined = [b]  # every block whose text ended up in `parts`, so the L= value's own drawn fillet
        # can be searched for from wherever the "L=" text itself actually sits, not an arbitrary member
        # of the joined group (leg5 legB2 cause 2: an R=/Δ= block can sit closer to a different,
        # same-radius record arc than the one its own paired L= value describes)
        c, u, n = frame(b)
        b_joined = n_curve_toks(b["text"]) > 1
        for o in curve_blocks:
            if o is b:
                continue
            op = np.array([o["cx"], o["cy"]]) - c
            if b_joined or n_curve_toks(o["text"]) > 1:
                # one side is a joined block ("A=32°20'00" L=660.20'"): compare near edges, not centres --
                # its own half-width already covers ground toward its neighbour, so a centre-to-centre
                # measure over-counts the true gap; same 3.2-glyph_h slop the line-below check uses
                along_ok = abs(op @ u) - 0.5 * (b["w"] + o["w"]) < 3.2 * b["glyph_h"]
            else:
                # neither block is joined (two ordinary single-value R=/A=/L= labels): keep the original,
                # tighter width-based reach -- a curve-dense area (a curb of many similar-radius fillets)
                # can put an unrelated curve's R= within the wider edge-gap reach of this one's Δ/L
                along_ok = abs(op @ u) < 0.7 * max(b["w"], o["w"])
            if along_ok and 0 < op @ n < 3.2 * b["glyph_h"]:
                parts += o["text"].replace(" ", "").split("|")
                joined.append(o)
        R = next((float(m[1].replace(",", "")) for t in parts for m in [RAD_TOK.search(t)] if m), None)
        D = next((dms(*m.groups()[:3]) for t in parts for m in [ANG_TOK.search(t)] if m), None)
        L = next((float(m[1]) for t in parts for m in [LEN_TOK.search(t)] if m), None)
        if R and D and L and (R, D, L) not in seen:  # a joined block and its paired neighbour(s) can
            seen.add((R, D, L))                       # each independently gather the same full triple
            calc = R * math.radians(D)
            ok = abs(calc - L) <= 0.02 + 0.0005 * L
            rows.append(["curve L=R*delta", f"R={R} Δ={D:.4f}° L={L}", f"{calc:.2f}", f"{calc - L:+.2f}", "pass" if ok else "FAIL"])
            if not ok:
                exceptions.append({"kind": "curve", "text": b["text"], "calc_L": round(calc, 2), "printed_L": L, "region": region(b)})
            # drawn-arc second opinion (leg5 legB2, cause 2), never a replacement for the R*delta check
            # above: R=/L= inside a curve-data block often describes a short fillet too small for
            # split_at to find a boundary mark on (R=8.72' L=16.73', R=15.00' L=7.09') -- find it by its
            # own fitted radius (a three-point circle through its ends and midpoint, same method
            # arcs_on_sheet already uses), not by length-blind nearest-piece proximity: a curve-dense
            # corner can put several similar-length fillets within reach of one label
            len_block = next((bb for bb in joined if LEN_TOK.search(bb["text"].replace(" ", ""))), b)
            if id(len_block) in len_checked:
                # loop17 leg H: this L= value already got its own full geometric check above (it's also
                # its own standalone "L=...'" block) -- never re-measure it a second time (would double-
                # count one label as two passes, or two possibly-conflicting fails), but DO carry this
                # already-checked R/delta onto the label that check already placed, keyed by the same
                # block's own region -- never guessed, the identical triple this pass just validated above.
                attach_shared_curve_radius(labels_by_region, tuple(region(len_block)), R, D)
                continue

            tip = tips.get(bidx.get(id(len_block)))
            reach = max(4.0, 0.6 * tip[2]) if tip else 5.0 * len_block["glyph_h"]
            pt = tip[0] if tip else np.array([len_block["cx"], len_block["cy"]])
            fits = []
            for x in sorted((x for x in arcs if poly_dist(pt, x["pts"]) < reach), key=lambda x: poly_dist(pt, x["pts"])):
                if x["len_pt"] * scale > L + DIST_TOL + 0.0005 * L:
                    continue  # a piece longer than the fillet's own printed total can't be the fillet, or
                    # a fragment of it (this is a fillet's own radius search, not a compound-curve run: a
                    # large R/W curve built from several same-radius facets can fool the 3-point
                    # circumradius test at any point along it, far past this small label's own reach)
                r_ft = circumradius3(x["pts"]) * scale
                ctr = circle_center3(x["pts"])
                if math.isfinite(r_ft) and ctr is not None and abs(r_ft - R) <= 0.02 * R:
                    fits.append((x, ctr))
            if fits:
                # a radius-matching whole path and its own sub-piece(s) sit at the same centre too (a
                # piece of a circle has the whole circle's radius): when one candidate's own length
                # already matches the printed L, that is the fillet, on its own -- no summing. Only a
                # genuinely fragmented short fillet (several pieces, none matching L alone) falls to the
                # same-centre group-and-sum
                exact = next((x for x, _ in fits if abs(x["len_pt"] * scale - L) <= DIST_TOL + 0.0005 * L), None)
                if exact is not None:
                    pieces = [exact]
                else:
                    # adjacent bezier sub-arcs of the same fillet share a fitted centre: group them onto
                    # the nearest match (fits[0], distance-sorted above) and sum
                    group = [fits[0]]
                    for x, ctr in fits[1:]:
                        if any(np.hypot(*(ctr - g[1])) < 0.5 / scale for g in group):
                            group.append((x, ctr))
                    pieces = [x for x, _ in group]
                lens_ft = [x["len_pt"] * scale for x in pieces]
                drawn = sum(lens_ft)
                ok2 = abs(drawn - L) <= DIST_TOL + 0.0005 * L
                printed = f"R={R}' L={L}'"
                if not ok2 and wrong_line_likely("arc length", drawn - L, L):
                    exceptions.append({"kind": "arc length", "text": printed, "issue": f"wrong line likely: measured {drawn:.2f} vs printed {L:.2f} ft", "region": region(len_block), "line": shape(pieces[0])})
                else:
                    sumtxt = f"{drawn:.2f}" if len(pieces) == 1 else f"{drawn:.2f} = " + " + ".join(f"{v:.2f}" for v in lens_ft)
                    rows.append(["arc length", printed, sumtxt, f"{drawn - L:+.2f}", "pass" if ok2 else "FAIL"])
                    # loop16 leg F: R and delta were computed and checked (L=R*delta above) but never
                    # left this function -- only "ft" (L) reached labels.json, so traverse.py's build_edges
                    # (which reads an "arc"-kind label's own "R"/"delta" the same way it already reads a
                    # tag_labels table curve's) had nothing to place a chord on. Carried through now.
                    labels.append({"kind": "arc", "printed": printed, "ft": L, "R": R, "delta": D, "line": shape(pieces[0]), "ok": ok2, "how": "leader" if tip else "beside", "region": region(len_block)})
                    if not ok2:
                        exceptions.append({"kind": "arc length", "text": printed, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - L, 2), "region": region(len_block), "line": shape(pieces[0])})

    (OUT / "labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    (OUT / "radials.json").write_text(json.dumps(radials, ensure_ascii=False), encoding="utf-8")
    with open(OUT / "checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["check", "printed", "drawn", "difference", "result"]); w.writerows(rows)
    (OUT / "exceptions.json").write_text(json.dumps(exceptions, indent=1, ensure_ascii=False), encoding="utf-8")
    kinds = {}
    for r in rows:
        k = kinds.setdefault(r[0], [0, 0]); k[0] += 1; k[1] += r[4] == "pass"
    print(f"lines on sheet {len(chains)} | scale {scale:.5f} ft/pt, grid north {rot:+.3f} deg from sheet up")
    for k, (n, ok) in kinds.items():
        print(f"  {k:16} checked {n:3}  pass {ok:3}  fail {n - ok:3}" if k != "bearing (R)" else f"  {k:16} {n:3} radial bearings, not checked against a line")
    print(f"  exceptions (fails + unmatched labels): {len(exceptions)}")
    print(f"  chord-sanity rejections (span chord > printed length): {CHORD_REJECTS[0]}")
    print(f"  leg9A rule 1: {pool['stitch_merges']} parent(s) stitched from {pool['stitch_paths']} curve paths")
    dd = pool["dashdot_trains"]
    print(f"  leg9A rule 2: {len(dd)} dash-dot train(s)" + ("" if not dd else ": " + ", ".join(f"{t['len_pt'] * scale:.1f} ft" for t in sorted(dd, key=lambda t: -t['len_pt']))))
    for e in exceptions[:12]:
        print("   ", e)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
