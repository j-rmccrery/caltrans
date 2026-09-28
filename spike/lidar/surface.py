"""One "highway surface" per LiDAR tile: pavement (at grade) union deck (structure), clipped to the
union of every sheet's R/W faces on that tile, dissolved so there are no seams between sheets.

Reads each sheet's extracted_features.geojson (pavement, viaduct deck) and parcels.geojson (R/W faces,
same filter extract.py uses), both already in the sheet's own out dir. Run once per tile, after every
sheet on that tile has had lidar/extract.py run -- spike/demo.py --six does this.
Output: spike/out/tiles/<tile>/highway_surface.geojson, kind = "at grade" | "structure".
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import unary_union

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
OUT = ROOT / "spike" / "out"

# Grouping mirrors tiles.py's own sheet->LiDAR-tile routing (GAP_STEMS): R-10434.3 and R-10741.1 sit
# in the gap between the vendor's south/north tiles and are extracted against the 2018 3DEP "gap" tile
# there, so their pavement/deck belong in their own highway-surface output, not folded into south/north
# (loop 11 left the gap tile unwritten; this was the bug -- surface.py just had no "gap" group).
TILE_SHEETS = {
    "south": [OUT, OUT / "r_10434_001_2020-09-16"],
    "north": [OUT / "r_10741_002_2017-02-10", OUT / "r_10741_003_2017-02-10"],
    "gap": [OUT / "r_10434_003_2020-09-16", OUT / "r_10741_001_2017-02-10"],
}


def inputs_mtime(dirs):
    """Latest mtime across every input file this tile's dissolve reads, or None if none exist yet."""
    m = None
    for d in dirs:
        for name in ("parcels.geojson", "extracted_features.geojson"):
            p = d / name
            if p.exists():
                t = p.stat().st_mtime
                m = t if m is None else max(m, t)
    return m


def faces_for(out_dir, to_utm, h):
    """Same R/W-face filter as extract.py: named parcels, plus small unnamed slivers (drops the two big
    unnamed faces that are the world outside the corridor)."""
    p = out_dir / "parcels.geojson"
    if not p.exists():
        return []
    faces = []
    for f in json.loads(p.read_text())["features"]:
        pr = f["properties"]
        if not pr["parcel"] and pr["area_sqft"] > 400000:
            continue
        ll = np.array(f["geometry"]["coordinates"][0]); x, y = to_utm.transform(ll[:, 0], ll[:, 1])
        faces.append(shape({"type": "Polygon", "coordinates": [list(zip(np.asarray(x) + h["dE_m"], np.asarray(y) + h["dN_m"]))]}).buffer(0))
    return faces


def sheet_polys(out_dir, to_utm):
    """pavement + viaduct-deck polygons from this sheet's extracted_features.geojson, in LiDAR-native UTM
    (extract.py wrote them as lon/lat reprojected straight from that frame, no htdp shift -- reverse just the reprojection)."""
    p = out_dir / "extracted_features.geojson"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text())["features"]:
        k = f["properties"]["kind"]
        if k not in ("pavement", "viaduct deck"):
            continue
        xy = np.array(f["geometry"]["coordinates"][0]); x, y = to_utm.transform(xy[:, 0], xy[:, 1])
        g = shape({"type": "Polygon", "coordinates": [list(zip(x, y))]}).buffer(0)
        out.append(("structure" if k == "viaduct deck" else "at grade", g))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip a tile whose highway_surface.geojson is already newer than its inputs")
    args = ap.parse_args()
    h = json.loads((HERE / "htdp.json").read_text())
    to_utm = Transformer.from_crs("EPSG:6318", "EPSG:6339", always_xy=True)
    to_ll = Transformer.from_crs("EPSG:6339", "EPSG:6318", always_xy=True)
    for tile_name, dirs in TILE_SHEETS.items():
        out_path = OUT / "tiles" / tile_name / "highway_surface.geojson"
        if args.fast and out_path.exists():
            in_m = inputs_mtime(dirs)
            if in_m is not None and out_path.stat().st_mtime >= in_m:
                print(f"{tile_name}: skipped (--fast, highway_surface.geojson newer than its inputs)")
                continue
        faces, polys = [], []
        for d in dirs:
            faces += faces_for(d, to_utm, h)
            polys += sheet_polys(d, to_utm)
        if not faces or not polys:
            print(f"{tile_name}: no R/W faces or no extracted features yet, skipping"); continue
        corridor = unary_union(faces)
        structure = unary_union([g for k, g in polys if k == "structure"])
        at_grade = unary_union([g for k, g in polys if k == "at grade"])
        at_grade = at_grade.difference(structure)  # deck wins where the two overlap
        out_feats = []
        for kind, geom in (("structure", structure), ("at grade", at_grade)):
            clipped = geom.intersection(corridor)
            if clipped.is_empty:
                continue
            for g in getattr(clipped, "geoms", [clipped]):
                if g.area < 1 or not hasattr(g, "exterior"):
                    continue
                xy = np.array(g.exterior.coords); lon, lat = to_ll.transform(xy[:, 0], xy[:, 1])
                out_feats.append({"type": "Feature", "properties": {"kind": kind, "area_m2": round(g.area, 1)},
                                   "geometry": {"type": "Polygon", "coordinates": [[[round(a, 7), round(b, 7)] for a, b in zip(lon, lat)]]}})
        out_dir = OUT / "tiles" / tile_name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "highway_surface.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": out_feats}))
        by = {}
        for f in out_feats:
            by.setdefault(f["properties"]["kind"], 0.0)
            by[f["properties"]["kind"]] += f["properties"]["area_m2"]
        print(f"{tile_name}: highway surface " + (", ".join(f"{k} {a:,.0f} m2" for k, a in by.items()) if by else "empty"))


if __name__ == "__main__":
    main()
