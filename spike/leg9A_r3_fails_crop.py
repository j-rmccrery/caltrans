"""Loop9 leg A attempt 2, item 2: spike/out/leg9A_r3_fails.png -- the six new tag-check rows R-10434.3
picked up (28/26/28 -> 30/26/34, zero new passes) before the dashdot-from-"beside" exclusion fix, each
attributed: tag in red, the false candidate piece in blue, caption naming which rows it caused and
whether it's a genuine record curve (honest fail) or a dash-dot train that doesn't belong to that tag's
own record at all (fake fail). Ad hoc, not part of the pipeline.
usage: SHEET=<r_10434_003 pdf> python spike/leg9A_r3_fails_crop.py -> spike/out/leg9A_r3_fails.png
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import checks  # noqa: E402
from checks import poly_dist, tag_leaders  # noqa: E402
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402

Z = 300 / 72
PAD = 70

# (tag, checks it caused, its own leader/beside tip) -- taken from the diagnosis: C6 and C32 both latch
# onto the same ~318 ft dash-dot piece (their tip is the "beside" search point, no leader on either);
# C9's SECOND drawn occurrence and C33 both latch onto the same ~608 ft piece (C33 via leader, C9 via beside)
TARGETS = [
    ("C6", ["radius", "arc length"]),
    ("C32", ["radius", "arc length"]),
    ("C9", ["radius (2nd occurrence, beside)", "arc length (2nd occurrence, beside)"]),
    ("C33", ["arc length (leader still finds the same false piece; its own radius check passes)"]),
]


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    checks.set_decimals(blocks)
    pool = checks.build_pool(page, blocks)
    arcs, paths = pool["arcs"], pool["paths"]
    tags = json.loads((OUT / "tags.json").read_text(encoding="utf-8"))
    tips = tag_leaders(tags, paths)

    ims = []
    for tag, checks_list in TARGETS:
        occs = [(i, t) for i, t in enumerate(tags) if t["tag"] == tag]
        # C9 is drawn three times on this sheet; the SECOND occurrence (near sheet pt 248,655) is the one
        # that finds the false dash-dot piece (the other two resolve elsewhere, unaffected)
        ti, t = occs[1] if tag == "C9" else occs[0]
        tip = tips[ti][0] if ti in tips else np.array([t["cx"], t["cy"]])
        dd_arcs = [x for x in arcs if x.get("dashdot")]
        false_piece = min(dd_arcs, key=lambda x: poly_dist(tip, x["pts"]))
        d = poly_dist(tip, false_piece["pts"])
        region = [t["cx"] - 2 * t["gh"], t["cy"] - t["gh"], t["cx"] + 2 * t["gh"], t["cy"] + t["gh"]]
        xs = [region[0], region[2]] + [p[0] for p in false_piece["pts"]]
        ys = [region[1], region[3]] + [p[1] for p in false_piece["pts"]]
        R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
        z = min(Z, 1100 / max(R.width, R.height, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
        im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
        cv2.polylines(im, [np.array([f(x, y) for x, y in false_piece["pts"]], np.int32)], False, (200, 130, 60), 4)
        cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (0, 0, 220), 3)
        im = cv2.copyMakeBorder(im, 0, 60, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cap1 = f"{tag}: {', '.join(checks_list)}"
        cap2 = f"blue = dash-dot train piece, {false_piece['len_pt']*scale:.1f} ft, {d:.1f} pt away -- FAKE FAIL (not this tag's record curve)"
        cv2.putText(im, cap1, (10, im.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(im, cap2, (10, im.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        ims.append(im)
        print(tag, checks_list, "-> FAKE FAIL, dash-dot train", false_piece["len_pt"] * scale, "ft, dist", d, "pt")

    h = max(im.shape[0] for im in ims)
    ims = [cv2.copyMakeBorder(im, 0, h - im.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for im in ims]
    combined = np.concatenate(ims, axis=1)
    cv2.imwrite(str(OUT / "leg9A_r3_fails.png"), cv2.cvtColor(combined, cv2.COLOR_RGB2BGR))
    print("wrote", OUT / "leg9A_r3_fails.png")


if __name__ == "__main__":
    main()
