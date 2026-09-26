"""Loop4 leg D attempt 2 evidence: the 3 arc/distance passes that vanished under leg C's containing_block
4pt/3-glyph sliver filter (commit ccf08dd) when rerun canonically (read_shx.py --tables) on sheets never
gated against that change -- 2 distance + 1 arc on R-10434.3, 1 arc on Presidio. Red label box, blue the
measured line each got under the BROKEN threshold (from a throwaway snapshot run with that old filter);
caption says what the FIXED (3pt) threshold gives instead.
usage: python spike/legD2_crops.py   (each panel loads the right sheet/out-dir by SHEET internally)
"""
import json
import sys
from pathlib import Path

import cv2
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from legD_crops import tile  # noqa: E402

SCRATCH = Path(r"C:\Users\johnr\AppData\Local\Temp\claude\C--Users-johnr-projects-caltrans\15afd8cb-a5d8-49e1-b455-d593a7ee390b\scratchpad")
ROOT = Path(__file__).resolve().parent.parent


def find(exc_path, kind, needle):
    exc = json.loads(Path(exc_path).read_text(encoding="utf-8"))
    for e in exc:
        if needle in e.get("text", ""):
            return e
    return None


def caption_tile(page, e, note):
    off = e.get("off_ft", e.get("off_arcmin"))
    im = tile(page, e["region"], e.get("line"))
    im = cv2.copyMakeBorder(im, 40, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    line1 = f"{e['text']}  {e['issue']}" if "issue" in e else f"{e['text']}  off {off:+.1f}"
    cv2.putText(im, line1, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(im, note, (4, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 90, 0), 1, cv2.LINE_AA)
    return im


def main():
    panels = []

    pdf3 = ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf"
    page3 = pymupdf.open(pdf3)[0]
    for kind, needle in [("distance", "23.77"), ("distance", "24.98"), ("arc length", "117.64")]:
        e = find(SCRATCH / "r3_broken_exceptions.json", kind, needle)
        panels.append(caption_tile(page3, e, "sliver filter (4pt/3-glyph): broken"))

    from georef import PDF as PRESIDIO_PDF  # default sheet when SHEET unset
    pagep = pymupdf.open(PRESIDIO_PDF)[0]
    e = find(SCRATCH / "presidio_broken_exceptions.json", "arc length", "171.66")
    panels.append(caption_tile(pagep, e, "sliver filter (4pt/3-glyph): broken"))

    H = max(t.shape[0] for t in panels)
    W = max(t.shape[1] for t in panels)
    panels = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in panels]
    import numpy as np
    grid = np.hstack(panels)
    out = ROOT / "spike" / "out" / "legD2_lost.png"
    cv2.imwrite(str(out), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print(f"wrote {out} ({grid.shape[1]}x{grid.shape[0]})")


if __name__ == "__main__":
    main()
