"""Loop17 leg A gate evidence: one crop per misfit-bucket row, before/after this leg's fixes.
Same render pattern as legD_recon_crops.py (page pixmap, drawn line in blue, label box in red),
plus an optional second (green/orange) record source when the row shares nodes with the record
value it was confused with (merge defect / wrong association).
usage: SHEET=<pdf> python spike/legA17_crops.py <out_stem> <edge_src_substring> [nb_src_substring]
  writes spike/out_recon/l17B_<out_stem>.png
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from traverse import build_edges  # noqa: E402

OUT_RECON = Path(__file__).parent / "out_recon"
PAD = 15


def region_of(e):
    if e.get("region"):
        return list(e["region"])
    lx = [e["p0"][0], e["p1"][0]]; ly = [e["p0"][1], e["p1"][1]]
    return [min(lx) - 6, min(ly) - 6, max(lx) + 6, max(ly) + 6]


def crop(page, boxes_lines, caption):
    """boxes_lines: list of (region, pts, color_line, color_box)."""
    xs, ys = [], []
    for reg, pts, *_ in boxes_lines:
        xs += [reg[0], reg[2]] + [p[0] for p in pts]
        ys += [reg[1], reg[3]] + [p[1] for p in pts]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(4.0, 900 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for reg, pts, cl, cb in boxes_lines:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pts], np.int32)], False, cl, 3)
        cv2.rectangle(im, f(reg[0], reg[1]), f(reg[2], reg[3]), cb, 2)
    im = cv2.copyMakeBorder(im, 44, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    for i, line in enumerate(caption.split("\n")):
        cv2.putText(im, line, (4, 17 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def main():
    out_stem, edge_sub = sys.argv[1], sys.argv[2]
    nb_sub = sys.argv[3] if len(sys.argv) > 3 else None
    caption = sys.argv[4] if len(sys.argv) > 4 else out_stem
    page = pymupdf.open(PDF)[0]
    edges = build_edges()
    hits = [e for e in edges if edge_sub in e["src"]]
    assert hits, f"no edge src contains {edge_sub!r}"
    e = hits[0]
    layers = [(region_of(e), [e["p0"], e["p1"]], (0, 90, 220), (220, 0, 0))]
    if nb_sub:
        nb_hits = [m for m in edges if nb_sub in m["src"] and m is not e]
        assert nb_hits, f"no edge src contains {nb_sub!r}"
        m = nb_hits[0]
        layers.append((region_of(m), [m["p0"], m["p1"]], (0, 170, 0), (0, 150, 255)))
    im = crop(page, layers, caption)
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    out_path = OUT_RECON / f"l17B_{out_stem}.png"
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
