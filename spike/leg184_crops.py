"""Loop18 leg 4 gate evidence: crop every curve edge that NEWLY completes its chord direction via the
radial source once the centre test (RADIAL_CENTER_TOL_FT) is wired in and checks.py's nearest_arc_end
widens the radial-to-curve pairing -- i.e. curves absent from the loop18-3b baseline's own
complete_curve_chords() fill but present now. Same 2-tile crop style as legE_crops.py (curve in green,
its radial donor in blue), but this script passes the REAL ground() transform into
complete_curve_chords() (legE_crops.py's own build_graph() does not -- it predates the centre test and
would silently skip it, showing tangent-only-passing curves the real pipeline now refuses).
usage: SHEET=<pdf> python spike/leg184_crops.py <curve_src> [<curve_src> ...]
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, DEFAULT  # noqa: E402
from leg4_crops import tile  # noqa: E402
import traverse as tv  # noqa: E402
from recon import OUT_RECON  # noqa: E402


def build_graph():
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]

    def ground(p):
        sx, sy = p[0], -p[1]
        return np.array([a * sx - b * sy + tx, b * sx + a * sy + ty])

    def azimuth(p, q):
        d = ground(q) - ground(p)
        return math.degrees(math.atan2(d[0], d[1])) % 360

    edges = tv.build_edges()
    scale = g["scale_ft_per_pt"]
    for e in edges:
        e["impossible"] = bool(e["kind"] == "arc" and "L" in e
                                and e["L"] < float(np.hypot(*(e["p1"] - e["p0"]))) * scale * 0.98)

    ends = np.array([p for e in edges for p in (e["p0"], e["p1"])])
    possible = np.array([not edges[i // 2]["impossible"] for i in range(len(ends))])
    good_idx = np.nonzero(possible)[0]
    tree = cKDTree(ends[good_idx]) if len(good_idx) else None
    node_of = {}
    for gi, i in enumerate(good_idx):
        i = int(i)
        if i in node_of:
            continue
        for gj in tree.query_ball_point(ends[i], tv.NODE):
            node_of.setdefault(int(good_idx[gj]), i)
    for i in np.nonzero(~possible)[0]:
        node_of[int(i)] = int(i)

    adj = {}
    for k, e in enumerate(edges):
        n0, n1 = node_of[2 * k], node_of[2 * k + 1]
        e["n0"], e["n1"] = n0, n1
        adj.setdefault(n0, []).append(k); adj.setdefault(n1, []).append(k)
    gh = tv.sheet_glyph_h()
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

    tv.inherit_bearings(edges, adj)
    tv.share_curve_radius(edges, scale)
    tv.complete_curve_chords(edges, adj, azimuth, tv.load_radials(), ground)
    return edges


def curve_region(e):
    xs = [p[0] for p in e["pts"]]; ys = [p[1] for p in e["pts"]]
    return [min(xs), min(ys), max(xs), max(ys)]


def caption_tile(page, region, line, label, color=(220, 0, 0)):
    im = tile(page, region, line)
    im = cv2.copyMakeBorder(im, 24, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label[:80], (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def safe(s):
    return "".join(c if c.isalnum() else "_" for c in s)[:24]


def main():
    page = pymupdf.open(PDF)[0]
    sheet_name = "presidio" if PDF == DEFAULT else PDF.stem
    wanted = set(sys.argv[1:])
    edges = build_graph()
    done = [e for e in edges if e["kind"] == "arc" and e.get("chord_source", "").startswith("radial") and (not wanted or e["src"] in wanted)]
    print(f"{sheet_name}: {len(done)} radial-sourced curve edge(s): " + ", ".join(f"{e['src']} ({e['chord_source']})" for e in done))
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    for e in done:
        curve_reg = curve_region(e)
        curve_line = [list(p) for p in e["pts"]]
        t0 = caption_tile(page, curve_reg, curve_line, f"{e['src']}  R={e.get('R')} delta={e.get('delta')} az={e.get('az'):.2f}", (0, 150, 0))
        m = e["chord_source_edge"]
        donor_reg = m.get("region") or [min(m["p0"][0], m["p1"][0]), min(m["p0"][1], m["p1"][1]), max(m["p0"][0], m["p1"][0]), max(m["p0"][1], m["p1"][1])]
        donor_line = [list(m["p0"]), list(m["p1"])]
        t1 = caption_tile(page, donor_reg, donor_line, f"source: {e['chord_source']}", (220, 0, 0))
        H = max(t0.shape[0], t1.shape[0])
        t0 = cv2.copyMakeBorder(t0, 0, H - t0.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        t1 = cv2.copyMakeBorder(t1, 0, H - t1.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        grid = np.hstack([t0, t1])
        out_name = f"l18_4_{sheet_name}_{safe(e['src'])}.png"
        cv2.imwrite(str(OUT_RECON / out_name), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
        print(f"wrote {OUT_RECON / out_name} ({grid.shape[1]}x{grid.shape[0]})")


if __name__ == "__main__":
    main()
