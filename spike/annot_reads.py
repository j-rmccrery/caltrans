"""Reads from AutoCAD SHX Text annotations: every block from blocks.py takes the text of the annotations
whose centre falls inside it (same block format as read_glyph.json). Annotations no block covers become
blocks of their own with angle 0. usage: python spike/annot_reads.py <pdf> <blocks.json> <out.json>; then READS=<out.json> SHEET=<pdf> python spike/georef.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pymupdf

pdf, blocks_path, out = sys.argv[1:4]
page = pymupdf.open(pdf)[0]
blocks = json.loads(Path(blocks_path).read_text(encoding="utf-8"))
ann = [(a.info.get("content", "").strip(), a.rect) for a in page.annots() if a.info.get("title") == "AutoCAD SHX Text"]
ann = [(t.replace("%%D", "°").replace("%%d", "°").replace("%%P", "±").replace("%%C", "Ø"), r) for t, r in ann if t]  # AutoCAD control codes


def inside(b, x, y):
    th = math.radians(b["angle"]); u = np.array([math.cos(th), -math.sin(th)]); n = np.array([math.sin(th), math.cos(th)])
    d = np.array([x - b["cx"], y - b["cy"]])
    return abs(d @ u) <= b["w"] / 2 + 2 and abs(d @ n) <= b["h"] / 2 + 2


taken = set()
for b in blocks:
    mine = []
    for i, (t, r) in enumerate(ann):
        if i in taken:
            continue
        if inside(b, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2):
            mine.append((r.y0, r.x0, t)); taken.add(i)
    if mine:
        b["text"] = "|".join(t for _, _, t in sorted(mine))
        b["conf"] = 1.0
        b["src"] = "shx"
    else:
        b["text"] = ""
for i, (t, r) in enumerate(ann):
    if i in taken:
        continue
    blocks.append({"cx": (r.x0 + r.x1) / 2, "cy": (r.y0 + r.y1) / 2, "w": r.width, "h": r.height, "angle": 0.0, "glyphs": len(t),
                   "glyph_h": min(r.height, 12), "id": len(blocks), "text": t, "conf": 1.0, "src": "shx-orphan"})
Path(out).write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
print(f"annotations {len(ann)}, placed in blocks {len(taken)}, orphan blocks {len(ann) - len(taken)}, blocks with text {sum(1 for b in blocks if b['text'])} of {len(blocks)}")
