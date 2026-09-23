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
import os
import re
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
PDF = Path(os.environ.get("SHEET", DEFAULT))  # SHEET=<pdf> runs another sheet; its outputs go to out/<stem>/
OUT = Path(__file__).parent / "out" / (PDF.stem if "SHEET" in os.environ else "")
# the sheet's reads: by glyph on a stroked sheet (read_glyphs.py), by OCR otherwise
_rg, _rr, _rt = OUT / "read_glyph.json", OUT / "read_rapid.json", OUT / "tables.json"
_validated = _rt.exists() and _rt.stat().st_size > 20  # an alphabet the tables' NO. column validated; the font-seed-only one is not
READS = _rg if _rg.exists() and _rg.stat().st_size > 2 and (_validated or not _rr.exists()) else _rr
NUM = re.compile(r"^([NEXY])?[:.]?(\d[\d,]{2,9}\.\d{2,4})$")  # 4-8 integer digits: local grids, CCS27/83, ft or m


def number(text):
    """(axis letter or None, value) for a printed coordinate, else None."""
    m = NUM.match(text.replace(" ", "").upper())
    if not m or not 4 <= len(m[2].split(".")[0].replace(",", "")) <= 8:
        return None
    return {"N": "N", "Y": "N", "E": "E", "X": "E"}.get(m[1]), float(m[2].replace(",", ""))


def frame(b):
    t = np.radians(b["angle"])
    return np.array([b["cx"], b["cy"]]), np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])


def real_text_blocks(page):
    """Selectable PDF text as blocks shaped like the stroke-derived ones. Newer sheets carry real text.
    Box and angle come from the character boxes themselves, so rotated lines measure correctly."""
    out = []
    for blk in page.get_text("rawdict")["blocks"]:
        for ln in blk.get("lines", []):
            chars = [ch for sp in ln["spans"] for ch in sp["chars"] if ch["c"].strip()]
            text = "".join(ch["c"] for sp in ln["spans"] for ch in sp["chars"]).strip()
            if not chars or not text:
                continue
            dx, dy = ln["dir"]
            u, n = np.array([dx, dy]), np.array([-dy, dx])
            cs = np.array([[(ch["bbox"][0] + ch["bbox"][2]) / 2, (ch["bbox"][1] + ch["bbox"][3]) / 2] for ch in chars])
            size = float(np.median([sp["size"] for sp in ln["spans"]]))
            al, pe = cs @ u, cs @ n
            c = u * (al.max() + al.min()) / 2 + n * pe.mean()
            out.append({"cx": float(c[0]), "cy": float(c[1]), "w": float(al.max() - al.min() + 0.6 * size), "h": float(0.75 * size),
                        "angle": float(np.degrees(np.arctan2(dy, dx))), "glyphs": len(chars), "glyph_h": float(0.7 * size),
                        "text": text, "conf": 1.0, "real": True})
    return out


def callouts(blocks, skip):
    """Stacked coordinate pairs outside the tables: a value with a second value on the next text line.
    Which one is the northing comes from the N/E letter, else from the rule that in every California
    state plane zone and unit the easting is the larger number. Pairs inside a multi-line note
    (monument descriptions) are taken from the note's own lines."""
    out = []
    nums = []
    for b in blocks:
        if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in skip):
            continue
        parts = [number(t) for t in b["text"].split("|")]
        vals = [v for v in parts if v]
        if len(vals) >= 2 and "|" in b["text"]:  # monument note: both coordinates inside one block
            (a1, v1), (a2, v2) = vals[:2]
            N, E = ((v1, v2) if (a1 == "N" or a2 == "E" or (a1 is None and a2 is None and v1 < v2)) else (v2, v1))
            out.append({"N": N, "E": E, "nb": b, "eb": b, "note": True})
        elif len(parts) == 1 and parts[0]:
            nums.append((b, *parts[0]))
    for nb, na, nv in nums:
        c, u, n = frame(nb)
        best = None
        for eb, ea, ev in nums:
            if eb is nb:
                continue
            d = np.array([eb["cx"], eb["cy"]]) - c
            al, pe = abs(d @ u), d @ n
            row = max(3.2 * nb["glyph_h"], 2.2 * max(nb["h"], eb["h"]))  # row pitch scales with the box, not just the glyph
            if al < 0.6 * max(nb["w"], eb["w"]) and 1.0 * nb["glyph_h"] < pe < row and (best is None or pe < best[3]):
                best = (eb, ea, ev, pe)
        if not best:
            continue
        eb, ea, ev, _ = best
        short = max(nv, ev) < 1e5  # local-grid values: only trust a pair that carries an N or E letter
        if short and na is None and ea is None:
            continue
        is_n = na == "N" or ea == "E" or (na is None and ea is None and nv < ev)
        if na == "E" or ea == "N" or (na is None and ea is None and nv > ev):
            is_n = False
        if is_n:
            out.append({"N": nv, "E": ev, "nb": nb, "eb": eb})
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
        # no underline between the rows: the leader starts at the edge of the text itself
        gh = nb["glyph_h"]
        half_w = max(nb["w"], eb["w"]) / 2
        for k, (a, b, w, pid) in enumerate(segs):
            for p0, p1 in ((a, b), (b, a)):
                d0, d1 = p0 - mid, p1 - mid
                bu, bn = half_w + 6.0 * gh, 2.5 * gh  # the text box plus room for the "N " prefix block
                inside = abs(d0 @ u) < bu and abs(d0 @ n) < bn
                far = abs(d1 @ u) > bu or abs(d1 @ n) > bn  # a glyph stroke stays inside; a leader leaves
                edge = max(abs(d0 @ u) / bu, abs(d0 @ n) / bn)  # 1.0 = starts right at the box edge
                if inside and far and np.hypot(*(p1 - p0)) > 2.0 * gh and (sep is None or edge > sep[1]):
                    sep = (k, edge)
        if sep is None:
            return None
        sep = sep[0]
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
            best = (reach, path[2:])
    # every vertex along the leader is a candidate: where the leader meets a dash-dot centreline the
    # chain runs one dash past the labelled point, so the last vertex is not always the right one
    return None if best is None else best[1]


