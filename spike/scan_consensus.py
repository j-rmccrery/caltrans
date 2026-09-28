"""Two independent readers on a scanned sheet, accepted only where they agree or structure repairs them.

Reader 1: RapidOCR line read (scan_read.py, read_rapid.json). Reader 2: the local vision model on a
tight, levelled crop of the same box (cached in read_vlm.json; the prompt carries no example values).
Each box is typed by its structure (coordinate, angle, distance, radius, label) from both reads, the
digit strings are compared, and a box is:
  agree     both readers give the same digits;
  repaired  one reader dropped a leading digit and the other's digits restore a value inside the
            sheet's grid range (coordinates only), or the two differ only in a dot the structure fixes;
  queue     anything else: both reads kept for the surveyor, nothing chosen.
Output: read_scan.json in the block format, with status and both raw reads; scored against gt_scan.py
where truth exists.
usage: SHEET=<scan.pdf> python spike/scan_consensus.py [--vlm]   (--vlm fills the cache; slow)
"""
import json
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "det"))
from georef import OUT, PDF  # noqa: E402
from scan_readers import crop_of, vlm  # noqa: E402

READS_DEFAULT = "read_v5.json" if (OUT / "read_v5.json").exists() and (OUT / "read_vlm_v5.json").exists() else "read_rapid.json"  # v5 is the default once its boxes AND its vision-reader cache exist (the vote needs both readers); otherwise rapid, whose cache is filled
READS = os.environ.get("READS", READS_DEFAULT)  # READS=read_rapid.json still works as the explicit fallback

ANGLE = re.compile(r"(\d{1,3})\D{0,2}(\d{2})\D{0,2}(\d{2})\D*$")
NUM = re.compile(r"(\d{1,6})[.,]?(\d{2})$")


def digits(s):
    return "".join(ch for ch in s if ch.isdigit())


def kind(text):
    t = text.replace(" ", "").upper()
    if re.match(r"^[NE][.:]?\d", t) or (re.match(r"^\d{4,6}\.\d{2}$", t)):
        return "coordinate"
    if "°" in t or re.match(r"^[ΔA][:=]?\d", t) or re.search(r"\d{1,3}°\d{2}'\d{2}", t):
        return "angle"
    if re.match(r"^R[=:\-]?\d", t):
        return "radius"
    if re.match(r"^L[=:\-]?\d", t) or re.match(r"^\d{1,4}\.\d{2}'?$", t) or re.match(r"^\d{3,6}$", t):
        return "distance"
    return "label"


def valid_for_kind(text, k):
    """Structural check only (loop16 send-back item 4): does `text` look like a well-formed
    read for its OWN apparent kind -- no ground truth involved. Used to arbitrate between two
    independent reads of the same box location (e.g. an old and a new detector's own reads)."""
    t = text.replace(" ", "").upper()
    if k == "coordinate":
        return bool(re.match(r"^[NE][.:]?\d{4,6}(\.\d{1,2})?$", t))  # incl. round border labels like E.14000
    if k == "angle":
        return bool(re.search(r"\d{1,3}\D{0,2}\d{2}\D{0,2}\d{2}", t)) and len(digits(t)) >= 5
    if k == "radius":
        return bool(re.match(r"^R[=:\-]?\d{2,5}", t))
    if k == "distance":
        return bool(re.match(r"^[LR]?[=:\-]?\d{1,5}\.\d{2}", t)) or bool(re.match(r"^\d{3,6}$", t))
    return False


def pick_reader(text_a, conf_a, text_b, conf_b):
    """Vote between two independent reads of the same keyed location: prefer whichever parses
    validly for its own apparent kind, else the higher-confidence read. No truth consulted."""
    va = valid_for_kind(text_a, kind(text_a))
    vb = valid_for_kind(text_b, kind(text_b))
    if va and not vb:
        return text_a, "a"
    if vb and not va:
        return text_b, "b"
    return (text_a, "a") if conf_a >= conf_b else (text_b, "b")


def grid_range(reads):
    """N and E ranges from the grid labels on the border (N.10000, E.12000: round numbers with a letter),
    widened a little; None when the sheet has none."""
    ns, es = [], []
    for b in reads:
        m = re.match(r"^([NE])[.:]?(\d{1,4}(?:000|500))$", b["text"].replace(" ", "").upper())
        if m:
            (ns if m[1] == "N" else es).append(float(m[2]))
    if not ns or not es:
        return None
    pad = max(0.15 * max(max(ns) - min(ns), max(es) - min(es)), 3000)  # one label read on an axis: a sheet spans a few thousand feet
    return (min(ns) - pad, max(ns) + pad), (min(es) - pad, max(es) + pad)


