"""Loop4 legD wrong-line triage: 12 largest-|off| distance/bearing wrong-line exceptions on
R-10434.3, red label box + blue measured (wrong) line, 3 per row, captioned with printed/off.
Reuses leg4_crops.py's tile() layout.
usage: SHEET="Sample Data/d4/r_10434_003_2020-09-16.pdf" python spike/legD_crops.py [png_name] [--fixed]
  --fixed: instead of the 12 biggest wrong-line fails, render up to 12 labels named on stdin
           (one "kind|printed" per line) as newly-passing/correct-line crops (for the re-bench gate).
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

SMALL = {"distance": 5.0, "bearing": 60.0}


def wrong_line_exceptions():
    exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8"))
    wl = [e for e in exc if e.get("kind") in ("distance", "bearing") and "issue" not in e
          and abs(e.get("off_ft", e.get("off_arcmin", 0))) > SMALL[e["kind"]]]
    wl.sort(key=lambda e: abs(e.get("off_ft", e.get("off_arcmin", 0))), reverse=True)
    return wl


def caption_tile(page, e):
    off = e.get("off_ft", e.get("off_arcmin"))
    unit = "ft" if "off_ft" in e else "'"
    im = tile(page, e["region"], e.get("line"))
    label = f"{e['text']}  off {off:+.1f}{unit}"
    im = cv2.copyMakeBorder(im, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def grid(page, picks, out_name):
    tiles = [caption_tile(page, e) for e in picks]
    n = len(tiles)
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
        off = e.get("off_ft", e.get("off_arcmin"))
        print(f"  {e['kind']:<8} {e['text']:>14}  off {off:+.1f}  region {e['region']}")


def main():
    page = pymupdf.open(PDF)[0]
    out_name = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "legD_wrong.png"
    wl = wrong_line_exceptions()
    print(f"{len(wl)} distance/bearing wrong-line exceptions")
    picks = wl[:12]
    grid(page, picks, out_name)


if __name__ == "__main__":
    main()
