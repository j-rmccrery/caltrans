"""Resolution sweep for PP-OCRv5 server DET on the 1969 hand-lettered scan (spike/det, isolated
from the running main-pipeline loop: writes only under spike/det/, never touches spike/out/).

Subcommands (paddlex ones need venv_paddle; recognize needs the project .venv):
  sweep      task 1: whole-page long-side sweep, table of landed/cut/fused/missed + model input
             size (hooked) + timing + y-range of detections.
  collapse   task 2: dump the raw DB probability map before postprocess at 6291 and at the first
             collapsed scale from `sweep`'s table; try a pad-to-multiple-of-32 fix.
  tiles      task 3: tile the page at a given scale with overlap, dedupe by interior-area (not
             box size), score.
  render     task 4: best scale via resize(page300) vs pymupdf render at the matching dpi, with
             and without page300's CLAHE levelling.
  recognize  task 5: crop keyed-box matches from a dets json, run RapidOCR rec-only (project
             .venv's rapidocr_onnxruntime), rescore with digits.

usage:
  <venv_paddle>/Scripts/python.exe spike/det/sweep_scale.py sweep
  <venv_paddle>/Scripts/python.exe spike/det/sweep_scale.py collapse
  <venv_paddle>/Scripts/python.exe spike/det/sweep_scale.py tiles --scale 4000 --tile 2200 --overlap 450
  <venv_paddle>/Scripts/python.exe spike/det/sweep_scale.py render --scale 4000
  .venv/Scripts/python.exe        spike/det/sweep_scale.py recognize --dets spike/det/out/ls4000_dets.json --name ls4000_rec
"""
import argparse
import contextlib
import io
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SPIKE))

STEM = "r_00065_002_1969-09-01_sn-02048"
PAGE = SPIKE / "out" / STEM / "page300.png"
PDF = next((SPIKE.parent / "Sample Data").rglob(STEM + ".pdf"))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
TUNED = dict(thresh=0.2, box_thresh=0.3, unclip_ratio=1.3)


def dets_to_json(polys):
    return [{"px": [[float(x), float(y)] for x, y in p]} for p in polys]


def score_quiet(dets, name):
    """det_score.score() prints all 32 rows; keep that out of the sweep table, print only counts."""
    from det_score import score
    with contextlib.redirect_stdout(io.StringIO()):
        counts = score(dets, name=name)
    return counts


def yrange(dets):
    ys = [pt[1] for d in dets for pt in d["px"]]
    return (min(ys), max(ys)) if ys else (None, None)


# ---------------------------------------------------------------- paddlex plumbing (hooks) ----
def make_detector():
    import paddlex
    from paddlex.inference.models.text_detection.processors import DetResizeForTest, DBPostProcess

    seen_resize = {}
    orig_resize0 = DetResizeForTest.resize_image_type0

    def traced_resize0(self, img, limit_side_len, limit_type, max_side_limit=None):
        out, ratios = orig_resize0(self, img, limit_side_len, limit_type, max_side_limit)
        seen_resize["in"] = img.shape[:2]
        seen_resize["out"] = None if out is None else out.shape[:2]
        return out, ratios

    DetResizeForTest.resize_image_type0 = traced_resize0

    dump = {"enabled": False, "name": None}
    orig_process = DBPostProcess.process

    def traced_process(self, pred, img_shape, thresh, box_thresh, unclip_ratio):
        if dump["enabled"]:
            p = pred[0]  # raw sigmoid prob map, model-input resolution, before threshold/contours
            cv2.imwrite(str(OUT / f"{dump['name']}_probmap.png"), (np.clip(p, 0, 1) * 255).astype(np.uint8))
            mask = (p > (thresh or self.thresh)).astype(np.uint8) * 255
            cv2.imwrite(str(OUT / f"{dump['name']}_mask.png"), mask)
            rows_with_signal = np.where(p.max(axis=1) > (thresh or self.thresh))[0]
            src_h, src_w, ratio_h, ratio_w = img_shape
            print(f"  [probmap {dump['name']}] map shape (h,w)={p.shape} max_prob={p.max():.3f} "
                  f"rows-with-signal(model space) y=[{rows_with_signal.min() if len(rows_with_signal) else -1},"
                  f"{rows_with_signal.max() if len(rows_with_signal) else -1}] of {p.shape[0]} "
                  f"src(h,w)=({src_h},{src_w}) ratio=({ratio_h:.4f},{ratio_w:.4f})")
        return orig_process(self, pred, img_shape, thresh, box_thresh, unclip_ratio)

    DBPostProcess.process = traced_process

    det = paddlex.create_model("PP-OCRv5_server_det", **TUNED)
    return det, seen_resize, dump


