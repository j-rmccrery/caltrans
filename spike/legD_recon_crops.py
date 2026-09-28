"""Loop16 leg D gate evidence: crops of edges that completed a half-recorded course by collinear
inheritance (traverse.inherit_bearings) -- this edge's own printed distance (red box, blue drawn
line) plus the record source it borrowed a bearing from (orange box, green drawn line), so the
orchestrator can see the record value on the sheet, not just in traverse.json.
Rebuilds the exact same edge/node graph traverse.main() does (build_edges + node clustering +
inherit_bearings), so the geometry matched here is provably the same pairing traverse.py used --
no separate fuzzy text lookup that could pick the wrong same-named label.
usage: [SHEET=<pdf>] python spike/legD_recon_crops.py [--max N]
  writes spike/out_recon/legD_<sheet>_<n>.png, one crop per completed edge on this sheet (misfit
  <= 0.5 ft ones first -- the ones recon.py actually credits).
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from scipy.spatial import cKDTree

import json

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from traverse import build_edges, inherit_bearings, sheet_glyph_h, NODE  # noqa: E402

OUT_RECON = Path(__file__).parent / "out_recon"
PAD = 15


def node_graph(edges):
    """Same node-clustering + loose-end snap as traverse.main(), duplicated read-only here (crop
    evidence only -- traverse.py itself is the gated pipeline, left untouched)."""
    ends = np.array([p for e in edges for p in (e["p0"], e["p1"])])
    possible = np.array([not edges[i // 2].get("impossible") for i in range(len(ends))])
    good_idx = np.nonzero(possible)[0]
    tree = cKDTree(ends[good_idx]) if len(good_idx) else None
    node_of = {}
    for i in good_idx:
        i = int(i)
        if i in node_of:
            continue
        for gj in tree.query_ball_point(ends[i], NODE):
            node_of.setdefault(int(good_idx[gj]), i)
    for i in np.nonzero(~possible)[0]:
        node_of[int(i)] = int(i)
    adj = {}
    for k, e in enumerate(edges):
        n0, n1 = node_of[2 * k], node_of[2 * k + 1]
        e["n0"], e["n1"] = n0, n1
        adj.setdefault(n0, []).append(k); adj.setdefault(n1, []).append(k)
    gh = sheet_glyph_h()
    impossible_nodes = {node_of[int(i)] for i in np.nonzero(~possible)[0]}
    loose = [n for n in adj if len(adj[n]) == 1 and n not in impossible_nodes]
    if loose:
        loose_pts = ends[loose]
        ltree = cKDTree(loose_pts)
        paired = set()
        cand = sorted(ltree.query_pairs(gh), key=lambda p: np.hypot(*(loose_pts[p[0]] - loose_pts[p[1]])))
        for i, j in cand:
            ni, nj = loose[i], loose[j]
            if ni in paired or nj in paired or ni == nj:
                continue
            paired.add(ni); paired.add(nj)
            lo, hi = min(ni, nj), max(ni, nj)
            for e in edges:
                if e["n0"] == hi:
                    e["n0"] = lo
                if e["n1"] == hi:
                    e["n1"] = lo
            adj[lo] = adj.pop(lo) + adj.pop(hi)
    return adj


def crop(page, reg_this, line_this, reg_nb, line_nb, caption):
    pts = list(line_this) + list(line_nb)
    x0 = min(reg_this[0], reg_nb[0], *(p[0] for p in pts)) - PAD
    y0 = min(reg_this[1], reg_nb[1], *(p[1] for p in pts)) - PAD
    x1 = max(reg_this[2], reg_nb[2], *(p[0] for p in pts)) + PAD
    y1 = max(reg_this[3], reg_nb[3], *(p[1] for p in pts)) + PAD
    R = pymupdf.Rect(x0, y0, x1, y1) & page.rect
    z = min(4.0, 700 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    cv2.polylines(im, [np.array([f(x, y) for x, y in line_nb], np.int32)], False, (0, 170, 0), 3)     # record source's own drawn line: green
    cv2.polylines(im, [np.array([f(x, y) for x, y in line_this], np.int32)], False, (0, 90, 220), 3)   # completed edge's drawn line: blue
    cv2.rectangle(im, f(reg_nb[0], reg_nb[1]), f(reg_nb[2], reg_nb[3]), (0, 150, 255), 2)     # record source label box: orange
    cv2.rectangle(im, f(reg_this[0], reg_this[1]), f(reg_this[2], reg_this[3]), (220, 0, 0), 2)  # completed edge's own label box: red
    im = cv2.copyMakeBorder(im, 28, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, caption, (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def region_of(e):
    """e['region'] when this edge came straight from a labels.json block; else a small box round
    its own drawn line (a tag_labels.json edge, e.g. an L# tag beside its leader)."""
    if e.get("region"):
        return list(e["region"])
    lx, ly = zip(*[(p[0], p[1]) for p in (e["p0"], e["p1"])])
    return [min(lx) - 6, min(ly) - 6, max(lx) + 6, max(ly) + 6]


def main():
    max_n = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 99
    page = pymupdf.open(PDF)[0]
    edges = build_edges()
    # same "impossible" arc-chord filter as traverse.main(), so this script's node graph -- and
    # therefore which edges land adjacent to which -- matches traverse.py's own exactly
    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    scale = g["scale_ft_per_pt"]
    for e in edges:
        e["impossible"] = bool(e["kind"] == "arc" and "L" in e
                                and e["L"] < float(np.hypot(*(e["p1"] - e["p0"]))) * scale * 0.98)
    adj = node_graph(edges)
    n = inherit_bearings(edges, adj)
    sheet = Path(PDF).stem if PDF else "presidio"
    inherited = [e for e in edges if "bearing_source" in e]
    print(f"{sheet}: {n} edge(s) inherited a bearing")
    written = []
    for i, e in enumerate(inherited[:max_n]):
        # loop16 leg D2 gate finding: two edges can share the same printed "src" text (e.g. two
        # separate "S2 deg 05'55"W" R/W lines) -- a name re-lookup can silently grab the wrong one.
        # inherit_bearings() now stores the exact donor OBJECT it used; use that directly, never a
        # name lookup, so the crop is provably the same pairing traverse.py made.
        m = e["bearing_source_edge"]
        nb_src = m["src"]
        cap = f"{sheet}: {e['src']} <- {nb_src} (az {e['az']:.3f} deg)"
        im = crop(page, region_of(e), [e["p0"], e["p1"]], region_of(m), [m["p0"], m["p1"]], cap)
        out_path = OUT_RECON / f"legD_{sheet}_{i}.png"
        OUT_RECON.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
        written.append(out_path)
        print(f"  wrote {out_path.name}: {e['src']!r} <- {nb_src!r}")
    return written


if __name__ == "__main__":
    main()
