"""Q5: flightline overlap QA on ground-class points. 2m mean-Z grid per flightline,
dz between flightlines in overlap cells, with/without DEM-slope>10deg exclusion.
Plus one classification-consistency check.
"""
import os
import itertools
import numpy as np
import laspy
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = r"C:\Users\johnr\projects\caltrans"
LAZ = BASE + r"\Sample Data\LiDAR-Point-cloud\points.laz"
DEM = BASE + r"\Sample Data\LiDAR-Point-cloud\output.tin.tif"
CACHE = BASE + r"\spike\lidar\cache"
OUT = BASE + r"\spike\lidar\out"
RES = 2.0  # metre grid

with laspy.open(LAZ) as f:
    h = f.header
    xmin, ymin = float(h.mins[0]), float(h.mins[1])
    xmax, ymax = float(h.maxs[0]), float(h.maxs[1])
w = int(np.ceil((xmax - xmin) / RES))
hgt = int(np.ceil((ymax - ymin) / RES))
ncells = w * hgt
print(f"grid {w} x {hgt} = {ncells} cells at {RES} m")


def cell_index(x, y):
    ix = np.clip(((x - xmin) / RES).astype(np.int64), 0, w - 1)
    iy = np.clip(((ymax - y) / RES).astype(np.int64), 0, hgt - 1)  # row0 = north
    return iy * w + ix


cache_p1 = os.path.join(CACHE, "q5_pass1.npz")
if os.path.exists(cache_p1):
    d = np.load(cache_p1)
    flightlines = d["flightlines"]
    sumz = d["sumz"]
    cnt = d["cnt"]
    min_z_flat = d["min_z_flat"]
    n_ground = int(d["n_ground"])
else:
    # discover flightline ids on the fly
    fl_sumz, fl_cnt = {}, {}
    min_z_flat = np.full(ncells, np.inf)
    n_ground = 0
    with laspy.open(LAZ) as f:
        for pts in f.chunk_iterator(3_000_000):
            g = np.asarray(pts.classification) == 2
            if not np.any(g):
                continue
            x, y, z = np.asarray(pts.x)[g], np.asarray(pts.y)[g], np.asarray(pts.z)[g]
            psid = np.asarray(pts.point_source_id)[g]
            n_ground += len(x)
            idx = cell_index(x, y)
            np.minimum.at(min_z_flat, idx, z)
            for fl in np.unique(psid):
                m = psid == fl
                if fl not in fl_sumz:
                    fl_sumz[fl] = np.zeros(ncells)
                    fl_cnt[fl] = np.zeros(ncells, dtype=np.int64)
                fl_sumz[fl] += np.bincount(idx[m], weights=z[m], minlength=ncells)
                fl_cnt[fl] += np.bincount(idx[m], minlength=ncells)
    flightlines = np.array(sorted(fl_sumz))
    sumz = np.stack([fl_sumz[fl] for fl in flightlines])
    cnt = np.stack([fl_cnt[fl] for fl in flightlines])
    np.savez(cache_p1, flightlines=flightlines, sumz=sumz, cnt=cnt, min_z_flat=min_z_flat, n_ground=n_ground)

print(f"ground-class points scanned: {n_ground}")
print(f"flightlines found: {list(flightlines)}")

meanz = np.full_like(sumz, np.nan)
nz = cnt > 0
for i in range(len(flightlines)):
    meanz[i][nz[i]] = sumz[i][nz[i]] / cnt[i][nz[i]]

# --- classification consistency: fraction of ground pts > 0.3m above local min-Z in 2m cell ---
cache_p2 = os.path.join(CACHE, "q5_pass2.npy")
if os.path.exists(cache_p2):
    n_above = int(np.load(cache_p2))
else:
    n_above = 0
    with laspy.open(LAZ) as f:
        for pts in f.chunk_iterator(3_000_000):
            g = np.asarray(pts.classification) == 2
            if not np.any(g):
                continue
            x, y, z = np.asarray(pts.x)[g], np.asarray(pts.y)[g], np.asarray(pts.z)[g]
            idx = cell_index(x, y)
            n_above += int(np.sum(z > (min_z_flat[idx] + 0.3)))
    np.save(cache_p2, n_above)

