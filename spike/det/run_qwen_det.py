"""Trial A: qwen2.5vl:7b text-line DETECTION on the 1969 scan via tiled grounding.

Tiles page300.png into overlapping ~1200px tiles, asks qwen for bbox_2d of every piece of
text per tile (JSON grounding), maps boxes back to page coords, dedupes overlaps (shapely IoU),
writes spike/det/qwen_dets.json for spike/det/det_score.py to score.

Calibration (spike/det/calib2.py): a synthetic text box at known coords round-tripped through
qwen2.5vl:7b came back at essentially the same pixel coords (711-863 vs a drawn glyph run inside
a 700-950 box) -- Ollama does NOT rescale the image; bbox_2d is 1:1 pixel space of what we send.

usage: python spike/det/run_qwen_det.py
"""
import base64
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "page300.png"
OUT = HERE / "qwen_dets.json"

TILE = 1200
STEP = 1000  # 200px overlap
PROMPT = ('Detect all text in this image tile of a hand-lettered survey drawing. '
          'Output a JSON list of objects with "bbox_2d": [x1,y1,x2,y2] in pixel coordinates '
          'of this image, and "text": the transcription. Reply with JSON only, no other words.')


def tiles_1d(total, tile, step):
    xs = list(range(0, max(total - tile, 0) + 1, step))
    if not xs or xs[-1] != total - tile:
        xs.append(max(total - tile, 0))
    return sorted(set(xs))


def ask_qwen(png_bytes):
    req = {"model": "qwen2.5vl:7b", "stream": False, "options": {"temperature": 0},
           "prompt": PROMPT, "images": [base64.b64encode(png_bytes).decode()]}
    import urllib.request
    r = urllib.request.urlopen(urllib.request.Request(
        "http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}),
        timeout=180)
    return json.load(r)["response"]


def parse_loose(text):
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s.strip())
    s = re.sub(r"```$", "", s.strip())
    m = re.search(r"\[.*\]", s, re.S)
    if not m:
        return []
    s = m.group(0)
    s = re.sub(r",\s*([\]}])", r"\1", s)  # trailing commas
    try:
        return json.loads(s)
    except Exception:
        return []


def iou(a, b):
    if not a.is_valid or not b.is_valid or not a.intersects(b):
        return 0.0
    inter = a.intersection(b).area
    return inter / (a.area + b.area - inter)


def main():
    img = cv2.imread(str(PAGE), cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    xs = tiles_1d(w, TILE, STEP)
    ys = tiles_1d(h, TILE, STEP)
    print(f"page {w}x{h}, {len(xs)}x{len(ys)} = {len(xs) * len(ys)} tiles")

    raw = []  # (px quad page-space, text)
    t_start = time.time()
    n_calls = 0
    for yi, y0 in enumerate(ys):
        for xi, x0 in enumerate(xs):
            x1, y1 = min(x0 + TILE, w), min(y0 + TILE, h)
            tile = img[y0:y1, x0:x1]
            ok, buf = cv2.imencode(".png", tile)
            t0 = time.time()
            try:
                resp = ask_qwen(buf.tobytes())
            except Exception as e:
                print(f"  tile ({xi},{yi}) FAILED {type(e).__name__}: {e}")
                continue
            dt = time.time() - t0
            n_calls += 1
            items = parse_loose(resp)
            kept = 0
            for it in items:
                bb = it.get("bbox_2d")
                if not bb or len(bb) != 4:
                    continue
                bx0, by0, bx1, by1 = bb
                if bx1 <= bx0 or by1 <= by0:
                    continue
                px = [[x0 + bx0, y0 + by0], [x0 + bx1, y0 + by0], [x0 + bx1, y0 + by1], [x0 + bx0, y0 + by1]]
                raw.append({"px": px, "text": str(it.get("text", ""))})
                kept += 1
            print(f"  tile ({xi},{yi}) [{x0},{y0}]-[{x1},{y1}] {dt:.1f}s -> {len(items)} raw, {kept} kept")
    total_dt = time.time() - t_start
    print(f"{n_calls} calls, {total_dt:.1f}s total, {total_dt / max(n_calls, 1):.1f}s/call, {total_dt / (len(xs) * len(ys)):.1f}s/tile avg")
    print(f"{len(raw)} boxes before dedup")

    # dedupe: first-seen wins on IoU > 0.5 (tile raster order = top-left tiles processed first)
    polys = [Polygon(d["px"]) for d in raw]
    kept_idx = []
    for i, p in enumerate(polys):
        if not p.is_valid or p.area <= 0:
            continue
        dup = any(iou(p, polys[j]) > 0.5 for j in kept_idx)
        if not dup:
            kept_idx.append(i)
    dets = [raw[i] for i in kept_idx]
    print(f"{len(dets)} boxes after dedup")

    OUT.write_text(json.dumps(dets), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
