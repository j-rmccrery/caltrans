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
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT, PDF  # noqa: E402
from checks import linework_segments  # noqa: E402
from georef import segments  # noqa: E402
from layers import classify, has_layers  # noqa: E402

PAD = 60


def cluster_boxes(boxes, W, H, cell=4.0, gap=8.0, page_frac=0.3):
    """Merge nearby path boxes into a few compact regions (grid-rasterise, dilate, connected components
    -- blocks.py's own glyph-merging idea, applied to layer-classified paths instead of glyph strokes).
    A single path spanning most of the sheet (the sheet border, drawn as one rectangle path) is not a
    furniture "region": its own bbox is dropped before clustering, and so is any cluster that still
    spans more than page_frac of the sheet after merging (measured on Presidio: RW-SHEET-MISC alone,
    unfiltered, clusters into one 88 % blob that would exclude nearly every label on the sheet)."""
    boxes = [b for b in boxes if (b[2] - b[0]) < page_frac * W and (b[3] - b[1]) < page_frac * H]
    if not boxes:
        return []
    gw, gh = int(W // cell) + 2, int(H // cell) + 2
    grid = np.zeros((gh, gw), dtype=bool)
    for x0, y0, x1, y1 in boxes:
        c0, r0 = int(x0 // cell), int(y0 // cell)
        c1, r1 = int(x1 // cell), int(y1 // cell)
        grid[max(r0, 0):r1 + 1, max(c0, 0):c1 + 1] = True
    pad = max(1, int(round(gap / cell)))
    grid = ndimage.binary_dilation(grid, structure=np.ones((2 * pad + 1, 2 * pad + 1), dtype=bool))
    out = []
    for sl in ndimage.find_objects(ndimage.label(grid)[0]):
        r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        x0, y0, x1, y1 = c0 * cell, r0 * cell, c1 * cell, r1 * cell
        if x1 - x0 < page_frac * W and y1 - y0 < page_frac * H:
            out.append([round(x0), round(y0), round(x1), round(y1)])
    return out


def main():
    page = pymupdf.open(PDF)[0]
    W, H = page.rect.width, page.rect.height
    # leg-1 MAP_AREA exactly: R/W-weight lines (1.9-2.1 pt, not the border) and the vertex circles; the
    # legend's sample circle and a stray heavy stroke in the title block must not drag the box, so
    # circles enter by their 2-98 % range. Layers are not used here (retry spec: additive only, and the
    # width band already picks the map's own linework reliably -- nothing to fix, nothing to remove).
    segs = linework_segments(page, 0.2)
    P = np.array([q for a, b, w, _ in segs if 1.9 <= w <= 2.1 and np.hypot(*(b - a)) < 0.8 * max(W, H) for q in (a, b)]).reshape(-1, 2)
    # additive: table-class paths clustered into their actual table locations, added to FURNITURE below.
    table_boxes = [[d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1] for d in page.get_drawings() if classify(d.get("layer"))[0] == "table"] if has_layers(page) else []
    table_furniture = cluster_boxes(table_boxes, W, H)
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
                 for b in blocks if b["glyphs"] >= 30 and abs(b["angle"]) < 2] + table_furniture
    (OUT / "frame.json").write_text(json.dumps({"page": [W, H], "map_area": map_area, "furniture": furniture}), encoding="utf-8")
    print(f"map area {map_area} of {W:.0f}x{H:.0f}; furniture: {len(furniture)} regions ({len(table_furniture)} from table/furniture layers)")


if __name__ == "__main__":
    main()
