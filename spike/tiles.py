"""Sheet -> LiDAR tile mapping and per-tile cache building.

Two tiles on disk (loop 3): south/Presidio (`Sample Data/LiDAR-Point-cloud/`, cache in the
pre-existing `spike/lidar/cache/`) and north/Marin (`Sample Data/LiDAR-Point-cloud/north/`,
cache in `spike/lidar/cache/north/`). A sheet is routed to a tile by its PDF stem; the LiDAR
tail scripts (extract, encroach, export_rasters, overlay) key everything off the tile dict,
not the sheet, once they have it.
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LIDAR = Path(__file__).resolve().parent / "lidar"

# north/Marin stems; r_00071_*/r_00092_* are the 1950s scans (D4 index), placed in a later leg
NORTH_STEMS = {"r_00071_011", "r_00071_020", "r_00071_028", "r_00092_008", "r_00092_009"}


def tile_for(pdf_path):
    """south (Presidio) or north (Marin) tile: {name, laz, dem, cache}."""
    stem = Path(pdf_path).stem
    north = stem.startswith("r_10741_") or stem in NORTH_STEMS
    base = ROOT / "Sample Data" / "LiDAR-Point-cloud" / ("north" if north else "")
    # south cache is the pre-existing spike/lidar/cache/ (170 MB) -- keep reading it, never rebuild it
    cache = (LIDAR / "cache" / "north") if north else (LIDAR / "cache")
    return dict(name="north" if north else "south", laz=base / "points.laz", dem=base / "output.tin.tif", cache=cache)


def ensure_cache(tile):
    """Build this tile's 1 m intensity ortho + bounds and class-6/17 point cache if missing.
    South tile's cache already exists on disk and is left alone (both checks are no-ops for it)."""
    cache = tile["cache"]
    cache.mkdir(parents=True, exist_ok=True)
    ortho, bounds = cache / "ortho_intensity_1m.npy", cache / "ortho_bounds.npy"
    if not (ortho.exists() and bounds.exists()):
        _build_ortho(tile)
    if not (cache / "q4_class6_17_pts.npz").exists():
        _build_class67(tile)


def _build_ortho(tile, res=1.0):
    """1 m mean-intensity ortho + (xmin, xmax, ymin, ymax), lifted from lidar/q2_terrain_check.py
    (RGB dropped: the point cloud carries no camera colour, q2 already found that all-zero)."""
    import laspy
    with laspy.open(tile["laz"]) as f:
        h = f.header
        xmin, ymin, xmax, ymax = h.mins[0], h.mins[1], h.maxs[0], h.maxs[1]
        w, ht = int(np.ceil((xmax - xmin) / res)), int(np.ceil((ymax - ymin) / res))
        n = w * ht
        sumi, cnt = np.zeros(n), np.zeros(n, dtype=np.int64)
        for pts in f.chunk_iterator(2_000_000):
            ix = np.clip(((pts.x - xmin) / res).astype(np.int64), 0, w - 1)
            iy = np.clip(((ymax - pts.y) / res).astype(np.int64), 0, ht - 1)  # row0 = north, matches q2/extract
            flat = iy * w + ix
            sumi += np.bincount(flat, weights=np.asarray(pts.intensity).astype(np.float64), minlength=n)
            cnt += np.bincount(flat, minlength=n)
    intensity = np.zeros(n)
    nz = cnt > 0
    intensity[nz] = sumi[nz] / cnt[nz]
    np.save(tile["cache"] / "ortho_intensity_1m.npy", intensity.reshape(ht, w))
    np.save(tile["cache"] / "ortho_bounds.npy", np.array([xmin, xmax, ymin, ymax]))


def _build_class67(tile):
    """Class-6 (building) and class-17 (bridge deck) points across the whole tile, lifted from
    lidar/q4_encroachment.py -- there it pre-filters to a Presidio-only alignment bbox; here it's
    the whole tile once, cached, so any sheet on this tile can use it without a corridor guess."""
    import laspy
    x6l, y6l, z6l, x17l, y17l, z17l = [], [], [], [], [], []
    with laspy.open(tile["laz"]) as f:
        for pts in f.chunk_iterator(3_000_000):
            cls = np.asarray(pts.classification)
            m6, m17 = cls == 6, cls == 17
            x, y, z = np.asarray(pts.x), np.asarray(pts.y), np.asarray(pts.z)
            x6l.append(x[m6]); y6l.append(y[m6]); z6l.append(z[m6])
            x17l.append(x[m17]); y17l.append(y[m17]); z17l.append(z[m17])
    np.savez(tile["cache"] / "q4_class6_17_pts.npz",
              x6=np.concatenate(x6l), y6=np.concatenate(y6l), z6=np.concatenate(z6l),
              x17=np.concatenate(x17l), y17=np.concatenate(y17l), z17=np.concatenate(z17l))


if __name__ == "__main__":
    # smoke check: routing + both tiles' files present
    south = tile_for("r_10434_002_2020-09-16.pdf")
    north = tile_for("r_10741_002_2017-02-10.pdf")
    assert south["name"] == "south" and north["name"] == "north"
    assert tile_for("r_00071_011.pdf")["name"] == "north"
    for t in (south, north):
        assert t["laz"].exists(), t["laz"]
        assert t["dem"].exists(), t["dem"]
    print("tiles.py: south ->", south["laz"], "| north ->", north["laz"], "OK")
