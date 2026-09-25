"""Loop5 legA south bearing attribution: 12 crops of failing bearing labels per sheet (largest |off|
in arcminutes; no-line exceptions fill out if fewer than 12 FAIL rows), red label box + blue measured
line (no line drawn for a no-line exception). Reuses legD_crops.py's caption_tile/tile layout.
usage: [SHEET=<pdf>] python spike/leg5A_crops.py [out_name]
  -> spike/out[/<sheet>]/leg5A_bearings.png (or out_name if given)
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from leg4_crops import tile  # noqa: E402


def bearing_exceptions():
    exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8"))
    fails = [e for e in exc if e.get("kind") == "bearing" and "off_arcmin" in e]
    no_line = [e for e in exc if e.get("kind") == "bearing" and "no line" in e.get("issue", "")]
    fails.sort(key=lambda e: abs(e["off_arcmin"]), reverse=True)
    picks = fails[:12]
    if len(picks) < 12:
        picks += no_line[: 12 - len(picks)]
    return picks, len(fails), len(no_line)


def caption_tile(page, e):
    im = tile(page, e["region"], e.get("line"))
    if "off_arcmin" in e:
        label = f"{e['text']}  off {e['off_arcmin']:+.1f}'  drawn {e.get('drawn', '')}"
    else:
        label = f"{e['text']}  {e.get('issue', 'no line')}"
    im = cv2.copyMakeBorder(im, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def grid(page, picks, out_name):
    tiles = [caption_tile(page, e) for e in picks]
    cols = 3
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    blank = np.full((H, W, 3), 255, np.uint8)
    while len(tiles) % cols:
        tiles.append(blank)
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    g = np.vstack(rows)
    cv2.imwrite(str(OUT / out_name), cv2.cvtColor(g, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / out_name} ({g.shape[1]}x{g.shape[0]})")
    for e in picks:
        off = e.get("off_arcmin")
        print(f"  {e['text']:>16}  off {off if off is None else f'{off:+.1f}'}  region {e['region']}")


def main():
    page = pymupdf.open(PDF)[0]
    out_name = sys.argv[1] if len(sys.argv) > 1 else "leg5A_bearings.png"
    picks, nfail, nnoline = bearing_exceptions()
    print(f"{nfail} bearing FAIL rows, {nnoline} no-line bearing exceptions -> {len(picks)} picks")
    grid(page, picks, out_name)


if __name__ == "__main__":
    main()
