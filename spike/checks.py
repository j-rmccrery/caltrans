"""Track A deterministic checks: does what the sheet SAYS match what the sheet DRAWS?

For every bearing / distance label on the drawing, find the line it annotates (parallel, adjacent),
measure that line from the vector geometry through the georeferencing fit, and compare:
  bearing   printed N dd°mm'ss" E  vs  azimuth of the drawn line (grid north from the fit)
  distance  printed ft             vs  drawn length x scale (grid feet; sheet says ground = grid x 1.0000704)
Curve labels are checked for L = R * delta wherever R, delta and L are printed together.
Every failure or unmatched label becomes an exception with its sheet region. No OCR confidence is used:
the exception queue is driven by geometry, which is the point.
usage: [SHEET=<pdf>] python spike/checks.py   ->  spike/out[/<sheet>]/checks.csv, exceptions.json
"""
import csv
import itertools
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

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
DETAIL_RE = re.compile(r"\bDETAIL\b", re.I)
_NTS_TOKEN = r"(?<![A-Za-z])N\.?T\.?S\.?(?![A-Za-z])"  # "N.T.S." as its own token: a bare substring match
# (no letter boundary) would also fire inside ordinary words that happen to contain "nts" -- agents,
# easements, monuments, instruments, all common on a survey sheet's boilerplate and legend
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


def dms(d, m, s):
    return int(d) + int(m) / 60 + int(s) / 3600


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
        if abs(ln["dir"] @ n) > math.sin(math.radians(tol_deg)):
            continue
        if want_az is not None and az_diff(az_of(ln), want_az) > max(AZ_FILTER, math.degrees(math.atan2(0.3, ln["len_pt"] * scale))):  # a short line drawn 0.3 ft off at one end is not a different bearing
            continue
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        perp = abs((ln["p0"] - c) @ n)
        if not (hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]) and perp < tol_perp:
            cands.append((perp, ln))
            continue
        mid = (ln["p0"] + ln["p1"]) / 2
        mperp, malong = abs((mid - c) @ n), abs((mid - c) @ u)
        if mperp < 2.5 * b["glyph_h"] and malong < 0.6 * b["w"]:
            anchored.append((mperp, ln))
    cands += anchored
    if not cands:
        return None
    on = [(p, ln) for p, ln in cands if p < 0.35 * b["glyph_h"]]  # the label is written on the line itself (some drafters)
    if on:
        cands = on
    if want_ft is not None:
        close = [(p, ln) for p, ln in cands if abs(ln["len_pt"] * scale - want_ft) < 1.0]
        if close:
            return min(close, key=lambda t: t[0])[1]
        spanned = [(p, s) for p, ln in cands for s in [span_for(ln, want_ft, scale, chains)] if s is not ln]  # no piece is the right length: try the span on every candidate's run
        if spanned:
            return min(spanned, key=lambda t: t[0])[1]
    return min(cands, key=lambda t: t[0])[1]


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
            if abs(L - want_ft) <= tol:
                hits.append((i, j))
    if len(hits) != 1:
        return piece
    i, j = hits[0]
    if (i, j) == (k, k):
        return piece
    s0, s1 = run[i]["s0"], run[j]["s1"]
    return {**piece, "p0": run[i]["p0"], "p1": run[j]["p1"], "dir": local_fit_dir(piece["_pts"], s0, s1, piece["dir"]),
            "len_pt": float(s1 - s0), "s0": s0, "s1": s1, "joined": j - i + 1}


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



