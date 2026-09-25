"""Loop5 legA gate evidence: 8 bearing labels that flipped FAIL->pass after the local-direction fix,
picked across the three south sheets, red label box + blue measured line, captioned with sheet + printed
+ drawn. usage: python spike/leg5A_passes.py -> spike/out/leg5A_passes.png
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from leg4_crops import tile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "spike" / "out"
SHEETS = {
    "presidio": (None, OUT / "labels.json"),
    "r10434_1": (ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf", OUT / "r_10434_001_2020-09-16" / "labels.json"),
    "r10434_3": (ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf", OUT / "r_10434_003_2020-09-16" / "labels.json"),
}
# (sheet, printed, region) picked from the flipped-pass set (labels.json ok=True now, ok=False baseline)
PICKS = [
    ("presidio", "N86°55'35\"E", (1422, 802, 1476, 822)),
    ("presidio", "N74°16'42\"W", (1195, 534, 1251, 554)),
    ("presidio", "S67°59'11\"E", (1115, 739, 1165, 761)),
    ("presidio", "N67°37'21\"W", (1190, 737, 1258, 770)),
    ("r10434_1", "S87°54'05\"E", (344, 1056, 411, 1089)),
    ("r10434_1", "S87°54'05\"E", (338, 1131, 395, 1157)),
    ("r10434_3", "S42°29'20\"E", (1765, 738, 1821, 752)),
    ("r10434_3", "S72°36'26\"W", (2034, 172, 2102, 193)),
]


def caption_tile(page, sheet, l):
    im = tile(page, l["region"], l.get("line"))
    label = f"{sheet}  {l['printed']}  ok={l['ok']}"
    im = cv2.copyMakeBorder(im, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label, (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def main():
    import georef
    pages = {}
    tiles = []
    for sheet, printed, region in PICKS:
        pdf, labels_path = SHEETS[sheet]
        if sheet not in pages:
            p = pdf if pdf else georef.DEFAULT
            pages[sheet] = pymupdf.open(p)[0]
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        match = next(l for l in labels if l["kind"] == "bearing" and l["printed"] == printed and tuple(l["region"]) == region)
        assert match["ok"], f"{sheet} {printed} {region} is not passing"
        tiles.append(caption_tile(pages[sheet], sheet, match))
    cols = 4
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    g = np.vstack(rows)
    out = OUT / "leg5A_passes.png"
    cv2.imwrite(str(out), cv2.cvtColor(g, cv2.COLOR_RGB2BGR))
    print(f"wrote {out} ({g.shape[1]}x{g.shape[0]})")


if __name__ == "__main__":
    main()
