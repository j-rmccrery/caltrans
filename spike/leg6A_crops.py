"""Loop6 legA evidence: the 12 largest-printed-L standalone L=/(T) MISS labels (loop5 legB's MISS class,
25 items south-wide, none resolved by legB), 4 per south sheet. Red box = the label; blue = every curved
piece in checks.build_pool's own arc pool within 8 glyph heights of the label, each tagged with its own
drawn length (ft) so the crop shows exactly what candidate the checker could see.
usage: SHEET=<pdf> python spike/leg6A_crops.py <out_dir_for_tiles>
  -> writes <out_dir>/<sheet>_<n>.png per target (one tile each) and prints, per target, every pool piece
     found within 8 glyph heights (length ft, distance from label centre pt).
A separate stitch step (run after all three sheets) combines the tiles into spike/out/leg6A_missing.png.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402
import checks  # noqa: E402

Z = 300 / 72
PAD = 130

# (printed text, region) for the 4 largest MISS labels on this sheet, taken directly from the current
# exceptions.json (kind=="arc length", text startswith "L=", issue = MISS -- see leg6A_missing.md)
TARGETS = {
    "r_10434_002_2020-09-16.pdf": [  # presidio
        ("L=573.93'(T)", [1556, 609, 1618, 625]),
        ("L=289.24'", [283, 422, 339, 444]),
        ("L=232.07'(T)", [1731, 649, 1790, 664]),
        ("L=206.36'", [1893, 594, 1939, 609]),
    ],
    "r_10434_001_2020-09-16.pdf": [
        ("L=1334.12'", [1481, 740, 1527, 755]),
        ("L=869.14'", [1837, 332, 1881, 347]),
        ("L=869.14'#2", [1153, 485, 1198, 500]),
        ("L=357.21'", [1828, 229, 1874, 244]),
    ],
    "r_10434_003_2020-09-16.pdf": [
        ("L=757.83'", [2213, 991, 2259, 1005]),
        ("L=577.57'", [597, 628, 647, 643]),
        ("L=537.96'", [2143, 875, 2201, 898]),
        ("L=406.62'", [1372, 680, 1413, 693]),
    ],
}


def tile(page, region, pool_pieces, label_text, out_path):
    xs = [region[0], region[2]] + [p[0] for pc in pool_pieces for p in pc["pts"]]
    ys = [region[1], region[3]] + [p[1] for pc in pool_pieces for p in pc["pts"]]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 1100 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for pc in pool_pieces:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pc["pts"]], np.int32)], False, (0, 90, 220), 3)
        mx, my = pc["pts"][len(pc["pts"]) // 2]
        cv2.putText(im, f"{pc['ft']:.2f}'", f(mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 90, 220), 2, cv2.LINE_AA)
    cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (220, 0, 0), 3)
    im = cv2.copyMakeBorder(im, 0, 30, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label_text, (10, im.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    checks.set_decimals(blocks)
    gh = float(np.median([b["glyph_h"] for b in blocks])) if blocks else 6.0
    pool = checks.build_pool(page, blocks)
    arcs = pool["arcs"]
    targets = TARGETS.get(PDF.name)
    if not targets:
        print(f"no targets for {PDF.name}, skipping"); return
    for i, (text, region) in enumerate(targets):
        c = np.array([(region[0] + region[2]) / 2, (region[1] + region[3]) / 2])
        near = [x for x in arcs if checks.poly_dist(c, x["pts"]) < 8.0 * gh]
        pieces = [{"pts": x["pts"], "ft": x["len_pt"] * scale} for x in near]
        out_path = out_dir / f"{PDF.stem}_{i}.png"
        tile(page, region, pieces, f"{PDF.stem}: {text}", out_path)
        print(f"{PDF.stem} {text}: {len(pieces)} pool pieces within 8gh -> " +
              ", ".join(f"{p['ft']:.2f}'" for p in sorted(pieces, key=lambda p: -p['ft'])[:8]))


if __name__ == "__main__":
    main()
