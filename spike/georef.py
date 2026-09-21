"""Georeference the sheet from its own printed control, with no hand-typed coordinates.

1. Pair the N / E coordinate callouts the reader found (read_rapid.json).
2. Trace each callout's leader line through the vector linework to the point it labels.
3. Fit sheet -> CCS83 Zone 3 (US survey ft) as a similarity transform; report residuals.
4. Independent check: coordinates-table and alignment-table values (not used in the fit)
   should land on linework vertices.
Writes spike/out/georef.json.
"""
import itertools
import json
import re
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
OUT = Path(__file__).parent / "out"
NUM = re.compile(r"^(\d),(\d{3}),(\d{3})\.(\d{2})$")


def number(text):
    m = NUM.match(text.replace(" ", ""))
    return float("".join(m.groups()[:3]) + "." + m[4]) if m else None


def frame(b):
    t = np.radians(b["angle"])
    return np.array([b["cx"], b["cy"]]), np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])


def callouts(blocks, skip):
    """N block with the E block on the next text line below it, outside the tables."""
    nums = [(b, number(b["text"])) for b in blocks]
    nums = [(b, v) for b, v in nums if v and not any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in skip)]
    Ns = [(b, v) for b, v in nums if 2.0e6 < v < 2.3e6]
    Es = [(b, v) for b, v in nums if 5.9e6 < v < 6.1e6]
    out = []
    for nb, nv in Ns:
        c, u, n = frame(nb)
        best = None
        for eb, ev in Es:
            d = np.array([eb["cx"], eb["cy"]]) - c
            al, pe = abs(d @ u), abs(d @ n)
            if al < 0.5 * nb["w"] and 1.0 * nb["glyph_h"] < pe < 3.2 * nb["glyph_h"] and (best is None or pe < best[2]):
                best = (eb, ev, pe)
        if best:
            out.append({"N": nv, "E": best[1], "nb": nb, "eb": best[0]})
    return out


def segments(page):
    segs = []
    circles = []
    for pid, d in enumerate(page.get_drawings()):
        r = d["rect"]
        kinds = {i[0] for i in d["items"]}
        if "c" in kinds and 2 < r.width < 9 and abs(r.width - r.height) < 1:
            circles.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        for it in d["items"]:
            if it[0] == "l":
                a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
                if np.hypot(*(a - b)) > 3:
                    segs.append((a, b, round(d.get("width") or 0, 2), pid))
    return segs, np.array(circles)


def trace_leader(co, segs, ends_tree, ends_idx):
    """Separator line between the N and E rows, then follow connected same-weight segments away from the label."""
    nb, eb = co["nb"], co["eb"]
    c, u, n = frame(nb)
    mid = (np.array([nb["cx"], nb["cy"]]) + np.array([eb["cx"], eb["cy"]])) / 2
    off = (mid - c) @ n
    sep = None
    for k, (a, b, w, pid) in enumerate(segs):
        da, db = a - c, b - c
        if abs(da @ n - off) < 0.35 * nb["glyph_h"] and abs(db @ n - off) < 0.35 * nb["glyph_h"]:
            lo, hi = sorted((da @ u, db @ u))
            if lo < nb["w"] / 2 and hi > -nb["w"] / 2 and hi - lo > 0.5 * nb["w"]:
                sep = k
                break
    if sep is None:
        return None
    a, b, w, _ = segs[sep]
    best = None
    for start, prev in ((a, b), (b, a)):
        cur, used, path = start, {sep}, [prev, start]
        for _ in range(4):
            hits = [ends_idx[j] for j in ends_tree.query_ball_point(cur, 0.8)]
            nxt = [(k, e) for k, e in hits if k not in used and abs(segs[k][2] - w) < 0.05]
            if len(nxt) != 1:  # dead end (the labelled point) or a junction with linework
                break
            k, e = nxt[0]
            used.add(k)
            cur = segs[k][1] if e == 0 else segs[k][0]
            path.append(cur)
        reach = np.hypot(*(cur - mid))
        if len(path) > 2 and (best is None or reach > best[0]):
            best = (reach, cur)
    return None if best is None else best[1]


def similarity(src, dst):
    """Least-squares x' = a*x - b*y + tx ; y' = b*x + a*y + ty. Sheet y is down, so flip it first."""
    A = np.zeros((2 * len(src), 4)); L = dst.reshape(-1)
    A[0::2] = np.c_[src[:, 0], -src[:, 1], np.ones(len(src)), np.zeros(len(src))]
    A[1::2] = np.c_[src[:, 1], src[:, 0], np.zeros(len(src)), np.ones(len(src))]
    return np.linalg.lstsq(A, L, rcond=None)[0]