def nts_circle(page, cx, cy, reach):
    """The dashed circle drawn around a detail caption, if the sheet's vector data separately carries
    one: stroked, dash-attributed paths within reach whose combined extent is roughly circular. None ->
    the caller falls back to a plain box.
    ponytail: a bounding-box union of dash-attributed strokes, not a real circle fit -- upgrade if a
    sheet draws its inset ring some other way (e.g. as many short plain-stroke facets) and this misses it."""
    box = None
    for d in page.get_drawings():
        if d["type"] != "s" or d.get("dashes") in (None, "[] 0", ""):
            continue
        r = d["rect"]
        mx, my = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if math.hypot(mx - cx, my - cy) > reach:
            continue
        box = (r.x0, r.y0, r.x1, r.y1) if box is None else (min(box[0], r.x0), min(box[1], r.y0), max(box[2], r.x1), max(box[3], r.y1))
    if box is None:
        return None
    w, h = box[2] - box[0], box[3] - box[1]
    return box if w > 20 and abs(w - h) < 0.3 * max(w, h) else None


def nts_regions(blocks, page):
    """Not-to-scale detail insets: a caption 'DETAIL "X"' / 'Scale: = N.T.S.' (an N.T.S. block within 3
    glyph heights of a DETAIL block, or one block that reads both at once) marks a region -- the dashed
    circle drawn around it if there is one, else a box 12 glyph heights around the caption. Labels inside
    are not-to-scale citations, checked against nothing."""
    details = [b for b in blocks if DETAIL_RE.search(b["text"])]
    caps, cap_ids = [], set()
    for b in blocks:
        if SCALE_NTS_RE.search(b["text"]):
            caps.append(b); cap_ids.add(id(b))
    for b in blocks:
        if id(b) in cap_ids or not NTS_RE.search(b["text"]):
            continue
        c, u, n = frame(b)
        gh = b["glyph_h"]
        if any(abs((np.array([d["cx"], d["cy"]]) - c) @ n) < 3 * gh and abs((np.array([d["cx"], d["cy"]]) - c) @ u) < 0.6 * max(b["w"], d["w"]) + 3 * gh for d in details):
            caps.append(b); cap_ids.add(id(b))
    regions = []
    for cap in caps:
        gh = cap["glyph_h"]
        near = [d for d in details if math.hypot(d["cx"] - cap["cx"], d["cy"] - cap["cy"]) < 20 * gh] + [cap]
        cx = sum(g["cx"] for g in near) / len(near)
        cy = sum(g["cy"] for g in near) / len(near)
        box = 12 * gh
        regions.append(nts_circle(page, cx, cy, box) or (cx - box, cy - box, cx + box, cy + box))
    return regions


def run_sum(drawn, Ls):
    """Whether a drawn run equals the sum of several record arcs that share it because the boundary
    between them isn't drawn (loop2 legC / STATE.md D3-6 / loop5 legB): the "pass as a run of N" rule.
    Shared by the inline L= labels below and by tables.py's table-tag curves."""
    total = sum(Ls)
    return total, len(Ls) > 1 and abs(drawn - total) <= DIST_TOL + 0.0005 * total


