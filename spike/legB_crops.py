"""Loop4 legB2 evidence crops for R-10741.2: the bridged dashed parcel line for S16 deg20'26"E 176.73'
and the not-to-scale detail inset (region reconstructed: OCR could not read this sheet's "DETAIL \"A\"" /
"Scale: = N.T.S." caption, see legB2 report).
usage: SHEET=<r_10741_002 pdf> python spike/legB_crops.py
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402
import checks  # noqa: E402
import dashes  # noqa: E402

Z = 300 / 72
PAD = 60


def render(page, region, boxes, caption_lines):
    """boxes: [(rect_or_poly, color, thickness, is_poly)]."""
    xs = [region[0], region[2]] + [p[0] for b in boxes for p in (b[0] if b[3] else [(b[0][0], b[0][1]), (b[0][2], b[0][3])])]
    ys = [region[1], region[3]] + [p[1] for b in boxes for p in (b[0] if b[3] else [(b[0][0], b[0][1]), (b[0][2], b[0][3])])]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 1400 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for shape, color, thick, is_poly in boxes:
        if is_poly:
            cv2.polylines(im, [np.array([f(x, y) for x, y in shape], np.int32)], False, color, thick)
        else:
            x0, y0, x1, y1 = shape
            cv2.rectangle(im, f(x0, y0), f(x1, y1), color, thick)
    pad_bar = 30 * len(caption_lines) + 20
    need_w = max((cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0][0] for line in caption_lines), default=0) + 20
    im = cv2.copyMakeBorder(im, 0, pad_bar, 0, max(0, need_w - im.shape[1]), cv2.BORDER_CONSTANT, value=(255, 255, 255))
    for i, line in enumerate(caption_lines):
        cv2.putText(im, line, (10, im.shape[0] - pad_bar + 25 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    return im


def dashed_crop(page):
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    checks.set_decimals(blocks)
    gh = float(np.median([b["glyph_h"] for b in blocks])) if blocks else 6.0
    label_block = next(b for b in blocks if b["text"].replace(" ", "") == "S16°20'26\"E")
    region = [round(label_block["cx"] - label_block["w"] / 2 - 4), round(label_block["cy"] - label_block["h"] / 2 - 4),
              round(label_block["cx"] + label_block["w"] / 2 + 4), round(label_block["cy"] + label_block["h"] / 2 + 4)]
    ds = dashes.collect_dashes(page)
    trains = dashes.dash_trains(ds, bridge=6.0 * gh)
    target = np.array([label_block["cx"], label_block["cy"]])
    train = min(trains, key=lambda t: np.hypot(*(t["pts"] - target).T).min())
    p0, p1 = train["pts"][0], train["pts"][-1]
    drawn_ft = train["len_pt"] * scale

    def az_of_dir(dx, dy):
        dxs, dys = dx, -dy
        gx, gy = a * dxs - bb * dys, bb * dxs + a * dys
        return math.degrees(math.atan2(gx, gy)) % 360
    az = az_of_dir(*(p1 - p0))
    want_az = checks.azimuth("S16°20'26\"E")
    im = render(page, region,
                [(region, (220, 0, 0), 3, False),
                 (train["pts"].tolist(), (0, 90, 220), 3, True)],
                ["red: the S16 deg20'26\"E 176.73' / (176.77') citation -- no line on this sheet's own layer, until the dash fix",
                 f"blue: the bridged dashed-layer train, {len(train['pts'])} pts, {drawn_ft:.2f}' (printed 176.73'/176.77', off {drawn_ft - 176.73:+.2f}'/{drawn_ft - 176.77:+.2f}')",
                 f"azimuth {checks.fmt_bearing(az)} vs printed S16°20'26\"E -- bearing passes; distance still short (see legB2 report)"])
    cv2.imwrite(str(OUT / "legB2_dashed.png"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / 'legB2_dashed.png'}  len {drawn_ft:.2f} ft  az {az:.3f} (want {want_az:.3f})")


def nts_crop(page):
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8"))
    labels = {e["text"]: e["region"] for e in exc if e.get("text") in ("10.95'", "156.02'")}
    # OCR reads this caption's "DETAIL \"A\"" / "Scale: = N.T.S." as unrelated CJK/broken fragments on
    # both readers (checked) -- the detector never fires on this instance for a genuine reason (no
    # letters "DETAIL"/"NTS" anywhere in the read text), not a bug in nts_regions(). Patched here with
    # the caption's real text at its real position so the region-building half of the feature (the part
    # checks.py can't reach on this sheet) is still demonstrated and the 2 target labels' containment
    # can be shown honestly.
    patched = blocks + [
        {"cx": 2259.0, "cy": 470.0, "w": 60.0, "h": 12.0, "angle": 0.0, "glyph_h": 8.0, "text": 'DETAIL "A"'},
        {"cx": 2230.0, "cy": 484.0, "w": 90.0, "h": 10.0, "angle": 0.0, "glyph_h": 6.0, "text": "Scale: = N.T.S."},
    ]
    regions = checks.nts_regions(patched, page)
    assert regions, "nts_regions found no region even with the patched caption text"
    x0, y0, x1, y1 = regions[0]
    boxes = [((x0, y0, x1, y1), (0, 200, 0), 4, False)]
    for text, r in labels.items():
        boxes.append((r, (220, 0, 0), 3, False))
    full_region = [min(x0, *[r[0] for r in labels.values()]), min(y0, *[r[1] for r in labels.values()]),
                   max(x1, *[r[2] for r in labels.values()]), max(y1, *[r[3] for r in labels.values()])]
    im = render(page, full_region, boxes,
                ["green: not-to-scale inset region (box, 12 glyph heights -- no dashed-circle drawing found on this sheet)",
                 "red: the 2 labels inside it, 10.95' and 156.02' -- both fall inside the box",
                 "caption OCR-garbled on this sheet (both readers): region reconstructed from the caption's real text/position, not detected live -- see legB report"])
    cv2.imwrite(str(OUT / "legB_nts.png"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / 'legB_nts.png'}")


if __name__ == "__main__":
    page = pymupdf.open(PDF)[0]
    dashed_crop(page)
    nts_crop(page)
