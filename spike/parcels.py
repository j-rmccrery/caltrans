"""Parcel polygons from the sheet's heavy linework, checked against the parcel table.

Heavy lines (R/W and parcel boundaries) plus the map border are noded and polygonised; every face
is a candidate parcel. A parcel-number label inside a face names it. Each named face's area
(through the georeferencing fit) is compared with the area printed in the parcel table: a second
deterministic check that touches the whole figure, not one line.
Output: parcels.geojson (lon/lat, WGS84-compatible NAD83(2011)) and a printed area table.
usage: [SHEET=<pdf>] python spike/parcels.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, real_text_blocks  # noqa: E402
from overlay import MAP_AREA, bezier  # noqa: E402

PARCEL = re.compile(r"^(DK-)?(\d{5})(-\d)?$")
SQFT_PER_ACRE = 43560.0
# parcel table on R-10434.2, keyed by hand for the check (areas printed in acres / square feet)
TABLE_AREA = {"61806-2": ("AC", 7.21), "61806-4": ("AC", 3.34), "61806-5": ("AC", 5.27), "61806-9": ("SF", 6970),
              "61985-1": ("SF", 2518), "61985-2": ("SF", 15372), "61985-3": ("SF", 49552), "61985-4": ("SF", 3248), "63269": ("AC", 11.45)}


def heavy_lines(page):
    x0, y0, x1, y1 = MAP_AREA
    out = []
    for d in page.get_drawings():
        r, c = d["rect"], d.get("color")
        w = round(d.get("width") or 0, 2)
        if c is None or max(c) > 0.2 or max(r.width, r.height) <= 12:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if not (x0 < cx < x1 and y0 < cy < y1):
            continue
        # R/W lines are 1.98; parcel and easement boundaries share the 0.84 weight with leaders and
        # text, so only long 0.84 paths count. Centreline and hatch edges (0.72) are not boundaries.
        total = sum(np.hypot(it[2].x - it[1].x, it[2].y - it[1].y) for it in d["items"] if it[0] == "l") +             sum(np.hypot(it[4].x - it[1].x, it[4].y - it[1].y) for it in d["items"] if it[0] == "c")
        if w == 0 or total < 12 or (w < 0.8 and total < 40):
            continue  # fills, glyph-sized bits and short thin leaders; dangling leaders cannot close a face anyway
        if d["closePath"] and r.width < 90 and r.height < 24:
            continue  # the rounded box drawn around a parcel number is not a boundary
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                seg = [(it[1].x, it[1].y), (it[2].x, it[2].y)]
            elif it[0] == "c":
                seg = [tuple(p) for p in bezier(*[np.array([p.x, p.y]) for p in it[1:5]])]
            else:
                continue
            if pts and np.hypot(pts[-1][0] - seg[0][0], pts[-1][1] - seg[0][1]) > 0.5:
                out.append(LineString(pts)); pts = []
            pts = (pts[:-1] if pts else []) + seg
        if len(pts) > 1:
            out.append(LineString(pts))
    return out


def close_gaps(lines, gap):
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree
    tree = STRtree(lines)
    extra = []
    for i, ln in enumerate(lines):
        for end in (Point(ln.coords[0]), Point(ln.coords[-1])):
            best = None
            for j in tree.query(end.buffer(gap)):
                if j == i:
                    continue
                d = lines[j].distance(end)
                if 0.05 < d < gap and (best is None or d < best[0]):
                    best = (d, lines[j])
            if best:
                extra.append(LineString([end, nearest_points(end, best[1])[1]]))
    return lines + extra


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    lines = heavy_lines(page)
    x0, y0, x1, y1 = MAP_AREA
    border = LineString([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
    # lines stop short of point-symbol circles and of each other by a few pt: bridge every loose end
    # to the nearest other line within GAP so the figure closes
    lines = close_gaps(lines + [border], gap=9.0)
    noded = unary_union(lines)  # nodes every crossing so faces close
    faces = [f for f in polygonize(noded) if f.area > 400]  # ignore slivers (< ~800 sq ft)
    faces = [f for f in faces if f.bounds[3] - f.bounds[1] > 26 or f.bounds[2] - f.bounds[0] > 130]  # not a parcel-number box (78 x 20 pt)
    print(f"heavy polylines {len(lines)} | faces {len(faces)}")

    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8")) + real_text_blocks(page)
    labels = [(m.group(0), Point(bl["cx"], bl["cy"])) for bl in blocks for m in [PARCEL.match(bl["text"].replace(" ", ""))] if m and not bl.get("real")]
    to_ll = Transformer.from_crs("EPSG:2227", "EPSG:6318", always_xy=True)

    def ground(xy):
        sx, sy = np.asarray(xy)[:, 0], -np.asarray(xy)[:, 1]
        E, N = a * sx - b * sy + tx, b * sx + a * sy + ty
        return E, N

    feats, rows = [], []
    for f in faces:
        names = [n for n, p in labels if f.contains(p)]
        E, N = ground(np.array(f.exterior.coords))
        area_sf = 0.5 * abs(np.dot(E[:-1], N[1:]) - np.dot(N[:-1], E[1:]))
        lon, lat = to_ll.transform(E, N)
        name = names[0] if len(names) == 1 else ("|".join(names) if names else "")
        props = {"parcel": name, "area_sqft": round(area_sf, 1), "area_acres": round(area_sf / SQFT_PER_ACRE, 3), "labels_inside": len(names)}
        if name in TABLE_AREA:
            unit, want = TABLE_AREA[name]
            want_sf = want if unit == "SF" else want * SQFT_PER_ACRE
            props.update(table_area_sqft=want_sf, diff_pct=round((area_sf - want_sf) / want_sf * 100, 2))
            rows.append((name, area_sf, want_sf))
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]]}})
    (OUT / "parcels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    named = [f for f in feats if f["properties"]["parcel"]]
    print(f"named faces {len(named)} of {len(feats)}; labels placed {len(labels)}")
    print(f"{'parcel':10} {'drawn sq ft':>12} {'table sq ft':>12} {'diff':>8}")
    for name, got, want in sorted(rows):
        print(f"{name:10} {got:12,.0f} {want:12,.0f} {(got - want) / want * 100:+7.2f}%")
    unnamed_big = sorted((f["properties"]["area_acres"] for f in feats if not f["properties"]["parcel"]), reverse=True)[:5]
    print("largest unnamed faces (acres):", unnamed_big)


if __name__ == "__main__":
    main()
