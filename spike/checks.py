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
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, frame, real_text_blocks, segments  # noqa: E402

BEAR = re.compile(r"^([NS])(\d{1,2})°(\d{2})'(\d{2})\"([EW])(\(R\))?$")
DIST = re.compile(r"^(\d{1,4}\.\d{2})'?(\(T\))?$")
ANG = re.compile(r"^[Δ△]?=?(\d{1,3})°(\d{2})'(\d{2})\"(\(T\))?$")
RAD = re.compile(r"^R=(\d{1,5}\.\d{2})'?$")
LEN = re.compile(r"^L=(\d{1,5}\.\d{2})'?(\(T\))?$")
DIST_TOL = 0.30   # ft, plus 0.05 %
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


def lines_on_sheet(segs, circles):
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
                    if d @ cur_dir > 0.99995:  # within 0.6 degrees
                        nxt = (k, far)
                        break
                if nxt is None:
                    break
                used.add(nxt[0]); chain.append(nxt[0]); cur = nxt[1]
        pts = np.array([q for k in chain for q in segs[k][:2]])
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


def linework_segments(page):
    """Like georef.segments, but without glyph strokes: a character is a small multi-stroke path."""
    segs = []
    for pid, d in enumerate(page.get_drawings()):
        r = d["rect"]
        if max(r.width, r.height) <= 12 and len(d["items"]) > 1:
            continue
        c = d.get("color")
        if c is None or max(c) > 0.6:
            continue  # white masks and light grey hatch are not lines a label describes
        for it in d["items"]:
            if it[0] == "l":
                a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
                if np.hypot(*(a - b)) > 1.0:
                    segs.append((a, b, round(d.get("width") or 0, 2), pid))
    return segs


