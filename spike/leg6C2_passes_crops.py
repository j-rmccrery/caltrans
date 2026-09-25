"""Loop6 leg C follow-up gate evidence: 6 labels passing under the CAPPED rule 1 only (not rules 2/3) --
each was FAILing at leg6B-check (flat 3' tolerance) and now passes because its own piece length scales
the tolerance up (capped at 30'). Caption carries the piece length (pt) and the tolerance used, so the
orchestrator can judge the 30' cap directly against the sheet. Red = label region, blue = the piece.
Ad hoc, not part of the pipeline.
usage: python spike/leg6C2_passes_crops.py
"""
import json
import math

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

BEAR_TOL, LINEWORK_W, BEAR_TOL_CAP = 0.05, 0.7, 0.5


def bearing_tol_deg(len_pt):
    return min(max(BEAR_TOL, math.degrees(math.atan2(LINEWORK_W, max(len_pt, 1e-6)))), BEAR_TOL_CAP)


PICKS = [
    ("presidio", "N77°38'06\"W", [2016, 446, 2069, 465]),
    ("presidio", "N19°13'28\"W", [2104, 523, 2157, 547]),
    ("presidio", "S38°34'36\"W", [1619, 483, 1688, 515]),
    ("r10434_3", "N78°52'33\"E", [1089, 469, 1145, 493]),
    ("r10434_3", "S69°28'24\"W", [1700, 295, 1763, 321]),
    ("r10434_1", "S2°05'55\"W", [290, 1039, 343, 1055]),
]


def find(labels, text, region):
    return next(la for la in labels if la["kind"] == "bearing" and la["printed"] == text and la["region"] == region)


def main():
    pages = {s: pymupdf.open(p)[0] for s, p in SHEETS.items()}
    tiles = []
    for sheet, text, region in PICKS:
        labels = json.loads((OUTDIR[sheet] / "labels.json").read_text(encoding="utf-8"))
        la = find(labels, text, region)
        p0, p1 = la["line"][0], la["line"][-1]
        len_pt = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        tol = bearing_tol_deg(len_pt)
        caption = f"{sheet} {text} -- {len_pt:.1f}pt, tol {tol * 60:.1f}'"
        tiles.append(tile(pages[sheet], la, caption, color=(220, 90, 0)))
        print(sheet, text, "len_pt", round(len_pt, 1), "tol_arcmin", round(tol * 60, 1))
    rows = [hstack_pad(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
    grid = vstack_pad(rows)
    out = ROOT / "spike" / "out" / "leg6C_passes.png"
    cv2.imwrite(str(out), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print("wrote", out, grid.shape)


if __name__ == "__main__":
    main()
