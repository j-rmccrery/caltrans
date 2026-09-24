"""Engineering features from the airborne LiDAR, deterministically, as polygons in the sheet's frame.

What airborne density supports:  pavement surface (ground returns that are dark and flat),
viaduct deck (bridge-deck class), building footprints (building class with a flat top).
What it does not: curbs, signs, monuments, edge of pavement to survey grade - that is mobile LiDAR.

Every feature is a raster decision on a 1 m grid, then polygonised; no model, so every polygon can be
traced to the rule and the returns that made it. Then the record is checked against the ground:
how much pavement lies outside the sheet's right-of-way faces, and how far the pavement edge sits
from the drawn R/W line. Outputs spike/out/extracted_features.geojson and printed numbers.
"""
import json
import sys
from pathlib import Path

import laspy
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio import features
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import shape, mapping, LineString, MultiLineString
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent.parent))
import tiles as tiles_mod  # noqa: E402
from georef import OUT, PDF  # noqa: E402  (SHEET-aware)

HERE = Path(__file__).parent
TILE = tiles_mod.tile_for(PDF)
CACHE = TILE["cache"]
LAZ = TILE["laz"]
DEM = TILE["dem"]
CELL = 1.0


def grids():
    """Per 1 m cell: ground-return count, mean ground intensity, bridge-deck count, building count and max z."""
    p = CACHE / "extract_grids.npz"
    if p.exists():
        return dict(np.load(p))
    with laspy.open(LAZ) as f:
        h = f.header
        x0, y0 = np.floor(h.mins[0]), np.floor(h.mins[1])
        W, H = int(np.ceil(h.maxs[0] - x0)) + 1, int(np.ceil(h.maxs[1] - y0)) + 1
        n = W * H
        g_cnt = np.zeros(n); g_int = np.zeros(n); b17 = np.zeros(n); b6 = np.zeros(n); z6 = np.full(n, -1e9); z2 = np.zeros(n); w9 = np.zeros(n)
        for pts in f.chunk_iterator(3_000_000):
            ix = ((pts.x - x0) / CELL).astype(int); iy = ((pts.y - y0) / CELL).astype(int)
            flat = iy * W + ix
            c = np.asarray(pts.classification)
            m = c == 2
            g_cnt += np.bincount(flat[m], minlength=n)
            g_int += np.bincount(flat[m], weights=np.asarray(pts.intensity)[m].astype(float), minlength=n)
            z2 += np.bincount(flat[m], weights=np.asarray(pts.z)[m], minlength=n)
            b17 += np.bincount(flat[c == 17], minlength=n)
            b6 += np.bincount(flat[c == 6], minlength=n)
            w9 += np.bincount(flat[c == 9], minlength=n)
            m6 = c == 6
            np.maximum.at(z6, flat[m6], np.asarray(pts.z)[m6])
        out = dict(x0=x0, y0=y0, W=W, H=H, g_cnt=g_cnt.reshape(H, W), g_int=(g_int / np.maximum(g_cnt, 1)).reshape(H, W),
                   g_z=(z2 / np.maximum(g_cnt, 1)).reshape(H, W), b17=b17.reshape(H, W), b6=b6.reshape(H, W), z6=z6.reshape(H, W), w9=w9.reshape(H, W))
        np.savez(p, **out)
        return out


def polygons(mask, transform, min_cells, to_ll, kind, **props):
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    keep = np.isin(lab, [i for i in range(1, n + 1) if (lab == i).sum() >= min_cells])
    feats = []
    for geom, v in features.shapes(keep.astype(np.uint8), mask=keep, transform=transform):
        g = shape(geom).simplify(0.5)
        if g.is_empty:
            continue
        xy = np.array(g.exterior.coords)
        lon, lat = to_ll.transform(xy[:, 0], xy[:, 1])
        feats.append({"type": "Feature", "properties": {"kind": kind, "area_m2": round(g.area, 1), **props},
                      "geometry": {"type": "Polygon", "coordinates": [[[round(a, 7), round(b, 7)] for a, b in zip(lon, lat)]]}, "_utm": g})
    return feats