def run_scale(det, seen_resize, dump, img, name, long_side, dump_name=None):
    dump["enabled"] = dump_name is not None
    dump["name"] = dump_name
    seen_resize.clear()
    t0 = time.time()
    res = list(det.predict(img, limit_side_len=long_side, limit_type="max", max_side_limit=long_side))
    dt = time.time() - t0
    dump["enabled"] = False
    dets = dets_to_json(res[0]["dt_polys"])
    json.dump(dets, open(OUT / f"{name}_dets.json", "w"))
    counts = score_quiet(dets, name)
    row = dict(name=name, long_side=long_side, model_in=seen_resize.get("out"), boxes=len(dets),
               seconds=round(dt, 1), yrange=yrange(dets), **counts)
    print("  {name:10} long_side={long_side:5} model_in={model_in!s:14} boxes={boxes:4} "
          "t={seconds:5}s  landed={landed:2} cut={cut:2} fused={fused:2} missed={missed:2}  "
          "y={yrange}".format(**row))
    return dets, row


# --------------------------------------------------------------------------------- task 1 -----
def cmd_sweep(args):
    img = cv2.imread(str(PAGE))
    print(f"page {PAGE.name}: shape (h,w,c)={img.shape}")
    det, seen_resize, dump = make_detector()
    scales = [args.only] if args.only else [2000, 2500, 3000, 3500, 3750, 4000, 4250, 4500, 5000, 5500, 6291]
    rows_path = OUT / "sweep_rows.json"
    rows = json.load(open(rows_path)) if args.only and rows_path.exists() else []
    for ls in scales:
        name = f"ls{ls}"
        _, row = run_scale(det, seen_resize, dump, img, name, ls)
        rows = [r for r in rows if r["long_side"] != ls] + [row]
    rows.sort(key=lambda r: r["long_side"])
    json.dump(rows, open(rows_path, "w"))
    print(f"wrote {rows_path}")


