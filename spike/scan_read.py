"""Scanned-sheet front end: detect and read hand-lettered text on a raster record map.

No vector strokes to cluster, so the OCR detector finds the text boxes (rotated quads) on
overlapping tiles of a high-resolution render; recognition runs on each box. Output has the same
shape as the vector pipeline's read_rapid.json (cx, cy, w, h, angle, text, conf) so georef code
can consume it.  usage: SHEET=<scan.pdf> python spike/scan_read.py
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

DPI = 300           # render resolution; the scan itself is ~300 dpi
TILE, OVER = 1600, 240


def repair(t):
    """Hand-lettered coordinates are written N.10018.76; the recogniser often drops the dots.
    A letter-prefixed run of 6-8 digits with no decimal point gets one before its last two digits."""
    import re
    m = re.fullmatch(r"([NE])[.:]?(\d{6,8})", t.replace(" ", "").upper())
    return f"{m[1]}{m[2][:-2]}.{m[2][-2:]}" if m else t


def main():
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    page = pymupdf.open(PDF)[0]
    z = DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    # old scans: lift the grey background so faint pencil lettering has contrast
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
    img = clahe.apply(img)
    H, W = img.shape
    print(f"render {W}x{H} px at {DPI} dpi")

    found = []
    t0 = time.time()
    for y0 in range(0, H, TILE - OVER):
        for x0 in range(0, W, TILE - OVER):
            tile = img[y0:y0 + TILE, x0:x0 + TILE]
            res, _ = eng(cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR))
            for box, text, conf in res or []:
                q = np.array(box, float) + [x0, y0]
                (cx, cy), (w, h), ang = cv2.minAreaRect(q.astype(np.float32))
                if w < h:
                    w, h, ang = h, w, ang + 90
                ang = (ang + 90) % 180 - 90
                found.append({"cx": cx / z, "cy": cy / z, "w": w / z, "h": h / z, "angle": round(float(ang), 2),
                              "glyphs": len(text), "glyph_h": h / z * 0.75, "text": text, "conf": float(conf), "px": q.tolist()})
    # the same box is found on both sides of a tile overlap: keep the higher-confidence one
    found.sort(key=lambda b: -b["conf"])
    keep = []
    for b in found:
        if all(abs(b["cx"] - k["cx"]) > 0.5 * min(b["w"], k["w"]) or abs(b["cy"] - k["cy"]) > 0.6 * max(b["h"], k["h"]) for k in keep):
            keep.append(b)
    for i, b in enumerate(keep):
        b["id"] = i
        b["text"] = repair(b["text"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "read_rapid.json").write_text(json.dumps(keep, indent=1, ensure_ascii=False), encoding="utf-8")

    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for b in keep:
        cv2.polylines(vis, [np.array(b["px"], np.int32)], True, (0, 0, 255) if abs(b["angle"]) > 3 else (0, 160, 0), 3)
    cv2.imwrite(str(OUT / "scan_overlay.png"), cv2.resize(vis, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_AREA))
    coords = [b["text"] for b in keep if any(c.isdigit() for c in b["text"]) and len(b["text"]) >= 6]
    print(f"boxes {len(found)} -> {len(keep)} after overlap dedupe | {time.time() - t0:.0f}s | numeric-looking reads {len(coords)}")
    print("sample:", coords[:25])


if __name__ == "__main__":
    main()
