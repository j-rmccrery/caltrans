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
DIST = re.compile(r"^(\d{1,4}\.\d{2,3})'?(\(T\))?$")  # 2 decimals in feet, 3 on the metric sheets
ANG = re.compile(r"^(?:[Δ△]|A)?=?(\d{1,3})°(\d{2})'(\d{2})\"(\(T\))?$")  # delta's prefix is a symbol
# (Δ/△) on some sheets, the letter "A=" on this drafter's (CHaldenwang, north set): every curve-data
# block on R-10741.1/.2/.3 uses "A=", never Δ/△, and none of the south sheets use "A=" (checked), so
# accepting both generalises to the drafter rather than guessing a single sheet's convention
RAD = re.compile(r"^R=(\d{1,5}\.\d{2})'?$")
LEN = re.compile(r"^L=(\d{1,5}\.\d{2})'?(\(T\))?$")
TOKEN = re.compile(r"[NS]\d{1,2}°\d{2}'\d{2}\"[EW](?:\(R\))?|(?<![\d.,+])\d{1,4}\.\d{2,3}'?(?:\(T\))?(?![\d])")
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


def set_decimals(blocks):
    """A sheet prints its distances with two decimals (feet) or three (the metric sheets): take the
    majority and make DIST and TOKEN demand it, so the other form is not read as a distance."""
    global DIST, TOKEN
    two = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{2}(?!\d)", b["text"])) for b in blocks)
    three = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{3}(?!\d)", b["text"])) for b in blocks)
    n = "3" if three > two else "2"
    DIST = re.compile(r"^(\d{1,4}\.\d{" + n + r"})'?(\(T\))?$")
    TOKEN = re.compile(r"[NS]\d{1,2}°\d{2}'\d{2}\"[EW](?:\(R\))?|(?<![\d.,+])\d{1,4}\.\d{" + n + r"}'?(?:\(T\))?(?![\d])")
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
        chains.append({"p0": p0, "p1": p1, "dir": d0, "len_pt": float(al.max() - al.min()), "width": w0, "n": len(chain)})
    return chains


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
                    A, B, C = P[0], P[len(P) // 2], P[-1]
                    den = 2 * abs((A[0] - C[0]) * (B[1] - A[1]) - (A[0] - B[0]) * (C[1] - A[1]))
                    R = float(np.hypot(*(A - B)) * np.hypot(*(B - C)) * np.hypot(*(C - A)) / den) if den > 1e-6 else float("inf")
                    out.append({"pts": P, "len_pt": L, "radius_pt": R, "width": round(d.get("width") or 0, 2), "color": c})
                run = []
    return out


def nearest_arc(b, arcs, tol_perp, tol_deg=8.0):
    """Arc whose nearest point lies beside the label with its tangent along the label's reading direction."""
    c, u, n = frame(b)
    best = None
    for arc in arcs:
        P = arc["pts"]
        d = np.hypot(*(P - c).T)
        k = int(d.argmin())
        if d[k] > tol_perp + b["w"] / 2:
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
                out.append({**c, "p0": p + t * s0, "p1": p + t * s1, "len_pt": float(s1 - s0), "run": k, "s0": float(s0), "s1": float(s1)})
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
    return {**piece, "p0": run[i]["p0"], "p1": run[j]["p1"], "len_pt": float(run[j]["s1"] - run[i]["s0"]), "s0": run[i]["s0"], "s1": run[j]["s1"], "joined": j - i + 1}


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


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    rot = np.degrees(np.arctan2(bb, a))
    blocks = json.loads((READS).read_text(encoding="utf-8")) + real_text_blocks(page)
    set_decimals(blocks)
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
    arcs = []
    for x in arcs_on_sheet(page):
        if max(x["color"]) < 0.2 and np.hypot(*(x["pts"][0] - x["pts"][-1])) > 2:
            arcs.append({"pts": x["pts"], "len_pt": x["len_pt"], "radius_pt": x["radius_pt"], "width": x["width"]})
            pieces = split_at(x["pts"], circles, junction_lines, ticks=ticks if x["width"] < 0.8 else ())
            if len(pieces) > 1:
                for P in pieces:
                    arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "radius_pt": x["radius_pt"], "width": x["width"]})
    for c in lines_on_sheet(segs, circles, max_turn_deg=20.0):
        if c["n"] >= 3 and c["len_pt"] > 12:
            for P in split_at(c["pts"], circles, junction_lines, ticks=ticks if c["width"] < 0.8 else ()):
                arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "radius_pt": c["radius_pt"], "width": c["width"]})
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
        for P in split_at(t["pts"], circles, junction_lines):
            L = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
            if L <= dash_floor:
                continue
            arcs.append({"pts": P, "len_pt": L, "radius_pt": t["radius_pt"], "width": 0.84})
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
    FURNITURE = list(FURNITURE) + alignment_table_regions(blocks)  # tables.json's _regions plus this table it doesn't cover
    NTS = nts_regions(blocks, page)

    def az_of(ln):
        """Grid azimuth of a drawn line (deg, clockwise from grid north), through the fit's rotation."""
        dx, dy = ln["dir"][0], -ln["dir"][1]
        return math.degrees(math.atan2(a * dx - bb * dy, bb * dx + a * dy)) % 360
    rows, exceptions, labels = [], [], []  # labels: every checked value with the line it was measured on (sheet pt), for the traverse

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
            # (T) used to be skipped here ("a run total over several tags, not a single arc"), but a
            # standalone (T) is just this one annotation's own drawn run between its vertex circles --
            # STATE.md measured that run against the printed (T) to 0.02 ft -- so it checks the same way
            led, arc = at_tip(bi, "arc", want)
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
            if arc is None:
                exceptions.append({"kind": "arc length", "text": lines[0], "issue": "leader points at no arc" if led else "no arc within 5 glyph heights matches the printed length", "region": region(b)})
            else:
                drawn = arc["len_pt"] * scale
                ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                rows.append(["arc length", lines[0], f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass" if ok else "FAIL"])
                labels.append({"kind": "arc", "printed": lines[0], "ft": want, "line": shape(arc), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                if not ok:
                    exceptions.append({"kind": "arc length", "text": lines[0], "drawn_ft": round(drawn, 2), "off_ft": round(drawn - want, 2), "region": region(b), "line": shape(arc)})
            continue
        # a bearing and its distance often come back as one OCR line: take the tokens inside each line
        parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines
        for part in parts:
            if BEAR.match(part) and BEAR.match(part)[6]:
                rows.append(["bearing (R)", part, "", "", "radial: not checked"]); continue
            if BEAR.match(part):
                mate = next((float(DIST.match(t)[1]) for t in parts if DIST.match(t)), None)
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
                if m[2] or curve_data or STATION.search(b["text"]) or AREA_CTX.search(b["text"]):
                    continue  # (T) totals, curve data (R=, Δ, L=), a station number, or a parcel-area figure: not a line length
                want = float(m[1])
                baz = next((azimuth(t) for t in parts if BEAR.match(t) and not BEAR.match(t)[6]), None)  # the bearing printed with it
                led, ln = at_tip(bi, "line", want)
                if not led:
                    ln = nearest_line(b, chains, 5.0 * b["glyph_h"], want, scale, want_az=baz, az_of=az_of)
                if ln is not None:
                    ln = span_for(ln, want, scale, chains)
                if ln is None or abs(ln["len_pt"] * scale - want) > 1.0:
                    arc = at_tip(bi, "arc", want)[1] if led else nearest_arc(b, arcs, 5.0 * b["glyph_h"])
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
                want = float(m[1])
                ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                rows.append(["distance", part, f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass" if ok else "FAIL"])
                labels.append({"kind": "distance", "printed": part, "ft": want, "line": shape(ln), "ok": ok, "how": "leader" if led else "beside", "region": region(b)})
                if not ok:
                    exceptions.append({"kind": "distance", "text": part, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - want, 2), "region": region(b), "line": shape(ln)})

    # curves: R, delta and L printed together (same block or stacked, or joined into one OCR line
    # with no "|" split -- RAD_TOK/ANG_TOK/LEN_TOK find those the same way TOKEN finds BEAR/DIST)
    curve_blocks = [b for b in blocks if any(RAD_TOK.search(t) or ANG_TOK.search(t) or LEN_TOK.search(t) for t in b["text"].replace(" ", "").split("|"))]

    def n_curve_toks(text):
        return sum(1 for pat in (RAD_TOK, ANG_TOK, LEN_TOK) for _ in pat.finditer(text))
    seen = set()
    for b in curve_blocks:
        parts = b["text"].replace(" ", "").split("|")
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
