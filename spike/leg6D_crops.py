"""Leg 6D evidence crop for R-10434.1's lost traverse closure: no chain closes with a real misfit even
after traverse.py's fixes (impossible-arc drop, glyph-height loose-end snap), so this renders the two
regions diffing shows loop2 leg C actually moved -- the '31.80'' arc that now matches a 308 ft run
instead of its own 31.80 ft piece (dropped by the new impossible-match filter), and the '14.91'' arc /
'8.12'' line pair near a tight curve that no longer share a vertex. Traverse edges in blue, the
misfit/flag text for each culprit in red.
usage: python spike/leg6D_crops.py   (SHEET=Sample Data/d4/r_10434_001_2020-09-16.pdf)
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
import traverse as T  # noqa: E402

Z = 300 / 72
PAD = 90


def tile(page, edges, label_lines):
    xs = [p[0] for e in edges for p in (e["p0"], e["p1"])]
    ys = [p[1] for e in edges for p in (e["p0"], e["p1"])]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 1100 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for e in edges:
        cv2.polylines(im, [np.array([f(*p) for p in e["pts"]], np.int32)], False, (220, 90, 0), 3)
        cv2.circle(im, f(*e["p0"]), 6, (0, 0, 220), -1)
        cv2.circle(im, f(*e["p1"]), 6, (0, 0, 220), -1)
    y = 24
    for line in label_lines:
        cv2.putText(im, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 220), 2, cv2.LINE_AA)
        y += 24
    return im


def main():
    page = pymupdf.open(PDF)[0]
    edges = T.build_edges()
    scale = json.loads((OUT / "georef.json").read_text())["scale_ft_per_pt"]
    by_src = {}
    for e in edges:
        by_src.setdefault(e["src"], []).append(e)

    panels = []
    node29 = [e for name in ("31.80'", "L=170.24'", "L6 + L8", "L=16.95' + L=23.48'") for e in by_src.get(name, [])]
    if node29:
        chord = float(np.hypot(*(by_src["31.80'"][0]["p1"] - by_src["31.80'"][0]["p0"]))) * scale
        panels.append(tile(page, node29, [
            "node 29: '31.80'' matches a 308 ft run (record 31.80 ft) -- impossible, dropped",
            f"drawn chord {chord:.0f} ft vs record 31.80 ft",
            "L=170.24' / L6+L8 / L=16.95'+L=23.48' -- the real edges at this vertex",
        ]))
    pair = by_src.get("14.91'", []) + by_src.get("8.12'", [])
    arc1491 = [e for e in pair if e["kind"] == "arc"]
    if arc1491:
        chord = float(np.hypot(*(arc1491[0]["p1"] - arc1491[0]["p0"]))) * scale
        panels.append(tile(page, pair, [
            "'14.91'' arc / '8.12'' line: moved by the same split_at change",
            f"arc drawn chord {chord:.1f} ft vs record 14.91 ft -- impossible, dropped",
            "no closed chain results: gate reports closed=0, see report",
        ]))

    H = max(t.shape[0] for t in panels)
    panels = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in panels]
    out = np.hstack(panels)
    dest = OUT / "leg6D_chain.png"
    cv2.imwrite(str(dest), out)
    print("wrote", dest, out.shape)


if __name__ == "__main__":
    main()