def monument_symbols(page):
    """Centroids of small closed triangles (NGS / found-monument symbols)."""
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if not (3 < max(r.width, r.height) < 14):
            continue
        pts = [it[1] for it in d["items"] if it[0] == "l"] + [it[2] for it in d["items"] if it[0] == "l"]
        if len(d["items"]) in (3, 4) and all(it[0] == "l" for it in d["items"]):
            first, last = d["items"][0][1], d["items"][-1][2]
            if abs(first.x - last.x) < 0.5 and abs(first.y - last.y) < 0.5 or d["closePath"]:
                out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    return out


def vs_caltrans_package(page, p):
    """Caltrans' own georeferencing of the same sheet (tif + tfw from the D4 index), if downloaded."""
    tfw = next(iter((PDF.parent / "pkg").glob(PDF.stem + ".tfw")), None)
    if not tfw:
        return
    import rasterio
    A, D, B, E, C, F = [float(v) for v in tfw.read_text().split()]
    with rasterio.open(tfw.with_suffix(".tif")) as r:
        k = r.width / page.rect.width
    a, b, tx, ty = p
    W, H = page.rect.width, page.rect.height
    d = []
    for px, py in itertools.product((0.2 * W, 0.5 * W, 0.8 * W), (0.2 * H, 0.5 * H, 0.8 * H)):
        ours = np.array([a * px + b * py + tx, b * px - a * py + ty])
        col, row = px * k - 0.5, py * k - 0.5
        d.append(np.hypot(*(ours - [A * col + B * row + C, D * col + E * row + F])))
    print(f"vs Caltrans georeferenced package at 9 sheet points: median {np.median(d):.2f}, max {max(d):.2f} (sheet units)")


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
    blocks = json.loads((READS).read_text(encoding="utf-8"))
    real = real_text_blocks(page)
    blocks = [b for b in blocks if not any(abs(b["cx"] - r["cx"]) < 8 and abs(b["cy"] - r["cy"]) < 8 for r in real)] + real
    cos = callouts(blocks, [t[0] for t in TABLES.values()] if PDF == DEFAULT else [])
    print(f"real-text lines {len(real)} | stroke blocks {len(blocks) - len(real)}")
    segs, circles = segments(page)
    ends = np.array([p for a, b, _, _ in segs for p in (a, b)])
    ends_idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    tree = cKDTree(ends)
    ctree = cKDTree(circles)

    symbols = np.array(monument_symbols(page)) if cos else np.zeros((0, 2))
    ctrl = []
    for co in cos:
        cands = []
        if co.get("note"):
            # monument note: the symbol sits at a corner of the note, and a leader may run from it
            b = co["nb"]
            near = [q for q in symbols if abs(q[0] - b["cx"]) < b["w"] * 0.9 + 15 and abs(q[1] - b["cy"]) < b["h"] * 0.9 + 15]
            for q in near:
                cands.append((float(q[0]), float(-q[1]), True))
                for k in tree.query_ball_point(q, 6):
                    seg = segs[ends_idx[k][0]]
                    far = seg[1] if ends_idx[k][1] == 0 else seg[0]
                    cands.append((float(far[0]), float(-far[1]), False))
            for tip in trace_leader(co, segs, tree, ends_idx) or []:  # some notes have a plain leader too
                d, j = ctree.query(tip)
                pt = circles[j] if d < 5 else tip
                cands.append((float(pt[0]), float(-pt[1]), bool(d < 5)))
        else:
            tips = trace_leader(co, segs, tree, ends_idx)
            for tip in tips or []:
                d, j = ctree.query(tip)
                pt = circles[j] if d < 5 else tip
                cands.append((float(pt[0]), float(-pt[1]), bool(d < 5)))
        if cands:
            ctrl.append({"N": co["N"], "E": co["E"], "cands": cands})
    print(f"callouts paired {len(cos)} ({sum(1 for c in cos if c.get('note'))} in monument notes) | with a candidate point {len(ctrl)}")
    if len(ctrl) < 2:
        raise SystemExit("georef: fewer than 2 usable control points on this sheet")

    dst = np.array([[c["E"], c["N"]] for c in ctrl])
    C = [np.array([k[:2] for k in c["cands"]]) for c in ctrl]

    def score(p):  # per callout: its best candidate under this hypothesis
        r = [np.hypot(*(apply(p, c) - d).T) for c, d in zip(C, dst)]
        return np.array([x.min() for x in r]), [int(x.argmin()) for x in r]

    # ponytail: exhaustive 2-point consensus over candidate choices, fine for ~20 control points
    best = (0, 1e9, None)
    for i, j in itertools.combinations(range(len(ctrl)), 2):
        for ci, cj in itertools.product(C[i], C[j]):
            if np.hypot(*(ci - cj)) < 20:
                continue
            p = similarity(np.array([ci, cj]), dst[[i, j]])
            r, _ = score(p)
            key = ((r < 1.0).sum(), -r[r < 1.0].sum())
            if key > best[:2]:
                best = (*key, p)
    res, pick = score(best[2])
    inl = res < 1.0
    src = np.array([c[k] for c, k in zip(C, pick)])
    p = similarity(src[inl], dst[inl])
    res = np.hypot(*(apply(p, src) - dst).T)
    for c, k, xy in zip(ctrl, pick, src):
        c.update(sx=float(xy[0]), sy=float(xy[1]), snapped=c["cands"][k][2], vertex=f"{k + 1} of {len(c['cands'])}")
        del c["cands"]
    scale, rot = float(np.hypot(p[0], p[1])), float(np.degrees(np.arctan2(p[1], p[0])))
    print(f"fit on {inl.sum()}/{len(ctrl)} control points | scale {scale:.5f} ft/pt (plot scale 1in=100ft -> {100 / 72:.5f}) | rotation {rot:.4f} deg")
    print(f"residuals ft (inliers): rms {np.sqrt((res[inl] ** 2).mean()):.2f}  max {res[inl].max():.2f}")
    for c, r, ok in zip(ctrl, res, inl):
        print(f"  N {c['N']:>12,.2f}  E {c['E']:>12,.2f}  residual {r:8.2f} ft {'' if ok else ' <- rejected'}{'' if c['snapped'] else ' (unsnapped)'} [leader vertex {c['vertex']}]")

    # independent check: table coordinates were not used above
    verts = cKDTree(np.array([[q[0], -q[1]] for a, b, _, _ in segs for q in (a, b)] + [[x, -y] for x, y in circles]))
    a, b, tx, ty = p
    inv = lambda EN: np.linalg.solve(np.array([[a, -b], [b, a]]), (np.atleast_2d(EN) - [tx, ty]).T).T
    print("independent check: table coordinates -> distance to nearest linework vertex")
    chk = []
    for tname in (("coordinates", "alignment") if PDF == DEFAULT else ()):  # keyed truth exists for this sheet only
        vals = [number(v) for v in TABLES[tname][1]]
        vals = [v[1] for v in vals if v]
        for N, E in zip(vals[0::2], vals[1::2]):
            d, _ = verts.query(inv([E, N])[0])
            chk.append(d * scale)
            print(f"  {tname:11} N {N:,.2f} E {E:,.2f} -> {d * scale:6.2f} ft")
    if chk:
        print(f"  median {np.median(chk):.2f} ft, max {max(chk):.2f} ft over {len(chk)} points")

    vs_caltrans_package(page, p)
    (OUT / "georef.json").write_text(json.dumps({
        "crs": "EPSG:2227", "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy = -pdf_y; units US survey ft, epoch 1991.35",
        "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot,
        "rms_ft": float(np.sqrt((res[inl] ** 2).mean())), "control": [dict(c, residual_ft=float(r), used=bool(k)) for c, r, k in zip(ctrl, res, inl)]}, indent=1))
    std = min(abs(scale - k / 72) / (k / 72) for k in (10, 20, 30, 40, 50, 60, 80, 100, 200, 400))  # ft or m per inch
    credible = inl.sum() >= 4 or (inl.sum() >= 3 and std < 0.005)
    print("credible" if credible else "NOT credible: too few agreeing control points for an unverified fit")
    assert credible, "fit is not credible"


if __name__ == "__main__":
    main()
