"""Crops of distance labels whose printed length matches no chain: label box red, picked line blue,
candidate chains green with their drawn length in ft. usage: [SHEET=..] python crops.py out.png
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, r"C:\Users\johnr\projects\caltrans\spike")
import checks  # noqa: E402
from georef import OUT, PDF, READS, frame, real_text_blocks  # noqa: E402
from overlay import FURNITURE  # noqa: E402

page = pymupdf.open(PDF)[0]
g = json.loads((OUT / "georef.json").read_text()); a, bb = g["params"][:2]; scale = math.hypot(a, bb)
blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
checks.set_decimals(blocks)
chains, circles, paths, segs = checks.sheet_lines(page, blocks)


def cands_for(b, tol_deg=4.0):
    c, u, n = frame(b)
    out = []
    for ln in chains:
        if abs(ln["dir"] @ n) > math.sin(math.radians(tol_deg)):
            continue
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        if hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]:
            continue
        perp = abs((ln["p0"] - c) @ n)
        if perp < 5.0 * b["glyph_h"]:
            out.append((perp, ln))
    return out


items = []
for b in blocks:
    if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in FURNITURE):
        continue
    lines = b["text"].replace(" ", "").split("|")
    curve = any(checks.ANG.match(t) or checks.RAD.match(t) or checks.LEN.match(t) for t in lines)
    parts = [m.group(0) for t in lines for m in checks.TOKEN.finditer(t)] or lines
    for part in parts:
        m = checks.DIST.match(part)
        if not m or m[2] or curve:
            continue
        want = float(m[1])
        cs = cands_for(b)
        if not cs or any(abs(ln["len_pt"] * scale - want) < 1.0 for p, ln in cs):
            continue
        if any(checks.span_for(ln, want, scale, chains) is not ln for p, ln in cs):
            continue
        items.append((b, part, want, cs))

Z = 3
tiles = []
for b, part, want, cs in items[: int(sys.argv[2]) if len(sys.argv) > 2 else 12]:
    R = pymupdf.Rect(b["cx"] - 110, b["cy"] - 70, b["cx"] + 110, b["cy"] + 70) & page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(Z, Z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda p: (int((p[0] - R.x0) * Z), int((p[1] - R.y0) * Z))
    for p, ln in cs:
        cv2.line(im, f(ln["p0"]), f(ln["p1"]), (0, 160, 0), 2)
        mid = (ln["p0"] + ln["p1"]) / 2
        cv2.putText(im, f"{ln['len_pt'] * scale:.1f}", f(mid), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 120, 0), 1)
    pick = min(cs, key=lambda t: t[0])[1]
    cv2.line(im, f(pick["p0"]), f(pick["p1"]), (220, 80, 0), 2)
    c, u, n = frame(b)
    cv2.rectangle(im, f(c - u * b["w"] / 2 - n * b["h"] / 2), f(c + u * b["w"] / 2 + n * b["h"] / 2), (220, 0, 0), 2)
    cv2.putText(im, f"{part} want {want}", (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 0, 0), 2)
    im = cv2.resize(im, (660, 420))
    tiles.append(im)
while len(tiles) % 3:
    tiles.append(np.full_like(tiles[0], 255))
rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
cv2.imwrite(sys.argv[1], cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
print(len(items), "items; wrote", sys.argv[1])
