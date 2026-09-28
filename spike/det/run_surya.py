"""Surya text-line DETECTOR trial on the 1969 scan page (spike/det, isolated from the main pipeline).

Writes only under spike/det/. Reads page300.png read-only. Produces several detections_*.json
variants (full page, tiled, tiled+rotated-merged) in the format det_score.py wants:
[{"px": [[x,y]x4], "text": "<optional>"}, ...] in page300.png pixel coords.

Run with the surya venv (has surya-ocr + this box's torch/CUDA via --system-site-packages):
    <scratchpad>/venv_surya/Scripts/python.exe spike/det/run_surya.py [--recognize]

Score each variant with the PROJECT venv (has shapely):
    .venv/Scripts/python.exe spike/det/det_score.py spike/det/out/surya_full.json --name surya_full
"""
import argparse
import json
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "page300.png"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

TILE = 1500
OVERLAP = 250


def tiles_for(w, h, tile=TILE, overlap=OVERLAP):
    """(x0, y0, x1, y1) windows covering w x h with overlap, last tile in each axis flush to edge."""
    xs = list(range(0, max(w - tile, 0) + 1, tile - overlap)) or [0]
    if xs[-1] + tile < w:
        xs.append(w - tile)
    ys = list(range(0, max(h - tile, 0) + 1, tile - overlap)) or [0]
    if ys[-1] + tile < h:
        ys.append(h - tile)
    boxes = []
    for y0 in ys:
        for x0 in xs:
            boxes.append((x0, y0, min(x0 + tile, w), min(y0 + tile, h)))
    return boxes


def polys_from_result(res, offset=(0, 0)):
    """surya TextDetectionResult -> list of {"px": [[x,y]x4]} in page coords, given tile offset."""
    ox, oy = offset
    out = []
    for line in res.bboxes:
        poly = line.polygon  # 4 [x,y] points, tile-local
        px = [[float(x) + ox, float(y) + oy] for x, y in poly]
        out.append({"px": px})
    return out


def run_full(predictor, img):
    t0 = time.time()
    [res] = predictor([img])
    dt = time.time() - t0
    dets = polys_from_result(res)
    return dets, dt


def run_tiled(predictor, img, tile=TILE, overlap=OVERLAP, rot=None):
    """rot: None, or 90 (rotate page 90 deg CW before tiling; boxes mapped back to original coords)."""
    src = img
    if rot == 90:
        src = img.transpose(Image.ROTATE_270)  # PIL ROTATE_270 = 90 deg CW visually
    w, h = src.size
    windows = tiles_for(w, h, tile, overlap)
    t0 = time.time()
    crops = [src.crop(box) for box in windows]
    results = predictor(crops, batch_size=min(8, len(crops)))
    dt = time.time() - t0
    dets = []
    for (x0, y0, x1, y1), res in zip(windows, results):
        d = polys_from_result(res, offset=(x0, y0))
        dets.extend(d)
    if rot == 90:
        # map from rotated-image coords back to original page coords.
        # src = original rotated 90 CW: src(x,y) <- original(y, H_orig-1-x) i.e.
        # ROTATE_270 (PIL) turns image 90 deg CW; a point (x,y) in src corresponds to
        # original point (x_o, y_o) = (y, W_src - 1 - x)  [W_src == H_orig]
        W_src = w  # = H_orig
        for d in dets:
            d["px"] = [[float(y), float(W_src - 1 - x)] for x, y in d["px"]]
    return dets, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recognize", action="store_true", help="also run recognition to fill text")
    ap.add_argument("--which", default="all", choices=["all", "full", "tiles", "tiles_rot"])
    args = ap.parse_args()

    import torch
    from surya.detection import DetectionPredictor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"torch {torch.__version__} device {device}")

    img = Image.open(PAGE).convert("RGB")
    print(f"page size {img.size}")

    predictor = DetectionPredictor.local()
    predictor.model.to(device)
    try:
        print("processor.size", predictor.processor.size)
    except Exception as e:
        print("processor.size unavailable:", e)

    variants = {}

    if args.which in ("all", "full"):
        dets, dt = run_full(predictor, img)
        variants["surya_full"] = (dets, dt)
        print(f"full: {len(dets)} boxes, {dt:.1f}s")

    if args.which in ("all", "tiles"):
        dets, dt = run_tiled(predictor, img, rot=None)
        variants["surya_tiles"] = (dets, dt)
        print(f"tiles: {len(dets)} boxes, {dt:.1f}s")

    if args.which in ("all", "tiles_rot"):
        base_dets, base_dt = variants.get("surya_tiles") or run_tiled(predictor, img, rot=None)
        rot_dets, rot_dt = run_tiled(predictor, img, rot=90)
        merged = base_dets + rot_dets
        variants["surya_tiles_rot_merged"] = (merged, base_dt + rot_dt)
        print(f"tiles_rot_merged: {len(merged)} boxes ({len(base_dets)} + {len(rot_dets)} rot), "
              f"{base_dt + rot_dt:.1f}s")

    if args.recognize:
        from surya.recognition import RecognitionPredictor
        rec = RecognitionPredictor.local()
        rec.model.to(device)
        for name, (dets, dt) in variants.items():
            t0 = time.time()
            crops = []
            for d in dets:
                xs = [p[0] for p in d["px"]]
                ys = [p[1] for p in d["px"]]
                x0, y0, x1, y1 = max(int(min(xs)), 0), max(int(min(ys)), 0), int(max(xs)), int(max(ys))
                if x1 <= x0 or y1 <= y0:
                    crops.append(Image.new("RGB", (4, 4), "white"))
                    continue
                crops.append(img.crop((x0, y0, x1, y1)))
            polygons = [[[0, 0], [c.size[0], 0], [c.size[0], c.size[1]], [0, c.size[1]]] for c in crops]
            results = rec(crops, task_names=["ocr_with_boxes"] * len(crops), polygons=[[p] for p in polygons])
            for d, r in zip(dets, results):
                d["text"] = r.text_lines[0].text if r.text_lines else ""
            rec_dt = time.time() - t0
            print(f"{name}: recognition {rec_dt:.1f}s for {len(dets)} crops")
            variants[name] = (dets, dt + rec_dt)

    for name, (dets, dt) in variants.items():
        out_path = OUT / f"{name}.json"
        out_path.write_text(json.dumps(dets), encoding="utf-8")
        print(f"wrote {out_path} ({len(dets)} boxes, {dt:.1f}s total)")


if __name__ == "__main__":
    main()