def consensus(rapid, vis, k, grid):
    dr, dv = digits(rapid), digits(vis)
    if dr and dr == dv:
        return "agree", dr
    if k == "coordinate" and grid and dr and dv:
        # one reader dropped the leading digit: the longer read, if it lands inside the grid
        long_, short = (dr, dv) if len(dr) > len(dv) else (dv, dr)
        if long_.endswith(short) and len(long_) - len(short) == 1:
            val = float(long_[:-2] + "." + long_[-2:])
            (n0, n1), (e0, e1) = grid
            if n0 <= val <= n1 or e0 <= val <= e1:
                return "repaired", long_
    if k == "angle" and dr and dv and len(dr) == len(dv) and sum(a != b for a, b in zip(dr, dv)) == 0:
        return "agree", dr
    return "queue", ""


def render(digits_, k, rapid, vis):
    """Put the structure back on an accepted digit string."""
    letter = next((c for c in (rapid + vis).upper() if c in "NE"), "") if k == "coordinate" else ""
    if k == "coordinate":
        return f"{letter}{digits_[:-2]}.{digits_[-2:]}" if len(digits_) > 2 else digits_
    if k == "angle":
        d = digits_
        return f"{d[:-4]}°{d[-4:-2]}'{d[-2:]}\"" if len(d) >= 5 else d
    if k in ("distance", "radius"):
        m = NUM.match(digits_)
        if k == "radius" or ("." not in rapid and "." not in vis and len(digits_) <= 4 and k == "radius"):
            return f"R={digits_}'"
        return f"{digits_[:-2]}.{digits_[-2:]}'" if len(digits_) > 2 else digits_
    return digits_


def main():
    reads = json.loads((OUT / READS).read_text(encoding="utf-8"))
    # the VLM cache is keyed by box id WITHIN one detector's own box list (id spaces differ between
    # read_rapid.json and read_v5.json -- different box counts/order), so it must be namespaced per
    # detector; a shared filename would silently pair v5 boxes with rapid-era vlm reads (all "queue").
    cache = OUT / ("read_vlm.json" if READS == "read_rapid.json" else "read_vlm_" + READS.removeprefix("read_").removesuffix(".json") + ".json")
    vis = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    if "--vlm" in sys.argv:
        page = pymupdf.open(PDF)[0]
        z = 300 / 72
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        for i, b in enumerate(reads):
            if str(b["id"]) in vis:
                continue
            _, png = cv2.imencode(".png", crop_of(img, b, z))
            try:
                vis[str(b["id"])] = vlm(png.tobytes())
            except Exception as e:
                vis[str(b["id"])] = ""
            if i % 20 == 0:
                cache.write_text(json.dumps(vis, indent=0, ensure_ascii=False), encoding="utf-8"); print(f"  vision model {i}/{len(reads)}", flush=True)
        cache.write_text(json.dumps(vis, indent=0, ensure_ascii=False), encoding="utf-8")
    grid = grid_range(reads)
    out, counts = [], {"agree": 0, "repaired": 0, "queue": 0}
    for b in reads:
        v = vis.get(str(b["id"]), "")
        k = kind(b["text"]) if kind(b["text"]) != "label" else kind(v)
        status, d = consensus(b["text"], v, k, grid)
        counts[status] += 1
        out.append({**b, "kind": k, "rapid": b["text"], "vision": v, "status": status, "text": render(d, k, b["text"], v) if d else "", "conf": 1.0 if status != "queue" else 0.0})
    out_name = "read_scan.json" if READS == READS_DEFAULT else "read_scan_" + READS.removeprefix("read_").removesuffix(".json") + ".json"
    (OUT / out_name).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} boxes: {counts}; vision reads cached {len(vis)}; grid range {grid}")
    try:
        from gt_scan import TRUTH
        if READS == "read_rapid.json":
            id_to_truth = {o["id"]: TRUTH[o["id"]] for o in out if o["id"] in TRUTH}
        else:
            # this detector's ids don't line up with TRUTH's (RapidOCR-1.4.4) ids -- map by
            # best overlap against read_rapid.json instead of a hard-coded id lookup
            from det_score import match_truth
            matches = match_truth(out)
            id_to_truth = {out[i]["id"]: TRUTH[k] for k, (i, cov) in matches.items() if i is not None}
        right = wrong = queued = 0
        for o in out:
            if o["id"] in id_to_truth:
                if o["status"] == "queue":
                    queued += 1
                elif digits(o["text"]) == digits(id_to_truth[o["id"]]):
                    right += 1
                else:
                    wrong += 1; print("   WRONG accepted:", o["id"], o["status"], o["text"], "truth", id_to_truth[o["id"]])
        print(f"vs truth ({len(id_to_truth)} boxes): accepted right {right}, accepted wrong {wrong}, queued {queued}")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
