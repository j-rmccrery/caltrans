"""Where the map is on this sheet, from the sheet itself: no Presidio constants.

map_area  = the box around the R/W-weight linework that is not the sheet border, the vertex circles
            (2-98 % range, so the legend's sample circle does not count) and the control points the
            georeferencing used, padded.
furniture = boxes to leave alone when reading tags on the drawing: dense upright text blocks (notes,
            legends, title block) and, once alphabet.py has run, the tables it found.

Writes spike/out[/<sheet>]/frame.json; overlay.py serves MAP_AREA / FURNITURE from it when present.
usage: [SHEET=<pdf>] python spike/frame.py   (after blocks.py)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT, PDF  # noqa: E402
from checks import linework_segments  # noqa: E402
from georef import segments  # noqa: E402

PAD = 60


def main():
    page = pymupdf.open(PDF)[0]
    W, H = page.rect.width, page.rect.height
    segs = linework_segments(page, 0.2)
    # R/W-weight lines (1.9-2.1 pt, not the border) and the vertex circles; the legend's sample circle and a
    # stray heavy stroke in the title block must not drag the box, so circles enter by their 2-98 % range
    P = np.array([q for a, b, w, _ in segs if 1.9 <= w <= 2.1 and np.hypot(*(b - a)) < 0.8 * max(W, H) for q in (a, b)]).reshape(-1, 2)
    _, circles = segments(page)
    if len(circles) >= 5:
        C = np.asarray(circles)
        P = np.vstack([P, np.percentile(C, 2, axis=0)[None], np.percentile(C, 98, axis=0)[None]])
    if (OUT / "georef.json").exists():  # the control points the fit used: they are on the map by definition
        ctl = [[c["sx"], -c["sy"]] for c in json.loads((OUT / "georef.json").read_text()).get("control", []) if c.get("used")]
        if ctl:
            P = np.vstack([P, np.array(ctl)])
    if not len(P):
        P = np.array([[0.1 * W, 0.1 * H], [0.9 * W, 0.9 * H]])  # nothing to go on: most of the page
    x0, y0 = P.min(0); x1, y1 = P.max(0)
    map_area = [round(max(x0 - PAD, 0)), round(max(y0 - PAD, 0)), round(min(x1 + PAD, W)), round(min(y1 + PAD, H))]
    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    furniture = [[round(b["cx"] - b["w"] / 2 - 6), round(b["cy"] - b["h"] / 2 - 6), round(b["cx"] + b["w"] / 2 + 6), round(b["cy"] + b["h"] / 2 + 6)]
                 for b in blocks if b["glyphs"] >= 30 and abs(b["angle"]) < 2]
    (OUT / "frame.json").write_text(json.dumps({"page": [W, H], "map_area": map_area, "furniture": furniture}), encoding="utf-8")
    print(f"map area {map_area} of {W:.0f}x{H:.0f}; furniture: {len(furniture)} dense text blocks")


if __name__ == "__main__":
    main()