def apply(p, xy):
    a, b, tx, ty = p
    xy = np.atleast_2d(xy)
    return np.c_[a * xy[:, 0] - b * xy[:, 1] + tx, b * xy[:, 0] + a * xy[:, 1] + ty]


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from gt import TABLES
    page = pymupdf.open(PDF)[0]
    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    cos = callouts(blocks, [t[0] for t in TABLES.values()])
    segs, circles = segments(page)
    ends = np.array([p for a, b, _, _ in segs for p in (a, b)])
    ends_idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    tree = cKDTree(ends)
    ctree = cKDTree(circles)

    ctrl = []
    for co in cos:
        tip = trace_leader(co, segs, tree, ends_idx)
        if tip is None:
            continue
        d, j = ctree.query(tip)
        snapped = d < 5
        pt = circles[j] if snapped else tip
        ctrl.append({"N": co["N"], "E": co["E"], "sx": float(pt[0]), "sy": float(-pt[1]), "snapped": bool(snapped)})
    print(f"callouts paired {len(cos)} | leaders traced {len(ctrl)} | snapped to point symbol {sum(c['snapped'] for c in ctrl)}")

    src = np.array([[c["sx"], c["sy"]] for c in ctrl]); dst = np.array([[c["E"], c["N"]] for c in ctrl])
    # ponytail: exhaustive 2-point consensus, fine for ~20 control points
    best = (0, None)
    for i, j in itertools.combinations(range(len(ctrl)), 2):
        p = similarity(src[[i, j]], dst[[i, j]])
        inl = np.hypot(*(apply(p, src) - dst).T) < 3.0
        if inl.sum() > best[0]:
            best = (inl.sum(), inl)
    inl = best[1]
    p = similarity(src[inl], dst[inl])
    res = np.hypot(*(apply(p, src) - dst).T)
    scale, rot = float(np.hypot(p[0], p[1])), float(np.degrees(np.arctan2(p[1], p[0])))
    print(f"fit on {inl.sum()}/{len(ctrl)} control points | scale {scale:.5f} ft/pt (plot scale 1in=100ft -> {100 / 72:.5f}) | rotation {rot:.4f} deg")
    print(f"residuals ft (inliers): rms {np.sqrt((res[inl] ** 2).mean()):.2f}  max {res[inl].max():.2f}")
    for c, r, ok in zip(ctrl, res, inl):
        print(f"  N {c['N']:>12,.2f}  E {c['E']:>12,.2f}  residual {r:8.2f} ft {'' if ok else ' <- rejected'}{'' if c['snapped'] else ' (unsnapped)'}")

    # independent check: table coordinates were not used above
    verts = cKDTree(np.array([[q[0], -q[1]] for a, b, _, _ in segs for q in (a, b)] + [[x, -y] for x, y in circles]))
    a, b, tx, ty = p
    inv = lambda EN: np.linalg.solve(np.array([[a, -b], [b, a]]), (np.atleast_2d(EN) - [tx, ty]).T).T
    print("independent check: table coordinates -> distance to nearest linework vertex")
    chk = []
    for tname in ("coordinates", "alignment"):
        vals = [number(v) for v in TABLES[tname][1]]
        vals = [v for v in vals if v]
        for N, E in zip(vals[0::2], vals[1::2]):
            d, _ = verts.query(inv([E, N])[0])
            chk.append(d * scale)
            print(f"  {tname:11} N {N:,.2f} E {E:,.2f} -> {d * scale:6.2f} ft")
    print(f"  median {np.median(chk):.2f} ft, max {max(chk):.2f} ft over {len(chk)} points")

    (OUT / "georef.json").write_text(json.dumps({
        "crs": "EPSG:2227", "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy = -pdf_y; units US survey ft, epoch 1991.35",
        "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot,
        "rms_ft": float(np.sqrt((res[inl] ** 2).mean())), "control": [dict(c, residual_ft=float(r), used=bool(k)) for c, r, k in zip(ctrl, res, inl)]}, indent=1))
    assert inl.sum() >= 4 and abs(scale - 100 / 72) / (100 / 72) < 0.01, "fit is not credible"


if __name__ == "__main__":
    main()
