"""Trace Presidio's C21 by eye: draw every curved piece in the checker's pool near C21's leader piece, coloured by
parent, with each piece's length in ft, and mark where 876.88 ft (the record) would end walking from the C21
piece's start along the pool. Writes spike/out/c21_trace.png and prints the parent chain."""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import checks  # noqa: E402
from georef import OUT, PDF, READS  # noqa: E402

page = pymupdf.open(PDF)[0]
blocks = json.loads(READS.read_text(encoding="utf-8"))
g = json.loads((OUT / "georef.json").read_text())
scale = g["scale_ft_per_pt"]
pool = checks.build_pool(page, blocks)
tags = {t["tag"]: t for t in json.loads((OUT / "tag_labels.json").read_text(encoding="utf-8")) if t.get("tag") == "C21"}
c21 = np.array(tags["C21"]["line"])
p0, p1 = c21[0], c21[-1]
print(f"C21 piece: {p0.round(1)} -> {p1.round(1)}, {float(np.sum(np.hypot(*np.diff(c21, axis=0).T))) * scale:.2f} ft; record 876.88 ft, R=1380 (= {1380 / scale:.1f} pt)")

# every arc whose midpoint lies within 500 pt of the C21 piece, with parent, seq, length, fitted radius
near = []
for a in pool["arcs"]:
    P = np.asarray(a["pts"])
    mid = P[len(P) // 2]
    d = min(np.hypot(*(mid - p0)), np.hypot(*(mid - p1)), float(np.min(np.hypot(*(c21 - mid).T))))
    if d < 500:
        R = a.get("radius_pt")
        near.append((a, d, R))
near.sort(key=lambda t: (t[0].get("parent", -1), t[0].get("seq", 0)))
print(f"{len(near)} curved pieces within 500 pt; by parent:")
byp = {}
for a, d, R in near:
    byp.setdefault(a["parent"], []).append(a)
for par, items in byp.items():
    tot = sum(x["len_pt"] for x in items) * scale
    if tot < 150 and not any((x.get("radius_pt") or 0) * scale > 900 for x in items):
        continue
    Rs = [x.get("radius_pt") for x in items]
    Rft = [round(r * scale) if (r and r == r and r < 1e6) else None for r in Rs]
    dd = any(x.get("dashdot") for x in items)
    print(f"  parent {par:4d}: {len(items)} pieces, {tot:8.2f} ft total, radii ft {Rft[:6]}{' dashdot' if dd else ''}, seq {[x.get("seq") for x in items]}")

# render
clip = pymupdf.Rect(min(p0[0], p1[0]) - 450, min(p0[1], p1[1]) - 260, max(p0[0], p1[0]) + 450, max(p0[1], p1[1]) + 260)
Z = 2.5
pix = page.get_pixmap(matrix=pymupdf.Matrix(Z, Z), clip=clip)
import cv2
img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()
img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
rng = np.random.default_rng(3)
colors = {}
for a, d, R in near:
    par = a["parent"]
    if par not in colors:
        colors[par] = tuple(int(v) for v in rng.integers(40, 220, 3))
    P = ((np.asarray(a["pts"]) - [clip.x0, clip.y0]) * Z).astype(np.int32)
    cv2.polylines(img, [P.reshape(-1, 1, 2)], False, colors[par], 3)
    m = P[len(P) // 2]
    cv2.putText(img, f"{a['len_pt'] * scale:.0f}", (int(m[0]) + 3, int(m[1]) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors[par], 1, cv2.LINE_AA)
# C21's own piece in blue, thick; leader tip
P = ((c21 - [clip.x0, clip.y0]) * Z).astype(np.int32)
cv2.polylines(img, [P.reshape(-1, 1, 2)], False, (255, 90, 0), 5)
cv2.putText(img, "C21 piece 449.84", (int(P[0][0]), int(P[0][1]) - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 90, 0), 2, cv2.LINE_AA)
# 876.88 ft as a circle-arc chord scale bar: draw the record radius R=1380 ft as a circle through the piece for reference
cv2.putText(img, f"record C21: R=1380 ft ({1380 / scale:.0f} pt)  L=876.88 ft ({876.88 / scale:.0f} pt)", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
out = OUT / "c21_trace.png"
cv2.imwrite(str(out), img)
print("wrote", out, img.shape)

# ---- ends: what sits at each end of C21's stitched parent, and the gap to it
par104 = [a for a in pool["arcs"] if a.get("parent") == tags and False]
mine = [a for a in pool["arcs"] if np.allclose(np.asarray(a["pts"])[0], p0, atol=0.5) or np.allclose(np.asarray(a["pts"])[-1], p1, atol=0.5)]
mp = mine[0]["parent"] if mine else None
fam = sorted([a for a in pool["arcs"] if a.get("parent") == mp], key=lambda a: a.get("seq", 0))
print(f"C21's parent {mp}: {len(fam)} pieces, {sum(a['len_pt'] for a in fam) * scale:.2f} ft")
for a in fam:
    P = np.asarray(a["pts"]); print(f"   seq {a.get('seq')}: {P[0].round(1)} -> {P[-1].round(1)}  {a['len_pt'] * scale:7.2f} ft")
ends = [np.asarray(fam[0]["pts"])[0], np.asarray(fam[-1]["pts"])[-1]]
for label, e in zip(("west end", "east end"), ends):
    print(f" {label} {e.round(1)}: nearest other-parent piece ends:")
    cand = []
    for a in pool["arcs"]:
        if a.get("parent") == mp: continue
        P = np.asarray(a["pts"])
        for which, q in (("start", P[0]), ("end", P[-1])):
            d = float(np.hypot(*(q - e)))
            if d < 60: cand.append((d, a.get("parent"), a.get("seq"), which, a["len_pt"] * scale, (a.get("radius_pt") or 0) * scale))
    for d, par, seq, which, L, R in sorted(cand, key=lambda t: t[0])[:5]:
        print(f"    {d:5.1f} pt  parent {par} seq {seq} {which}  len {L:7.2f} ft  R~{R:.0f} ft")
# tight crops of both ends
for label, e in zip(("west", "east"), ends):
    clip = pymupdf.Rect(e[0] - 140, e[1] - 90, e[0] + 140, e[1] + 90)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=clip)
    img = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy(), cv2.COLOR_RGB2BGR)
    for a in pool["arcs"]:
        P = np.asarray(a["pts"])
        if not (clip.x0 - 20 < P[:, 0].mean() < clip.x1 + 20 and clip.y0 - 20 < P[:, 1].mean() < clip.y1 + 20): continue
        col = (255, 90, 0) if a.get("parent") == mp else (0, 140, 0)
        Q = ((P - [clip.x0, clip.y0]) * 4).astype(np.int32)
        cv2.polylines(img, [Q.reshape(-1, 1, 2)], False, col, 3)
        m = Q[len(Q) // 2]; cv2.putText(img, f"p{a.get('parent')}/{a.get('seq')} {a['len_pt'] * scale:.0f}", (int(m[0]), int(m[1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    cv2.circle(img, tuple(((e - [clip.x0, clip.y0]) * 4).astype(int)), 10, (0, 0, 255), 2)
    cv2.imwrite(str(OUT / f"c21_{label}_end.png"), img); print("wrote", OUT / f"c21_{label}_end.png")

# ---- do the pieces west of the parent lie on C21's own circle?
def fit_circle(P):
    P = np.asarray(P, float); x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(P))]; b = x * x + y * y
    cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    r = np.sqrt(c + cx * cx + cy * cy); return np.array([cx, cy]), r
allpts = np.vstack([np.asarray(a["pts"]) for a in fam])
C, R = fit_circle(allpts)
print(f"C21 parent circle: centre {C.round(1)}, R {R * scale:.1f} ft (record 1380); residual max {np.max(np.abs(np.hypot(*(allpts - C).T) - R)):.2f} pt")
west = ends[0]
print("pieces whose points sit on that circle (residual < 2 pt) and end within 200 pt of the west end, west of it:")
for a in pool["arcs"]:
    if a.get("parent") == mp: continue
    P = np.asarray(a["pts"])
    if P[:, 0].mean() > west[0] + 5 or float(np.min(np.hypot(*(P - west).T))) > 200: continue
    res = np.abs(np.hypot(*(P - C).T) - R)
    if np.max(res) < 3.0:
        print(f"   parent {a.get('parent')} seq {a.get('seq')}: {P[0].round(1)} -> {P[-1].round(1)}  {a['len_pt'] * scale:7.2f} ft  max residual {np.max(res):.2f} pt  dashdot={a.get('dashdot', False)}")
# the record's start: 876.88 ft back along the circle from the east end
east = ends[1]
theta_e = np.arctan2(east[1] - C[1], east[0] - C[0]); dth = (876.88 / scale) / R
for sgn in (1, -1):
    th = theta_e + sgn * dth; s0 = C + R * np.array([np.cos(th), np.sin(th)])
    print(f"record start candidate (going {'ccw' if sgn > 0 else 'cw'} from the east end): {s0.round(1)}")

# ---- per-piece geometry along the thin line, west to east
rows = []
for a in pool["arcs"]:
    P = np.asarray(a["pts"])
    if not (850 < P[:, 0].mean() < 1900 and 520 < P[:, 1].mean() < 760) or len(P) < 3 or a["len_pt"] * scale < 20: continue
    Cc, Rr = fit_circle(P); res = float(np.max(np.abs(np.hypot(*(P - Cc).T) - Rr)))
    h0 = np.degrees(np.arctan2(*(P[1] - P[0])[::-1])); h1 = np.degrees(np.arctan2(*(P[-1] - P[-2])[::-1]))
    rows.append((P[0][0], a.get("parent"), a.get("seq"), P[0].round(0), P[-1].round(0), a["len_pt"] * scale, Rr * scale, res, h0, h1, a.get("dashdot", False)))
rows.sort(key=lambda t: t[0])
print(f"{'parent':>7} {'seq':>4} {'start':>14} {'end':>14} {'len ft':>8} {'R ft':>8} {'resid':>6} {'h0':>7} {'h1':>7}  dd")
for x0, par, seq, s0, s1, L, Rft, res, h0, h1, dd in rows:
    print(f"{par:>7} {str(seq):>4} {str(s0):>14} {str(s1):>14} {L:8.2f} {Rft:8.0f} {res:6.2f} {h0:7.1f} {h1:7.1f}  {'dd' if dd else ''}")

# ---- what continues east of p97/1's end, and what marks the west start
for label, e in (("east of p97/1", np.array([1888.0, 673.0])), ("west start (p104/1->2 join)", np.array([1320.1, 659.9]))):
    print(label, e)
    for a in pool["arcs"]:
        P = np.asarray(a["pts"])
        for which, q in (("start", P[0]), ("end", P[-1])):
            d = float(np.hypot(*(q - e)))
            if d < 15 and a["len_pt"] * scale > 5:
                Cc, Rr = fit_circle(P) if len(P) >= 3 else (None, float('nan'))
                print(f"   arc parent {a.get('parent')} seq {a.get('seq')} {which} at {d:.1f} pt: len {a['len_pt'] * scale:.2f} ft R {Rr * scale:.0f}")
    for c in pool["chains"]:
        for which, q in (("p0", c["p0"]), ("p1", c["p1"])):
            d = float(np.hypot(*(np.asarray(q) - e)))
            if d < 15 and c["len_pt"] * scale > 5:
                print(f"   chain {which} at {d:.1f} pt: len {c['len_pt'] * scale:.2f} ft dir {np.degrees(np.arctan2(c['dir'][1], c['dir'][0])):.1f} deg {'dashed' if c.get('dashed') else ''}")
    for c in pool["circles"]:
        cc = np.asarray(c[:2]) if not isinstance(c, dict) else np.array([c.get("cx", c.get("x")), c.get("cy", c.get("y"))])
        d = float(np.hypot(*(cc - e)))
        if d < 12: print(f"   vertex circle at {d:.1f} pt")

# ---- the predicted C21 end: 876.88 - (255.91+193.93+86.86+278.14) = 62.04 ft into p97/2; any mark there?
p972 = next(a for a in pool["arcs"] if a.get("parent") == 97 and a.get("seq") == 2)
P = np.asarray(p972["pts"]); seg = np.hypot(*np.diff(P, axis=0).T); cum = np.concatenate([[0], np.cumsum(seg)])
for need_ft in (62.04, 62.04 + 86.86):  # with and without the junction sliver counted
    s = need_ft / scale; i = int(np.searchsorted(cum, s)); t = (s - cum[i - 1]) / seg[i - 1]; q = P[i - 1] + t * (P[i] - P[i - 1])
    print(f"predicted end {need_ft:.2f} ft into p97/2 -> {q.round(1)}")
    for c in pool["circles"]:
        cc = np.asarray(c[:2]) if not isinstance(c, dict) else np.array([c.get("cx", c.get("x")), c.get("cy", c.get("y"))])
        d = float(np.hypot(*(cc - q)))
        if d < 12: print(f"   vertex circle {d:.1f} pt away")
    for t_ in pool["ticks"]:
        tp = np.asarray(t_["p0"] if isinstance(t_, dict) else t_[0]); tq = np.asarray(t_["p1"] if isinstance(t_, dict) else t_[1])
        d = min(float(np.hypot(*(tp - q))), float(np.hypot(*(tq - q))))
        if d < 8: print(f"   tick end {d:.1f} pt away")
    for ch in pool["chains"]:
        d = min(float(np.hypot(*(np.asarray(ch["p0"]) - q))), float(np.hypot(*(np.asarray(ch["p1"]) - q))))
        if d < 6: print(f"   line end {d:.1f} pt away, len {ch['len_pt'] * scale:.1f} ft dir {np.degrees(np.arctan2(ch['dir'][1], ch['dir'][0])):.0f}")