print()
print("=== Classification-consistency check ===")
print(f"ground-class points > 0.3 m above local min-Z in their {RES:.0f}m cell: "
      f"{n_above} / {n_ground} = {100*n_above/n_ground:.2f}%")

# --- DEM slope (degrees) resampled to 2m grid ---
with rasterio.open(DEM) as ds:
    dem = ds.read(1).astype(np.float32)
    nodata = ds.nodata
    dem_m = np.where(dem == nodata, np.nan, dem)
    px = ds.transform.a
    gy, gx = np.gradient(dem_m, px)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
    dem_transform = ds.transform

# cell centers
jj, ii = np.meshgrid(np.arange(w), np.arange(hgt))
cx = xmin + (jj + 0.5) * RES
cy = ymax - (ii + 0.5) * RES
rows, cols = rasterio.transform.rowcol(dem_transform, cx.ravel(), cy.ravel())
rows = np.clip(np.array(rows), 0, dem.shape[0] - 1)
cols = np.clip(np.array(cols), 0, dem.shape[1] - 1)
slope_grid = slope_deg[rows, cols].reshape(hgt, w).ravel()
steep = slope_grid > 10  # boolean, flat-cell index aligned with flat cell idx above

print()
print("=== Flightline overlap dz (ground class, 2m grid) ===")
pairs = list(itertools.combinations(range(len(flightlines)), 2))
maxabs_dz_map = np.full(ncells, np.nan)
for i, j in pairs:
    both = nz[i] & nz[j]
    if both.sum() == 0:
        continue
    dz_all = meanz[i][both] - meanz[j][both]
    steep_here = steep[both]

    def stats(dz):
        if len(dz) == 0:
            return None
        return dict(n=len(dz), mean=float(np.mean(dz)), median=float(np.median(dz)),
                    rmse=float(np.sqrt(np.mean(dz ** 2))), p95_abs=float(np.percentile(np.abs(dz), 95)))

    s_all = stats(dz_all)
    s_flat = stats(dz_all[~steep_here])
    fi, fj = flightlines[i], flightlines[j]
    print(f"pair {fi}-{fj}: overlap cells={s_all['n']}")
    print(f"  WITHOUT slope excl: mean={s_all['mean']:+.3f} median={s_all['median']:+.3f} "
          f"rmse={s_all['rmse']:.3f} p95|dz|={s_all['p95_abs']:.3f} (m)")
    if s_flat:
        print(f"  WITH slope>10deg excluded ({s_flat['n']} cells kept): mean={s_flat['mean']:+.3f} "
              f"median={s_flat['median']:+.3f} rmse={s_flat['rmse']:.3f} p95|dz|={s_flat['p95_abs']:.3f} (m)")
    else:
        print("  WITH slope>10deg excluded: 0 cells remain")

    idxs = np.where(both)[0]
    cur = maxabs_dz_map[idxs]
    absdz = np.abs(dz_all)
    better = np.isnan(cur) | (absdz > cur)
    maxabs_dz_map[idxs[better]] = absdz[better]

n_overlap_any = int(np.sum(nz.sum(axis=0) >= 2))
print()
print(f"cells covered by 2+ flightlines (any pair): {n_overlap_any}")

# --- map PNG: max |dz| across all pairs, per cell ---
os.makedirs(OUT, exist_ok=True)
dz_img = maxabs_dz_map.reshape(hgt, w)
ext = (xmin, xmax, ymin, ymax)
fig, ax = plt.subplots(figsize=(12, 6))
im = ax.imshow(dz_img, extent=ext, origin="upper", cmap="RdYlBu_r", vmin=0, vmax=np.nanpercentile(dz_img, 99))
plt.colorbar(im, ax=ax, label="max |dz| across flightline pairs (m)")
ax.set_title(f"Q5 flightline overlap: max |dz| per {RES:.0f}m cell (ground class)")
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_aspect("equal")
plt.tight_layout()
plt.savefig(os.path.join(OUT, "q5_flightline_overlap_dz.png"), dpi=150)
plt.close(fig)
print("wrote q5_flightline_overlap_dz.png")
print("DONE Q5")