def main():
    tiles_mod.ensure_cache(TILE)  # ortho + class67 cache render() needs; extract_grids.npz is built by grids() below
    G = grids()
    x0, y0, W, H = float(G["x0"]), float(G["y0"]), int(G["W"]), int(G["H"])
    # rasters are stored with row 0 at the south edge; flip to north-up for rasterio
    flip = lambda a: a[::-1]
    T = from_origin(x0, y0 + H * CELL, CELL, CELL)
    to_ll = Transformer.from_crs("EPSG:6339", "EPSG:6318", always_xy=True)

    g_cnt, g_int, g_z = flip(G["g_cnt"]), flip(G["g_int"]), flip(G["g_z"])
    gy, gx = np.gradient(np.where(g_cnt > 0, g_z, np.nan))
    slope = np.degrees(np.arctan(np.hypot(np.nan_to_num(gx), np.nan_to_num(gy))))
    vals = g_int[(g_cnt >= 3)]
    # asphalt is the dark end of the ground-intensity histogram: Otsu split of ground intensity
    hist, edges = np.histogram(vals, bins=256)
    p = hist / hist.sum(); w0 = np.cumsum(p); w1 = 1 - w0
    mids = (edges[:-1] + edges[1:]) / 2
    m0 = np.cumsum(p * mids) / np.maximum(w0, 1e-9); m1 = (np.sum(p * mids) - np.cumsum(p * mids)) / np.maximum(w1, 1e-9)
    thr = mids[np.argmax(w0 * w1 * (m0 - m1) ** 2)]
    water = ndimage.binary_dilation(flip(G["w9"]) > 0, iterations=25)  # the Bay and the lagoon are dark and flat too
    pave = (g_cnt >= 3) & (g_int < thr) & (slope < 6) & ~water
    pave = ndimage.binary_opening(pave, iterations=1)
    pave = ndimage.binary_closing(pave, iterations=2)
    print(f"ground intensity Otsu threshold {thr:.0f}; dark flat dry ground {pave.sum():,} m²")

    deck = flip(G["b17"]) >= 2
    deck = ndimage.binary_closing(deck, iterations=1)
    b6, z6 = flip(G["b6"]), flip(G["z6"])
    bld = b6 >= 3
    bld = ndimage.binary_opening(bld, iterations=1)

    # only pavement connected to the state highway corridor is this sheet's business
    h = json.loads((HERE / "htdp.json").read_text())  # same epoch shift for both tiles: 2 km apart, drift negligible over that distance
    to_utm = Transformer.from_crs("EPSG:6318", "EPSG:6339", always_xy=True)
    faces = []
    for f in json.loads((OUT / "parcels.geojson").read_text())["features"]:
        pr = f["properties"]
        if not pr["parcel"] and pr["area_sqft"] > 400000:
            continue
        ll = np.array(f["geometry"]["coordinates"][0]); x, y = to_utm.transform(ll[:, 0], ll[:, 1])
        faces.append(shape({"type": "Polygon", "coordinates": [list(zip(np.asarray(x) + h["dE_m"], np.asarray(y) + h["dN_m"]))]}).buffer(0))
    corridor = unary_union(faces)
    cmask = features.rasterize([(mapping(corridor.buffer(30)), 1)], out_shape=(H, W), transform=T).astype(bool)
    lab, n = ndimage.label(pave, structure=np.ones((3, 3)))
    touching = np.unique(lab[cmask & pave]); touching = touching[touching > 0]
    pave = np.isin(lab, touching)
    print(f"pavement connected to the corridor: {pave.sum():,} m² in {len(touching)} components")

    feats = []
    feats += polygons(pave, T, 400, to_ll, "pavement", rule=f"ground class, intensity < {thr:.0f} (Otsu), slope < 6 deg, >= 3 returns, not water, connected to the R/W corridor")
    feats += polygons(deck, T, 30, to_ll, "viaduct deck", rule="bridge-deck class, >= 2 returns")
    for f in polygons(bld, T, 20, to_ll, "building", rule="building class, >= 3 returns, footprint >= 20 m2"):
        g = f["_utm"]
        # roof flatness from the max-z grid inside the footprint
        rmask = features.rasterize([(mapping(g), 1)], out_shape=(H, W), transform=T).astype(bool)
        tops = z6[rmask & (z6 > -1e8)]
        flat = float(np.mean(np.abs(tops - np.median(tops)) < 1.0)) if len(tops) else 0.0
        ground = float(np.nanmedian(np.where(g_cnt > 0, g_z, np.nan)[rmask])) if rmask.any() else float("nan")
        f["properties"].update(flat_top=round(flat, 2), height_m=round(float(np.nanmax(tops) - ground), 2) if len(tops) else None,
                               verdict="building" if flat >= 0.6 else "vegetation/terrain (filtered)")
        feats.append(f)
    for f in feats:
        f.pop("_utm", None)
    render(pave, deck, bld, T, corridor)
    (OUT / "extracted_features.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    by = {}
    for f in feats:
        k = f["properties"]["kind"]; by.setdefault(k, [0, 0.0]); by[k][0] += 1; by[k][1] += f["properties"]["area_m2"]
    for k, (n, a) in by.items():
        print(f"  {k:14} {n:4} polygons  {a:12,.0f} m²")
    print(f"  buildings passing the roof test: {sum(1 for f in feats if f['properties'].get('verdict') == 'building')}")

    # record against ground: pavement vs the sheet's right-of-way faces
    pav_polys = [shape({"type": "Polygon", "coordinates": [[to_utm.transform(a, b) for a, b in f["geometry"]["coordinates"][0]]]}).buffer(0) for f in feats if f["properties"]["kind"] == "pavement"]
    pav = unary_union(pav_polys)
    near = pav.intersection(corridor.buffer(15))  # the highway itself: pavement on or within 15 m of the R/W faces
    if near.is_empty or near.area == 0:
        # sheet's corridor has no LiDAR pavement nearby -- e.g. it sits outside this tile's coverage; nothing to check
        print("pavement on or near the state right-of-way: none (sheet corridor has no LiDAR coverage here)")
    else:
        inside = near.intersection(corridor).area
        print(f"pavement on or near the state right-of-way: {near.area:,.0f} m²; {inside / near.area:.1%} inside the drawn R/W faces, "
              f"{near.area - inside:,.0f} m² lies outside them within 15 m (record-vs-ground exceptions to review)")
        rw = []
        for f in json.loads((OUT / "sheet_linework.geojson").read_text())["features"]:
            if f["properties"]["weight"] == "heavy":
                xy = np.array(f["geometry"]["coordinates"]); x, y = to_utm.transform(xy[:, 0], xy[:, 1])
                rw.append(LineString(zip(np.asarray(x) + h["dE_m"], np.asarray(y) + h["dN_m"])))
        rw = MultiLineString(rw)
        edge = near.boundary
        pts = [edge.interpolate(t, normalized=True) for t in np.linspace(0, 1, 400)]
        d = np.array([rw.distance(q) for q in pts])
        print(f"highway pavement edge to nearest drawn R/W line: median {np.median(d):.1f} m, p10 {np.percentile(d, 10):.1f} m, p90 {np.percentile(d, 90):.1f} m")
    deck_polys = [shape({"type": "Polygon", "coordinates": [[to_utm.transform(a, b) for a, b in f["geometry"]["coordinates"][0]]]}).buffer(0) for f in feats if f["properties"]["kind"] == "viaduct deck"]
    deck_u = unary_union(deck_polys)
    if deck_u.is_empty or deck_u.area == 0:
        print("viaduct deck: none (sheet corridor has no LiDAR coverage here)")
    else:
        print(f"viaduct deck {deck_u.area:,.0f} m²: {deck_u.intersection(corridor).area / deck_u.area:.1%} inside the drawn R/W faces")


def render(pave, deck, bld, T, corridor):
    import cv2
    img = np.load(CACHE / "ortho_intensity_1m.npy")
    xmin, xmax, ymin, ymax = np.load(CACHE / "ortho_bounds.npy")[:4]
    lo, hi = np.percentile(img[img > 0], [2, 98]); base = (np.clip((img - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    im = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    H, W = im.shape[:2]
    def to_px(x, y):
        return ((x - xmin) / (xmax - xmin) * W).astype(int), ((ymax - y) / (ymax - ymin) * H).astype(int)
    for mask, col in ((pave, (0, 200, 255)), (deck, (255, 80, 0)), (bld, (0, 0, 255))):
        rows, cols = np.nonzero(mask)
        xs, ys = rasterio.transform.xy(T, rows, cols)
        px, py = to_px(np.array(xs), np.array(ys))
        ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
        over = im.copy(); over[py[ok], px[ok]] = col; im = cv2.addWeighted(over, 0.55, im, 0.45, 0)
    for g in getattr(corridor, "geoms", [corridor]):
        xy = np.array(g.exterior.coords); px, py = to_px(xy[:, 0], xy[:, 1])
        cv2.polylines(im, [np.c_[px, py].astype(np.int32)], True, (0, 255, 0), 2)
    cv2.imwrite(str(OUT / "extracted_features.png"), im)


if __name__ == "__main__":
    main()
