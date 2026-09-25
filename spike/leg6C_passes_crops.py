"""Loop6 leg C gate evidence: 6 newly-passing labels, two per rule --
  rule 1 (scaled bearing tolerance): r10434_1 N74*57'51"W
  rule 2 (chord citation beside a curve): presidio N75*41'44"W, r10434_1 S87*54'05"E,
    r10434_3 S87*48'20"E, r10434_3 S69*16'16"W (all 4 of rule 2's fires)
  rule 3 (wrong parallel neighbour): presidio N74*18'38"W
Red = label region, blue = the line/chord checks.py now measures. Ad hoc, not part of the pipeline.
usage: python spike/leg6C_passes_crops.py
"""
import json
from pathlib import Path

import cv2
import pymupdf

from leg6B_crops import tile, hstack_pad, vstack_pad, ROOT

SHEETS = {
    "presidio": ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf",
    "r10434_1": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf",
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
}
OUTDIR = {
    "presidio": ROOT / "spike" / "out",
    "r10434_1": ROOT / "spike" / "out" / "r_10434_001_2020-09-16",
    "r10434_3": ROOT / "spike" / "out" / "r_10434_003_2020-09-16",
}

PICKS = [
    ("r10434_1", "bearing", "N74°57'51\"W", "rule 1: scaled tolerance"),
    ("presidio", "bearing", "N74°18'38\"W", "rule 3: wrong parallel neighbour"),
    ("presidio", "chord bearing", "N75°41'44\"W", "rule 2: chord"),
    ("r10434_1", "chord bearing", "S87°54'05\"E", "rule 2: chord (leader)"),
    ("r10434_3", "chord bearing", "S87°48'20\"E", "rule 2: chord"),
    ("r10434_3", "chord bearing", "S69°16'16\"W", "rule 2: chord"),
]


def find(labels, kind, text):
    return next(la for la in labels if la["kind"] == kind and la["printed"] == text)


def main():
    pages = {s: pymupdf.open(p)[0] for s, p in SHEETS.items()}
    tiles = []
    for sheet, kind, text, tag in PICKS:
        labels = json.loads((OUTDIR[sheet] / "labels.json").read_text(encoding="utf-8"))
        la = find(labels, kind, text)
        caption = f"{sheet} {text} -- {tag} [{la['kind']}]"
        tiles.append(tile(pages[sheet], la, caption, color=(220, 90, 0)))
    rows = [hstack_pad(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
    grid = vstack_pad(rows)
    out = ROOT / "spike" / "out" / "leg6C_passes.png"
    cv2.imwrite(str(out), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print("wrote", out, grid.shape)
    for sheet, kind, text, tag in PICKS:
        labels = json.loads((OUTDIR[sheet] / "labels.json").read_text(encoding="utf-8"))
        la = find(labels, kind, text)
        print(sheet, tag, "->", la["kind"], la["printed"], "ok", la["ok"], "how", la["how"], "region", la["region"])


if __name__ == "__main__":
    main()
