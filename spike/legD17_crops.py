"""Loop17 leg D: gate-evidence crops -- for a handful of the rows that gained a record bearing (the
fix_bearing_symbols degree/case regex fix) and the compound-curve radius share, render the sheet raster
around the row with the matched drawn line highlighted, so the orchestrator can view before/after
without re-deriving pixel coordinates by hand. One-off script, not part of the bench/pipeline.
usage: SHEET=<pdf> python spike/legD17_crops.py <name> <printed_distance_or_R_marker> [pad_pt]
"""
import json
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
import traverse  # noqa: E402

OUT_RECON = Path(__file__).parent / "out_recon"


def crop_row(name, printed_substr, pad=170):
    edges = traverse.build_edges()
    matches = [e for e in edges if e["kind"] == "line" and printed_substr in e.get("src", "")]
    if not matches:
        print(f"{name}: no edge with '{printed_substr}' in src")
        return
    e = matches[0]
    page = pymupdf.open(PDF)[0]
    px = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (px.width, px.height), px.samples).convert("RGB")
    d = ImageDraw.Draw(img)
    pts = [(p[0] * 2, p[1] * 2) for p in e["pts"]]
    d.line(pts, fill=(0, 170, 0), width=5)
    has_az = "az" in e
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    box = (min(xs) - pad * 2, min(ys) - pad * 2, max(xs) + pad * 2, max(ys) + pad * 2)
    crop = img.crop(tuple(int(v) for v in box))
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    out = OUT_RECON / f"l17D_{name}.png"
    crop.save(out)
    print(f"{name}: src={e['src']!r} has_bearing={has_az} az={e.get('az')} bearing_source={e.get('bearing_source')} -> {out}")


def crop_curve(name, pad=200):
    edges = traverse.build_edges()
    g = json.loads((OUT / "georef.json").read_text())
    scale = g["scale_ft_per_pt"]
    n = traverse.share_curve_radius(edges, scale)
    print(f"{name}: share_curve_radius filled {n}")
    arcs = [e for e in edges if e["kind"] == "arc"]
    page = pymupdf.open(PDF)[0]
    px = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (px.width, px.height), px.samples).convert("RGB")
    d = ImageDraw.Draw(img)
    colors = [(0, 170, 0), (200, 0, 0), (0, 90, 220)]
    allxs, allys = [], []
    for i, e in enumerate(arcs):
        pts = [(p[0] * 2, p[1] * 2) for p in e["pts"]]
        d.line(pts, fill=colors[i % len(colors)], width=4 if i else 7)
        allxs += [p[0] for p in pts]; allys += [p[1] for p in pts]
        print(f"  edge[{i}] src={e['src']!r} R={e.get('R')} R_source={e.get('R_source')}")
    box = (min(allxs) - pad * 2, min(allys) - pad * 2, max(allxs) + pad * 2, max(allys) + pad * 2)
    crop = img.crop(tuple(int(v) for v in box))
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    out = OUT_RECON / f"l17D_{name}.png"
    crop.save(out)
    print(f"  -> {out}")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "curve":
        crop_curve(sys.argv[2])
    else:
        crop_row(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 170)
