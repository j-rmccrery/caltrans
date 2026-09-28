"""Trial: PaddleOCR PP-OCRv5 server DET, two full-resolution variants beyond run_paddle.py's
TUNED run (which was silently clamped to max_side_limit=4000, paddlex's default page-length
cap -- see leg background). Both use thresh 0.2, box_thresh 0.3, unclip_ratio 1.3.

  (a) whole page, no clamp: limit_side_len=6300, limit_type=max, max_side_limit=6300
      (>= the page's 6291 long side, so TextDetection's own default 4000 clamp never fires)
  (b) 1500px tiles, 250px overlap (step 1250), each tile det'd independently (well under any
      clamp), boxes mapped back to page coords, merged with shapely IoU dedup (IoU > 0.5 keeps
      the larger box; this also collapses a box straddling two tiles into one where both tile
      copies agree)

usage: <venv_paddle>\\Scripts\\python.exe spike/det/run_paddle_fullres.py
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "page300.png"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

img = cv2.imread(str(PAGE))
H, W = img.shape[:2]
print("page shape", img.shape)

TUNED = dict(thresh=0.2, box_thresh=0.3, unclip_ratio=1.3)


def polys_to_dets(polys):
    return [{"px": [[float(x), float(y)] for x, y in p]} for p in polys]


def iou_dedup(dets, thresh=0.5):
    polys = [Polygon(d["px"]) for d in dets]
    keep = [True] * len(dets)
    order = sorted(range(len(dets)), key=lambda i: -polys[i].area)
    for a_i, ai in enumerate(order):
        if not keep[ai] or not polys[ai].is_valid:
            continue
        for bi in order[a_i + 1:]:
            if not keep[bi] or not polys[bi].is_valid:
                continue
            inter = polys[ai].intersection(polys[bi]).area
            union = polys[ai].union(polys[bi]).area
            if union > 0 and inter / union > thresh:
                keep[bi] = False  # smaller (or equal, later in sort) box dropped
    return [d for d, k in zip(dets, keep) if k]


# --- variant (a): whole page, explicit no-clamp ---
# paddleocr.TextDetection's wrapper whitelist does NOT pass through max_side_limit at all
# (ValueError: Unknown argument) -- that's the hidden clamp itself, not just its default value.
# paddlex.create_model is the underlying predictor and does accept it.
def run_full_page():
    import paddlex
    det = paddlex.create_model("PP-OCRv5_server_det",
                                limit_side_len=6300, limit_type="max", max_side_limit=6300, **TUNED)
    t0 = time.time()
    res = list(det.predict(img))
    dt = time.time() - t0
    polys = res[0]["dt_polys"]
    dets = polys_to_dets(polys)
    path = OUT / "g_full_noclamp.json"
    json.dump(dets, open(path, "w"))
    print(f"g_full_noclamp: input long side served={max(H, W)} (max_side_limit=6300) "
          f"predict={dt:.1f}s boxes={len(dets)} device=CPU -> {path}")
    return path


# --- variant (b): 1500px tiles, 250px overlap, merged ---
def tiles_1d(total, tile, step):
    xs = list(range(0, max(total - tile, 0) + 1, step))
    if not xs or xs[-1] != total - tile:
        xs.append(max(total - tile, 0))
    return sorted(set(xs))


def run_tiled():
    import paddlex
    det = paddlex.create_model("PP-OCRv5_server_det",
                                limit_side_len=1500, limit_type="max", max_side_limit=1500, **TUNED)
    TILE, OVERLAP = 1500, 250
    STEP = TILE - OVERLAP
    xs, ys = tiles_1d(W, TILE, STEP), tiles_1d(H, TILE, STEP)
    print(f"tiling {len(xs)}x{len(ys)} = {len(xs) * len(ys)} tiles of {TILE}px, {OVERLAP}px overlap")
    raw = []
    t0 = time.time()
    for y0 in ys:
        for x0 in xs:
            tile = img[y0:y0 + TILE, x0:x0 + TILE]
            res = list(det.predict(tile))
            polys = res[0]["dt_polys"]
            for p in polys:
                raw.append({"px": [[float(x) + x0, float(y) + y0] for x, y in p]})
    dt = time.time() - t0
    print(f"raw tile boxes (pre-dedup): {len(raw)}  predict total={dt:.1f}s")
    merged = iou_dedup(raw, thresh=0.5)
    path = OUT / "h_tiles_1500_250.json"
    json.dump(merged, open(path, "w"))
    print(f"h_tiles_1500_250: tiles={len(xs) * len(ys)} raw={len(raw)} merged={len(merged)} "
          f"predict={dt:.1f}s device=CPU -> {path}")
    return path


if __name__ == "__main__":
    run_full_page()
    run_tiled()
