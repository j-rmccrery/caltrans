"""Track B on real parcels: building-class LiDAR returns inside the sheet's own right-of-way and
easement polygons, and the terrain over the tunnel easements.

Inputs: spike/out/parcels.geojson (from parcels.py, lon/lat), the LiDAR class-6/17 point cache and
DEM from the lidar spike, the cached HTDP epoch shift. Output: encroachments.geojson (clusters with
parcel, footprint, height, roof-flatness verdict), tunnel_profile.csv, and a printed summary.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).parent))
import tiles as tiles_mod  # noqa: E402
from georef import OUT, PDF  # noqa: E402  (SHEET-aware)

HERE = Path(__file__).parent
TILE = tiles_mod.tile_for(PDF)
CACHE = TILE["cache"]
DEM = TILE["dem"]
TUNNEL = {"61985-1", "61985-2", "61985-3", "61985-4"}


def main():
    tiles_mod.ensure_cache(TILE)
    h = json.loads((HERE / "lidar" / "htdp.json").read_text())  # same epoch shift for both tiles: 2 km apart, drift negligible over that distance
    to_utm = Transformer.from_crs("EPSG:6318", "EPSG:6339", always_xy=True)
    polys, names = [], []
    for f in json.loads((OUT / "parcels.geojson").read_text())["features"]:
        g = shape(f["geometry"])
        xy = np.array(g.exterior.coords)
        x, y = to_utm.transform(xy[:, 0], xy[:, 1])
        polys.append(shape({"type": "Polygon", "coordinates": [list(zip(np.asarray(x) + h["dE_m"], np.asarray(y) + h["dN_m"]))]}))
        names.append(f["properties"]["parcel"] or f"face-{len(names)}")
    tree = STRtree(polys)
    print(f"parcel faces {len(polys)} ({sum(1 for n in names if not n.startswith('face-'))} named)")

    d = np.load(CACHE / "q4_class6_17_pts.npz")
    keys = list(d.keys())
    x6, y6, z6 = (d[k] for k in keys[:3])
    print(f"building-class points {len(x6):,}")
    with rasterio.open(DEM) as ds:
        dem = ds.read(1).astype(np.float32); dem[dem == ds.nodata] = np.nan; T = ds.transform

    def ground(x, y):
        r, c = rasterio.transform.rowcol(T, x, y)
        return dem[np.clip(r, 0, dem.shape[0] - 1), np.clip(c, 0, dem.shape[1] - 1)]

    feats, rows = [], []
    for pi, poly in enumerate(polys):
        if names[pi].startswith("face-") and poly.area > 2e5:
            continue  # the two big unnamed faces are the world outside the corridor
        minx, miny, maxx, maxy = poly.bounds
        m = (x6 >= minx) & (x6 <= maxx) & (y6 >= miny) & (y6 <= maxy)
        if not m.any():
            continue
        inside = np.array([poly.contains(Point(px, py)) for px, py in zip(x6[m], y6[m])])
        xs, ys, zs = x6[m][inside], y6[m][inside], z6[m][inside]
        if len(xs) < 3:
            continue
        gx0, gy0 = xs.min() - 1, ys.min() - 1
        ix, iy = (xs - gx0).astype(int), (ys - gy0).astype(int)
        grid = np.zeros((iy.max() + 2, ix.max() + 2), bool); grid[iy, ix] = True
        lab, n = ndimage.label(grid, structure=np.ones((3, 3)))
        pl = lab[iy, ix]
        for k in range(1, n + 1):
            pm = pl == k
            if pm.sum() < 3:
                continue
            cx, cy = xs[pm].mean(), ys[pm].mean()
            foot = int((lab == k).sum())
            height = float(zs[pm].max() - ground(np.array([cx]), np.array([cy]))[0])
            cells = iy[pm] * grid.shape[1] + ix[pm]
            top = {}
            for c_, z_ in zip(cells, zs[pm]):
                top[c_] = max(top.get(c_, -1e9), z_)
            tops = np.array(list(top.values()))
            flat = float(np.mean(np.abs(tops - np.median(tops)) < 1.0))
            verdict = "building" if foot >= 20 and 2.5 <= height <= 25 and flat >= 0.6 else "vegetation/terrain (filtered)"
            rows.append((names[pi], foot, height, flat, verdict))
            lon, lat = Transformer.from_crs("EPSG:6339", "EPSG:6318", always_xy=True).transform(cx - h["dE_m"], cy - h["dN_m"])
            feats.append({"type": "Feature", "properties": {"parcel": names[pi], "footprint_m2": foot, "points": int(pm.sum()), "height_m": round(height, 2), "flat_top": round(flat, 2), "verdict": verdict},
                          "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    (OUT / "encroachments.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"{'parcel':12} {'footprint m2':>12} {'height m':>9} {'flat':>5}  verdict")
    for r in sorted(rows, key=lambda r: (r[4] != "building", -r[1])):
        print(f"{r[0]:12} {r[1]:12} {r[2]:9.2f} {r[3]:5.2f}  {r[4]}")
    print(f"building-like clusters inside named parcels: {sum(r[4] == 'building' and not r[0].startswith('face-') for r in rows)}")

    # terrain over the tunnel easements: ground elevation along each polygon's long axis
    with open(OUT / "tunnel_profile.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["parcel", "station_m", "x", "y", "ground_m"])
        for pi, poly in enumerate(polys):
            # a face's name can be several labels joined by "|" (parcels.py containment union,
            # leg 4/5): match any TUNNEL member, not the whole joined string.
            hit = [n for n in names[pi].split("|") if n in TUNNEL]
            if not hit:
                continue
            mr = poly.minimum_rotated_rectangle
            c = np.array(mr.exterior.coords)[:4]
            e = [(c[i], c[(i + 1) % 4]) for i in range(2)]
            a, b = max(e, key=lambda s: np.hypot(*(s[1] - s[0])))
            mid = (np.array(mr.exterior.coords)[:4].mean(axis=0))
            L = np.hypot(*(b - a)); u = (b - a) / L
            zs = []
            for s in np.arange(0, L, 5.0):
                p = mid + u * (s - L / 2)
                z = float(ground(np.array([p[0]]), np.array([p[1]]))[0]); zs.append(z)
                for n in hit:
                    w.writerow([n, round(s, 1), round(p[0], 2), round(p[1], 2), round(z, 2)])
            print(f"tunnel easement {'+'.join(hit)}: length {L:.0f} m, ground over it {np.nanmin(zs):.1f}-{np.nanmax(zs):.1f} m")


if __name__ == "__main__":
    main()