def nearest_line(b, chains, tol_perp, want_ft=None, scale=None, tol_deg=4.0):  # a rotated label box carries 1-3 deg of angle error
    """The line a label describes: parallel, overlapping it along the reading direction, close beside it.
    A label often sits between two parallel lines; when a printed distance is known, a neighbour whose
    drawn length matches it within 1 ft is preferred (the bearing check stays independent)."""
    c, u, n = frame(b)
    cands = []
    for ln in chains:
        if abs(ln["dir"] @ n) > math.sin(math.radians(tol_deg)):
            continue
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        if hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]:
            continue  # no overlap along the reading direction
        perp = abs((ln["p0"] - c) @ n)
        if perp < tol_perp:
            cands.append((perp, ln))
    if not cands:
        return None
    if want_ft is not None:
        close = [(p, ln) for p, ln in cands if abs(ln["len_pt"] * scale - want_ft) < 1.0]
        if close:
            return min(close)[1]
    return min(cands, key=lambda t: t[0])[1]


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    rot = np.degrees(np.arctan2(bb, a))
    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8")) + real_text_blocks(page)
    segs = linework_segments(page)
    _, circles = segments(page)
    chains = [c for c in lines_on_sheet(segs, circles) if c["len_pt"] >= 6]
    rows, exceptions = [], []

    def region(b):
        return [round(b["cx"] - b["w"] / 2 - 4), round(b["cy"] - b["h"] / 2 - 4), round(b["cx"] + b["w"] / 2 + 4), round(b["cy"] + b["h"] / 2 + 4)]

    for b in blocks:
        for part in b["text"].replace(" ", "").split("|"):
            if BEAR.match(part):
                mate = next((float(DIST.match(t)[1]) for t in b["text"].replace(" ", "").split("|") if DIST.match(t)), None)
                ln = nearest_line(b, chains, 5.0 * b["glyph_h"], mate, scale)
                if ln is None:
                    exceptions.append({"kind": "bearing", "text": part, "issue": "no line found beside label", "region": region(b)}); continue
                dx, dy = ln["dir"][0], -ln["dir"][1]                      # sheet direction, y up
                gx, gy = a * dx - bb * dy, bb * dx + a * dy                # into the grid frame
                az = math.degrees(math.atan2(gx, gy)) % 360               # from grid north, clockwise
                want = azimuth(part)
                diff = min(abs((az - want + 180) % 360 - 180), abs((az + 180 - want + 180) % 360 - 180))
                ok = diff <= BEAR_TOL
                rows.append(["bearing", part, fmt_bearing(az if abs((az - want + 180) % 360 - 180) < 90 else az + 180), f"{diff * 60:.1f}'", "pass" if ok else "FAIL"])
                if not ok:
                    exceptions.append({"kind": "bearing", "text": part, "drawn": fmt_bearing(az), "off_arcmin": round(diff * 60, 1), "region": region(b)})
            elif DIST.match(part) and not b.get("real"):
                m = DIST.match(part)
                if m[2] or re.search(r"R=|L=|Δ|△", b["text"]):  # (T) totals and curve data are not line lengths
                    continue
                ln = nearest_line(b, chains, 5.0 * b["glyph_h"], float(m[1]), scale)
                if ln is None:
                    exceptions.append({"kind": "distance", "text": part, "issue": "no line found beside label", "region": region(b)}); continue
                W = page.rect.width
                if min(ln["p0"][0], ln["p1"][0]) < 262 or max(ln["p0"][0], ln["p1"][0]) > W - 50:
                    exceptions.append({"kind": "distance", "text": part, "issue": "line runs to the sheet edge (matchline); not checkable on this sheet", "region": region(b)}); continue
                drawn = ln["len_pt"] * scale
                want = float(m[1])
                ok = abs(drawn - want) <= DIST_TOL + 0.0005 * want
                rows.append(["distance", part, f"{drawn:.2f}", f"{drawn - want:+.2f}", "pass" if ok else "FAIL"])
                if not ok:
                    exceptions.append({"kind": "distance", "text": part, "drawn_ft": round(drawn, 2), "off_ft": round(drawn - want, 2), "region": region(b)})

    # curves: R, delta and L printed together (same block or stacked)
    curve_blocks = [b for b in blocks if any(RAD.match(t) or ANG.match(t) or LEN.match(t) for t in b["text"].replace(" ", "").split("|"))]
    for b in curve_blocks:
        parts = b["text"].replace(" ", "").split("|")
        c, u, n = frame(b)
        for o in curve_blocks:
            if o is not b and abs((np.array([o["cx"], o["cy"]]) - c) @ u) < 0.7 * max(b["w"], o["w"]) and 0 < (np.array([o["cx"], o["cy"]]) - c) @ n < 3.2 * b["glyph_h"]:
                parts += o["text"].replace(" ", "").split("|")
        R = next((float(RAD.match(t)[1]) for t in parts if RAD.match(t)), None)
        D = next((dms(*ANG.match(t).groups()[:3]) for t in parts if ANG.match(t)), None)
        L = next((float(LEN.match(t)[1]) for t in parts if LEN.match(t)), None)
        if R and D and L:
            calc = R * math.radians(D)
            ok = abs(calc - L) <= 0.02 + 0.0005 * L
            rows.append(["curve L=R*delta", f"R={R} Δ={D:.4f}° L={L}", f"{calc:.2f}", f"{calc - L:+.2f}", "pass" if ok else "FAIL"])
            if not ok:
                exceptions.append({"kind": "curve", "text": b["text"], "calc_L": round(calc, 2), "printed_L": L, "region": region(b)})

    with open(OUT / "checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["check", "printed", "drawn", "difference", "result"]); w.writerows(rows)
    (OUT / "exceptions.json").write_text(json.dumps(exceptions, indent=1, ensure_ascii=False), encoding="utf-8")
    kinds = {}
    for r in rows:
        k = kinds.setdefault(r[0], [0, 0]); k[0] += 1; k[1] += r[4] == "pass"
    print(f"lines on sheet {len(chains)} | scale {scale:.5f} ft/pt, grid north {rot:+.3f} deg from sheet up")
    for k, (n, ok) in kinds.items():
        print(f"  {k:16} checked {n:3}  pass {ok:3}  fail {n - ok:3}")
    print(f"  exceptions (fails + unmatched labels): {len(exceptions)}")
    for e in exceptions[:12]:
        print("   ", e)


if __name__ == "__main__":
    main()
