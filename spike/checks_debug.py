"""Scratch: draw the line chosen for a few checked labels (green = pass, red = fail, blue = none)."""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import checks  # noqa: E402
from georef import OUT, PDF, frame, real_text_blocks  # noqa: E402

page = pymupdf.open(PDF)[0]
blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8")) + real_text_blocks(page)
segs = checks.linework_segments(page)
from georef import segments
chains = [c for c in checks.lines_on_sheet(segs, segments(page)[1]) if c["len_pt"] >= 6]
rows = {r[1]: r for r in csv.reader(open(OUT / "checks.csv", encoding="utf-8"))}
tiles = []
for b in blocks:
    for part in b["text"].replace(" ", "").split("|"):
        if not (checks.BEAR.match(part) or checks.DIST.match(part)) or len(tiles) >= 10:
            continue
        ln = checks.nearest_line(b, chains, 5.0 * b["glyph_h"])
        res = rows.get(part, [None] * 5)[4]
        z = 4
        R = pymupdf.Rect(b["cx"] - 110, b["cy"] - 60, b["cx"] + 110, b["cy"] + 60)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R)
        im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        f = lambda q: (int((q[0] - R.x0) * z), int((q[1] - R.y0) * z))
        col = (0, 170, 0) if res == "pass" else (255, 0, 0) if res == "FAIL" else (0, 0, 255)
        if ln is not None:
            cv2.line(im, f(ln["p0"]), f(ln["p1"]), col, 3)
        box = cv2.boxPoints((((b["cx"] - R.x0) * z, (b["cy"] - R.y0) * z), (b["w"] * z, b["h"] * z), b["angle"]))
        cv2.polylines(im, [box.astype(np.int32)], True, col, 1)
        cv2.putText(im, f"{part} {res} {rows.get(part, ['', '', '', ''])[3]}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
        tiles.append(im)
H, W = min(t.shape[0] for t in tiles), min(t.shape[1] for t in tiles)
tiles = [t[:H, :W] for t in tiles]
h = (len(tiles) + 1) // 2
left, right = tiles[:h], tiles[h:] + [np.full_like(tiles[0], 255)] * (h - len(tiles[h:]))
cv2.imwrite(str(OUT / "checks_debug.png"), cv2.cvtColor(np.hstack([np.vstack(left), np.vstack(right)]), cv2.COLOR_RGB2BGR))
print("passes:")
for r in rows.values():
    if r[4] == "pass":
        print("  ", r)