# --------------------------------------------------------------------------------- task 2 -----
def cmd_collapse(args):
    img = cv2.imread(str(PAGE))
    det, seen_resize, dump = make_detector()
    rows = json.load(open(OUT / "sweep_rows.json")) if (OUT / "sweep_rows.json").exists() else None
    first_collapsed = None
    if rows:
        for r in rows:
            if r["landed"] + r["cut"] + r["fused"] == 0 or (r["yrange"] and r["yrange"][0] and r["yrange"][0] > 2000):
                first_collapsed = r["long_side"]
                break
    print(f"first collapsed scale from sweep table: {first_collapsed}")
    targets = sorted(set([6291] + ([first_collapsed] if first_collapsed else [])))
    for ls in targets:
        run_scale(det, seen_resize, dump, img, f"collapse{ls}", ls, dump_name=f"collapse{ls}")

    # try the fix: pad the image so both dims are already multiples of 32 (>= the model's own
    # round-to-32) before handing it to the resizer at limit_type=max with limit=max(h,w), i.e.
    # force ratio=1.0 (no resize at all) at native resolution, padded cleanly.
    H, W = img.shape[:2]
    padH = ((H + 31) // 32) * 32
    padW = ((W + 31) // 32) * 32
    padded = cv2.copyMakeBorder(img, 0, padH - H, 0, padW - W, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    print(f"padded fix: {img.shape[:2]} -> {padded.shape[:2]} (mult of 32), limit_side_len=max(padded dims)")
    ls = max(padH, padW)
    run_scale(det, seen_resize, dump, padded, "collapse_padfix", ls, dump_name="collapse_padfix")


# --------------------------------------------------------------------------------- task 3 -----
def tiles_1d(total, tile, step):
    xs = list(range(0, max(total - tile, 0) + 1, step))
    if not xs or xs[-1] != total - tile:
        xs.append(max(total - tile, 0))
    return sorted(set(xs))


def interior_dedup(raw, iou_thresh=0.3):
    """raw: list of dicts with px + _tile (x0,y0,x1,y1) + _pad (interior inset). Cluster boxes
    that overlap (IoU > iou_thresh) and keep the one with the most of its own area inside its
    detecting tile's interior (away from that tile's seam), not the largest polygon -- a box
    that straddles a seam is often a fusion/cut artifact even when it is the bigger one."""
    from shapely.geometry import Polygon, box as shbox
    polys = [Polygon(d["px"]) for d in raw]
    interior_area = []
    for d, p in zip(raw, polys):
        x0, y0, x1, y1 = d["_tile"]
        pad = d["_pad"]
        interior = shbox(x0 + pad, y0 + pad, x1 - pad, y1 - pad)
        interior_area.append(p.intersection(interior).area if p.is_valid else 0.0)
    keep = [True] * len(raw)
    order = sorted(range(len(raw)), key=lambda i: -interior_area[i])
    for a_i, ai in enumerate(order):
        if not keep[ai] or not polys[ai].is_valid:
            continue
        for bi in order[a_i + 1:]:
            if not keep[bi] or not polys[bi].is_valid:
                continue
            inter = polys[ai].intersection(polys[bi]).area
            union = polys[ai].union(polys[bi]).area
            if union > 0 and inter / union > iou_thresh:
                keep[bi] = False  # bi has less interior support than ai (sorted above it)
    return [{"px": d["px"]} for d, k in zip(raw, keep) if k]


def cmd_tiles(args):
    img = cv2.imread(str(PAGE))
    H, W = img.shape[:2]
    det, seen_resize, dump = make_detector()
    TILE, OVERLAP = args.tile, args.overlap
    STEP = TILE - OVERLAP
    pad = OVERLAP // 2
    xs, ys = tiles_1d(W, TILE, STEP), tiles_1d(H, TILE, STEP)
    print(f"tiling {len(xs)}x{len(ys)} = {len(xs) * len(ys)} tiles of {TILE}px, {OVERLAP}px overlap, "
          f"detector limit_side_len={args.scale} (native inside each tile since tile < scale)")
    raw = []
    t0 = time.time()
    for y0 in ys:
        for x0 in xs:
            x1, y1 = min(x0 + TILE, W), min(y0 + TILE, H)
            tile = img[y0:y1, x0:x1]
            res = list(det.predict(tile, limit_side_len=args.scale, limit_type="max", max_side_limit=args.scale))
            for p in res[0]["dt_polys"]:
                raw.append({"px": [[float(x) + x0, float(y) + y0] for x, y in p], "_tile": (x0, y0, x1, y1), "_pad": pad})
    dt = time.time() - t0
    merged = interior_dedup(raw)
    name = f"tiles_{TILE}_{OVERLAP}"
    json.dump(merged, open(OUT / f"{name}_dets.json", "w"))
    counts = score_quiet(merged, name)
    print(f"{name}: raw={len(raw)} merged={len(merged)} t={dt:.1f}s landed={counts['landed']} "
          f"cut={counts['cut']} fused={counts['fused']} missed={counts['missed']} y={yrange(merged)}")


# --------------------------------------------------------------------------------- task 4 -----
def cmd_render(args):
    det, seen_resize, dump = make_detector()
    ls = args.scale
    dpi = 300.0 * ls / 6291.0
    print(f"matching render dpi for long_side={ls}: {dpi:.2f} (page300 is 300dpi, long side 6291)")

    # (a) resize page300.png (already CLAHE-levelled) down to this scale
    page = cv2.imread(str(PAGE))
    run_scale(det, seen_resize, dump, page, "render_a_resize", ls)

    # (b) render PDF at matching dpi with pymupdf, + CLAHE (same recipe as scan_read.py)
    import pymupdf
    pg = pymupdf.open(PDF)[0]
    z = dpi / 72
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    print(f"pymupdf render at {dpi:.2f}dpi: shape (h,w)={gray.shape}")

    gray_clahe = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    gray_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16)).apply(gray_clahe)
    bgr_clahe = cv2.cvtColor(gray_clahe, cv2.COLOR_GRAY2BGR)
    run_scale(det, seen_resize, dump, bgr_clahe, "render_b_clahe", max(gray.shape))

    # (c) render, no CLAHE
    bgr_raw = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    run_scale(det, seen_resize, dump, bgr_raw, "render_c_noclahe", max(gray.shape))


# --------------------------------------------------------------------------------- task 5 -----
def cmd_recognize(args):
    sys.path.insert(0, str(SPIKE))
    from gt_scan import TRUTH, digits  # noqa: E402
    from scan_readers import crop_of  # noqa: E402
    from shapely.geometry import Polygon
    from rapidocr_onnxruntime import RapidOCR

    dets = json.load(open(args.dets))
    RAPID = SPIKE / "out" / STEM / "read_rapid.json"
    keyed = {b["id"]: b for b in json.load(open(RAPID, encoding="utf-8")) if b["id"] in TRUTH}
    img = cv2.imread(str(PAGE), cv2.IMREAD_GRAYSCALE)
    polys = [Polygon(d["px"]) for d in dets]

    eng = RapidOCR()
    out_dets = []
    hits = 0
    for k, want in TRUTH.items():
        t = Polygon(keyed[k]["px"])
        best, cov = None, 0.0
        for i, p in enumerate(polys):
            if not p.is_valid or not p.intersects(t):
                continue
            c = p.intersection(t).area / t.area
            if c > cov:
                best, cov = i, c
        text = ""
        if best is not None:
            crop = crop_of(img, dets[best], 1.0)
            rec = eng(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR), use_det=False, use_cls=False, use_rec=True)
            txts = rec[0] if rec and rec[0] else []
            text = txts[0][0] if txts else ""
            d = dict(dets[best])
            d["text"] = text
            out_dets.append(d)
            hit = digits(text) == digits(want)
        else:
            hit = False
        hits += hit
        print(f"  {k:4} truth {want!r:26} read {text!r:26} {'OK' if hit else 'BAD'}")
    print(f"{args.name}: digits exact on matched keyed boxes = {hits}/{len(TRUTH)}")
    json.dump(out_dets, open(OUT / f"{args.name}_dets.json", "w"))
    score_quiet(out_dets if out_dets else dets, args.name)
    print(f"overlay -> {OUT / (args.name + '_overlay.png')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("sweep")
    p1.add_argument("--only", type=int, default=None)
    sub.add_parser("collapse")
    p3 = sub.add_parser("tiles")
    p3.add_argument("--scale", type=int, default=4000)
    p3.add_argument("--tile", type=int, default=2200)
    p3.add_argument("--overlap", type=int, default=450)
    p4 = sub.add_parser("render")
    p4.add_argument("--scale", type=int, default=4000)
    p5 = sub.add_parser("recognize")
    p5.add_argument("--dets", required=True)
    p5.add_argument("--name", required=True)
    a = ap.parse_args()
    {"sweep": cmd_sweep, "collapse": cmd_collapse, "tiles": cmd_tiles, "render": cmd_render,
     "recognize": cmd_recognize}[a.cmd](a)
