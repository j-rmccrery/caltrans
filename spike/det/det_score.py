"""Shared gate for scan text-line DETECTORS on the 1969 scan R-65.2 (spike/gt_scan.py's 32 keyed boxes).

A detector writes a JSON list of quads in pixel coords of spike/out/<STEM>/page300.png
(300 dpi, 4369 x 6291): [{"px": [[x,y],[x,y],[x,y],[x,y]], "text": "<optional read>"}, ...].
This script scores it two ways and draws the 32 keyed crops with the best box on each:

  landed   best box covers >= 80 % of the keyed box and is not more than 2.2x its area (fusion)
  cut      some overlap but coverage < 80 %
  fused    coverage ok but the box is > 2.2x the keyed area (swallowed a neighbour)
  missed   no overlap
  digits   if the detector also wrote "text": digit string equals the keyed digits (gt_scan.digits)

Caveat: the keyed quads are RapidOCR's own boxes, and ~8 of the 32 are themselves fused or cut
(that is the point of the leg). The overlay PNG is the real gate; the counts are the summary.

usage: python spike/det/det_score.py <detections.json> [--name surya] -> prints counts, writes
       spike/det/out/<name>_overlay.png (32 crops, keyed box red, best detector box green)
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
sys.path.insert(0, str(SPIKE))
from gt_scan import TRUTH, digits  # noqa: E402

STEM = "r_00065_002_1969-09-01_sn-02048"
PAGE = SPIKE / "out" / STEM / "page300.png"
RAPID = SPIKE / "out" / STEM / "read_rapid.json"


def match_truth(dets, keyed=None):
    """Map each TRUTH-keyed box (id into RAPID = the RapidOCR-1.4.4 read_rapid.json this repo
    keys gt_scan.py's truth by) to its best-overlap box in a detector's own `dets` list, which
    has its own, unrelated box ids/order. Used instead of ever treating a TRUTH key as an index
    into a different detector's boxes. Returns {truth_id: (best_index_or_None, coverage)}."""
    keyed = keyed or {b["id"]: b for b in json.load(open(RAPID, encoding="utf-8")) if b["id"] in TRUTH}
    polys = [Polygon(d["px"]) for d in dets]
    out = {}
    for k in TRUTH:
        t = Polygon(keyed[k]["px"])
        best, cov = None, 0.0
        for i, p in enumerate(polys):
            if not p.is_valid or not p.intersects(t):
                continue
            c = p.intersection(t).area / t.area
            if c > cov:
                best, cov = i, c
        out[k] = (best, cov)
    return out


def score(dets, name="det"):
    keyed = {b["id"]: b for b in json.load(open(RAPID, encoding="utf-8")) if b["id"] in TRUTH}
    matches = match_truth(dets, keyed)
    polys = [Polygon(d["px"]) for d in dets]
    img = cv2.imread(str(PAGE), cv2.IMREAD_GRAYSCALE)
    tiles, rows = [], []
    counts = {"landed": 0, "cut": 0, "fused": 0, "missed": 0, "digits": 0}
    for k, want in TRUTH.items():
        t = Polygon(keyed[k]["px"])
        best, cov = matches[k]
        if best is None:
            verdict = "missed"
        elif cov < 0.8:
            verdict = "cut"
        elif polys[best].area > 2.2 * t.area:
            verdict = "fused"
        else:
            verdict = "landed"
        counts[verdict] += 1
        got = dets[best].get("text", "") if best is not None else ""
        dig = bool(got) and digits(got) == digits(want)
        counts["digits"] += dig
        rows.append((k, want, verdict, f"{cov:.2f}", got))
        # crop: keyed box padded, both quads drawn
        q = np.array(keyed[k]["px"], np.int32)
        x0, y0 = q.min(0) - 60
        x1, y1 = q.max(0) + 60
        if best is not None:
            b = np.array(dets[best]["px"], np.int32)
            x0, y0 = np.minimum((x0, y0), b.min(0) - 20)
            x1, y1 = np.maximum((x1, y1), b.max(0) + 20)
        x0, y0 = max(int(x0), 0), max(int(y0), 0)
        x1, y1 = min(int(x1), img.shape[1]), min(int(y1), img.shape[0])
        crop = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
        cv2.polylines(crop, [q - (x0, y0)], True, (0, 0, 255), 1)
        if best is not None:
            cv2.polylines(crop, [np.array(dets[best]["px"], np.int32) - (x0, y0)], True, (0, 200, 0), 1)
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        cv2.putText(crop, f"{k} {verdict} {want}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        tiles.append(crop)
    # sheet of tiles, 4 per row
    w = max(t.shape[1] for t in tiles)
    h = max(t.shape[0] for t in tiles)
    cols = 4
    sheet = np.full((h * ((len(tiles) + cols - 1) // cols), w * cols, 3), 255, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * h:r * h + t.shape[0], c * w:c * w + t.shape[1]] = t
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    cv2.imwrite(str(out / f"{name}_overlay.png"), sheet)
    for r in rows:
        print("  {:4} {:<26} {:<7} cov {}  read {!r}".format(r[0], r[1], r[2], r[3], r[4]))
    print(f"{name}: landed {counts['landed']}/32, cut {counts['cut']}, fused {counts['fused']}, "
          f"missed {counts['missed']}; digits exact {counts['digits']}/32 (RapidOCR baseline 21/32); "
          f"{len(dets)} boxes on the page; overlay {out / (name + '_overlay.png')}")
    return counts


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else Path(args[0]).stem
    score(json.load(open(args[0], encoding="utf-8")), name)