def build_pool(page, blocks):
    """Every candidate a label can be checked against: straight-line chains (split at junctions/circles),
    curved-piece arcs (bezier/polyline curves and dashed trains, split the same way), leader tips, the
    furniture/NTS mask regions. Shared by main() and by any crop/report tool that needs the identical
    pool checks.py itself measured against (leg6A_crops.py), so a diagnostic never silently drifts from
    what the checker actually saw."""
    chains, circles, paths, segs = sheet_lines(page, blocks)
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
    parent_id = itertools.count()
    arcs = []
    for x in arcs_on_sheet(page):
        if max(x["color"]) < 0.2 and np.hypot(*(x["pts"][0] - x["pts"][-1])) > 2:
            parent = next(parent_id)
            arcs.append({"pts": x["pts"], "len_pt": x["len_pt"], "radius_pt": x["radius_pt"], "width": x["width"], "parent": parent})  # the whole, unsplit: no "seq" (never itself part of a sum-group)
            pieces = split_at(x["pts"], circles, junction_lines, ticks=ticks if x["width"] < 0.8 else ())
            if len(pieces) > 1:
                for i, P in enumerate(pieces):
                    arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "radius_pt": x["radius_pt"], "width": x["width"], "parent": parent, "seq": i})
    for c in lines_on_sheet(segs, circles, max_turn_deg=20.0):
        if c["n"] >= 3 and c["len_pt"] > 12:
            parent = next(parent_id)
            for i, P in enumerate(split_at(c["pts"], circles, junction_lines, ticks=ticks if c["width"] < 0.8 else ())):
                arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "radius_pt": c["radius_pt"], "width": c["width"], "parent": parent, "seq": i})
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
    from dashes import collect_dashes, dash_trains
    glyph_h_med = float(np.median([b["glyph_h"] for b in blocks])) if blocks else 6.0
    dash_floor = 5.0 * glyph_h_med
    RESID_TOL = 2.0  # pt: a fitted line's max perpendicular residual, for a bridged train whose raw
    # heading spread reads >2 deg even though it is straight -- the spread test measures dash-to-dash
    # turn one step at a time and a few tenths of a degree of chaining noise compounds over many dashes,
    # while the fit sees the whole run at once; still twice SIDE_TOL (the per-step lateral tolerance
    # chaining itself already enforces), so a run that is genuinely curved (not noisy-straight) still fails
    for t in dash_trains(collect_dashes(page), bridge=6.0 * glyph_h_med):
        if len(t["pts"]) < 3:
            continue
        parent = next(parent_id)
        for i, P in enumerate(split_at(t["pts"], circles, junction_lines)):
            L = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
            if L <= dash_floor:
                continue
            arcs.append({"pts": P, "len_pt": L, "radius_pt": t["radius_pt"], "width": 0.84, "parent": parent, "seq": i})
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
    NTS = nts_regions(blocks, page)
    return {"chains": chains, "circles": circles, "paths": paths, "segs": segs, "arcs": arcs, "tips": tips,
            "FURNITURE": FURNITURE, "NTS": NTS, "junction_lines": junction_lines, "ticks": ticks, "glyph_h_med": glyph_h_med}


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    rot = np.degrees(np.arctan2(bb, a))
    blocks = json.loads((READS).read_text(encoding="utf-8")) + real_text_blocks(page)
    set_decimals(blocks)
    pool = build_pool(page, blocks)
    chains, circles, paths, segs, arcs, tips = pool["chains"], pool["circles"], pool["paths"], pool["segs"], pool["arcs"], pool["tips"]
    FURNITURE, NTS = pool["FURNITURE"], pool["NTS"]

    def az_of(ln):
        """Grid azimuth of a drawn line (deg, clockwise from grid north), through the fit's rotation."""
        dx, dy = ln["dir"][0], -ln["dir"][1]
        return math.degrees(math.atan2(a * dx - bb * dy, bb * dx + a * dy)) % 360
    rows, exceptions, labels, len_pending = [], [], [], []  # labels: every checked value with the line it
    # was measured on (sheet pt), for the traverse; len_pending: standalone L=/(T) labels whose own
    # length matched no drawn piece, resolved by run-sum grouping after every block is scanned (below)
    len_checked = set()  # id() of every block the standalone L=/(T) branch (below) already matched to a
    # drawn piece and passed. The curve-data fillet check (further down) skips only these: a joined block
    # whose L= is ALSO its own separate single-line block would otherwise pass twice for the identical
    # drawn piece. A block the standalone branch missed or deferred is NOT marked -- the fillet check's
    # radius match is a genuinely different search and gets its own try at exactly those

    def at_tip(bi, kind, want=None):
        """The line or arc a label's leader points at (within 4 pt of the arrowhead), if it has a leader.
        Several pieces meet at an arrowhead (the segment, a stub, a crossing line): the one whose length
        matches the printed distance wins, else the nearest. Returns (led, segment); led False = no
        leader, or the leader belongs to another value in the same block: fall back to 'beside'."""
        if bi not in tips:
            return False, None
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
            return True, None
        if want is not None:
            close = [t for t in cands if abs(t[1]["len_pt"] * scale - want) < 1.0]
            if close:
                return True, min(close, key=lambda t: t[0])[1]
            if sum(1 for t in blocks[bi]["text"].replace(" ", "").split("|") if DIST.match(t)) > 1:
                return False, None  # two dimensions in one block, the leader is the other one's
        return True, min(cands, key=lambda t: t[0])[1]

    def region(b):
        return [round(b["cx"] - b["w"] / 2 - 4), round(b["cy"] - b["h"] / 2 - 4), round(b["cx"] + b["w"] / 2 + 4), round(b["cy"] + b["h"] / 2 + 4)]

    def shape(seg):
        """The drawn line or arc a check measured, as points (pt), so the exception page can show it."""
        P = seg["pts"][:: max(1, len(seg["pts"]) // 20)] if "pts" in seg else [seg["p0"], seg["p1"]]
        return [[round(float(x), 1), round(float(y), 1)] for x, y in P]

    for bi, b in enumerate(blocks):
        if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in FURNITURE):
            continue  # table cells and title block: the record, not labels on the drawing
        if NTS and any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in NTS):
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
            led, arc = at_tip(bi, "arc", want)
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
                arc = min(close, key=lambda x: (abs(x["len_pt"] * scale - want), len(x["pts"]), float(x["pts"][0][0]), float(x["pts"][0][1]))) if close else None
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
                tol = DIST_TOL + 0.0005 * want
                # the nearest piece is usually the seed, but not always the one WHOSE parent contains the
                # printed run (a nearer, unrelated stub can sit closer to the label than the target curve
                # itself does): try the 20 nearest in order (all of them, in practice -- 160pt rarely
                # holds more) and take the first whose own parent yields a unique matching window
                for seed in wide[:20]:
                    run = sorted((x for x in arcs if x.get("parent") == seed["parent"] and "seq" in x), key=lambda x: x["seq"])
                    k = next(i for i, x in enumerate(run) if x is seed)
                    hits = [(i, j) for i in range(0, k + 1) for j in range(k, len(run))
                            if abs(sum(x["len_pt"] for x in run[i:j + 1]) * scale - want) <= tol]
                    if len(hits) == 1 and hits[0] != (k, k):
                        i, j = hits[0]
                        group_arc = run[i:j + 1]
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
            else:
                len_pending.append({"text": lines[0], "want": want, "total": is_total, "arc": arc, "led": led, "region": region(b)})
                len_checked.add(id(b))  # a candidate WAS found here (just the wrong length): the fillet
                # check's own radius-based search would only re-measure the identical piece and re-fail it
            continue
        # a bearing and its distance often come back as one OCR line: take the tokens inside each line
        parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines
        for part in parts:
            if BEAR.match(part) and BEAR.match(part)[6]:
                rows.append(["bearing (R)", part, "", "", "radial: not checked"]); continue
            if BEAR.match(part):
                mate = next((float(dist_num(DIST.match(t))[0]) for t in parts if DIST.match(t)), None)
                led, ln = at_tip(bi, "line", mate)
                if not led:
                    ln = nearest_line(b, chains, 5.0 * b["glyph_h"], mate, scale, want_az=azimuth(part), az_of=az_of)
                if ln is not None:
                    ln = span_for(ln, mate, scale, chains)
                if ln is None:
                    exceptions.append({"kind": "bearing", "text": part, "issue": "leader points at no line" if led else "no line found beside label", "region": region(b)}); continue
                dx, dy = ln["dir"][0], -ln["dir"][1]                      # sheet direction, y up
                gx, gy = a * dx - bb * dy, bb * dx + a * dy                # into the grid frame
                az = math.degrees(math.atan2(gx, gy)) % 360               # from grid north, clockwise
                want = azimuth(part)
                diff = min(abs((az - want + 180) % 360 - 180), abs((az + 180 - want + 180) % 360 - 180))
                ok = diff <= BEAR_TOL
                rows.append(["bearing", part, fmt_bearing(az if abs((az - want + 180) % 360 - 180) < 90 else az + 180), f"{diff * 60:.1f}'", "pass" if ok else "FAIL"])
                labels.append({"kind": "bearing", "printed": part, "az": want, "line": shape(ln), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                if not ok:
                    exceptions.append({"kind": "bearing", "text": part, "drawn": fmt_bearing(az), "off_arcmin": round(diff * 60, 1), "region": region(b), "line": shape(ln)})
            elif DIST.match(part):
                m = DIST.match(part)
                num_str, is_total = dist_num(m)
                if is_total or curve_data or STATION.search(b["text"]) or AREA_CTX.search(b["text"]):
                    continue  # (T) totals, curve data (R=, Δ, L=), a station number, or a parcel-area figure: not a line length
                want = float(num_str)
                baz = next((azimuth(t) for t in parts if BEAR.match(t) and not BEAR.match(t)[6]), None)  # the bearing printed with it
                led, ln = at_tip(bi, "line", want)
                if not led:
                    ln = nearest_line(b, chains, 5.0 * b["glyph_h"], want, scale, want_az=baz, az_of=az_of)
                if ln is not None:
                    ln = span_for(ln, want, scale, chains)
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
                    arc = at_tip(bi, "arc", want)[1] if led else nearest_arc(b, arcs, 1.5 * b["glyph_h"])
                    if arc is not None and (ln is None or abs(arc["len_pt"] * scale - want) < abs(ln["len_pt"] * scale - want)):
                        drawn = arc["len_pt"] * scale
                        ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
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
                rows.append(["distance", part, f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass" if ok else "FAIL"])
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
                rows.append(["arc length", p["text"], f"{drawn:.2f}", f"{drawn - p['want']:+.2f}", "FAIL"])
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": False, "how": "leader" if p["led"] else "beside", "region": p["region"]})
                exceptions.append({"kind": "arc length", "text": p["text"], "drawn_ft": round(drawn, 2), "off_ft": round(drawn - p["want"], 2), "region": p["region"], "line": shape(arc)})
        elif by_sum:
            sum_str = f"{drawn:.2f} = " + " + ".join(f"{x:.2f}" for x in Ls)
            for p in piece:
                rows.append(["arc length", p["text"], sum_str, f"{drawn - total:+.2f}",
                             f"pass as a run of {len(piece)}: the boundary between these arcs is not drawn"])
                labels.append({"kind": "arc", "printed": p["text"], "ft": p["want"], "line": shape(arc), "ok": True, "how": "leader" if p["led"] else "beside", "region": p["region"]})
        else:  # the run doesn't match the sum either: fail once against the sum, not once per label
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
                continue  # this L= value already got its own full geometric check above (it's also its
                # own standalone "L=...'" block); a second row for the identical drawn piece would just
                # double-count one label as two passes (or two, possibly conflicting, fails)
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
                sumtxt = f"{drawn:.2f}" if len(pieces) == 1 else f"{drawn:.2f} = " + " + ".join(f"{v:.2f}" for v in lens_ft)
                printed = f"R={R}' L={L}'"
                rows.append(["arc length", printed, sumtxt, f"{drawn - L:+.2f}", "pass" if ok2 else "FAIL"])
                labels.append({"kind": "arc", "printed": printed, "ft": L, "line": shape(pieces[0]), "ok": ok2, "how": "leader" if tip else "beside", "region": region(len_block)})
                if not ok2:
                    exceptions.append({"kind": "arc length", "text": printed, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - L, 2), "region": region(len_block), "line": shape(pieces[0])})

    (OUT / "labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
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
    for e in exceptions[:12]:
        print("   ", e)


if __name__ == "__main__":
    main()
