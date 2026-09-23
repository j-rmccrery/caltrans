"""Images for the walkthrough report: the sheet, one tag followed end to end, one queued item, the glyph match.
usage: python spike/report_assets.py  -> docs/img/
"""
import base64
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import checks as C  # noqa: E402
import tags as T  # noqa: E402
from exceptions_page import crop  # noqa: E402
from georef import OUT, READS, PDF  # noqa: E402

IMG = Path(__file__).resolve().parent.parent / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)


def save_b64(b64, name):
    (IMG / name).write_bytes(base64.b64decode(b64))


def main():
    page = pymupdf.open(PDF)[0]
    # 1 the whole sheet, small
    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.6, 0.6), alpha=False)
    pix.save(str(IMG / "sheet.png"))
    # 2 the tag L8 followed: its leader tip and the line it lands on
    tags = json.load(open(OUT / "tags.json", encoding="utf-8"))
    t = next(x for x in tags if x["tag"] == "L8")
    _, circles = C.segments(page)
    paths, lp = C.leaders(page, circles)
    tip = C.tag_leaders([t], paths)[0][0]
    segs = [s for s in C.linework_segments(page, max_gray=0.2) if s[3] not in lp]
    chains = [c for c in C.lines_on_sheet(segs, circles) if c["width"] >= 0.8]
    ln = min(chains, key=lambda c: C.seg_dist(tip, c["p0"], c["p1"]))
    region = [round(t["cx"] - 12), round(t["cy"] - 7), round(t["cx"] + 12), round(t["cy"] + 7)]
    save_b64(crop(page, region, [[float(ln["p0"][0]), float(ln["p0"][1])], [float(ln["p1"][0]), float(ln["p1"][1])]]), "tag_L8.jpg")
    # 3 the table row L8
    pix = page.get_pixmap(matrix=pymupdf.Matrix(4, 4), clip=pymupdf.Rect(2216, 800, 2384, 960), alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    cv2.rectangle(im, (0, int((934 - 800) * 4)), (im.shape[1] - 1, int((950 - 800) * 4)), (220, 0, 0), 3)
    cv2.imwrite(str(IMG / "table_L8.png"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    # 4 the glyph match: the two drawing glyphs of "L8" as bitmaps beside the table exemplars they matched
    blocks = json.load(open(OUT / "read_rapid.json", encoding="utf-8"))
    G = T.glyphs(page)
    X, Y = T.exemplars(G, blocks)
    M = T.Matcher(X, Y)
    near = sorted((i for i, g in enumerate(G) if not g["single"] and np.hypot(*(g["c"] - [t["cx"], t["cy"]])) < 9), key=lambda i: G[i]["c"][0])
    tiles = []
    for i in near[:2]:
        b = T.bitmap(G[i], t["angle"], t["gh"])
        ch, margin = M.classify(b)
        d = M.dist(b[None, :])[0]
        ex = X[int(d.argmin())]
        a = (b.reshape(T.PX, T.PX) * 255).astype(np.uint8); e = (ex.reshape(T.PX, T.PX) * 255).astype(np.uint8)
        pair = np.hstack([255 - cv2.resize(a, (120, 120), interpolation=cv2.INTER_NEAREST), np.full((120, 12), 255, np.uint8), 255 - cv2.resize(e, (120, 120), interpolation=cv2.INTER_NEAREST)])
        pair = cv2.cvtColor(pair, cv2.COLOR_GRAY2BGR)
        cv2.putText(pair, f"drawing", (8, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1, cv2.LINE_AA)
        cv2.putText(pair, f"table '{ch}'  d={d.min():.1f}", (140, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1, cv2.LINE_AA)
        tiles.append(pair)
    cv2.imwrite(str(IMG / "glyph_L8.png"), np.vstack([tiles[0], np.full((10, tiles[0].shape[1], 3), 255, np.uint8), tiles[1]]))
    # 5 a queued tag: L3, eight lines beside it and no leader
    q = next(x for x in json.load(open(OUT / "tags_queue.json", encoding="utf-8")) if x["tag"] == "L3")
    save_b64(crop(page, q["region"]), "queue_L3.jpg")
    # 6 a genuine small disagreement from the exception queue (the first one)
    e = next(x for x in json.load(open(OUT / "exceptions.json", encoding="utf-8")) if "line" in x and abs(x.get("off_ft", 99)) <= 5)
    save_b64(crop(page, e["region"], e["line"]), "disagree.jpg")
    print("assets:", sorted(p.name for p in IMG.iterdir()), "| L8 line", round(ln["len_pt"] * 1.38886, 2), "ft | disagreement", e["text"], e.get("drawn_ft"), e.get("off_ft"))


if __name__ == "__main__":
    main()
