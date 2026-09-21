"""Q4: rough encroachment screen. Corridor = polyline through alignment pts A,B,D,C,E,G,F,H,
buffered 100ft/200ft. Count+cluster class-6 (building) points inside; report class-17 (bridge deck).
No shapely available/needed: point-to-polyline distance done directly with numpy.
"""
import os
import numpy as np
import laspy
import rasterio
from pyproj import Transformer
from scipy import ndimage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = r"C:\Users\johnr\projects\caltrans"
LAZ = BASE + r"\Sample Data\LiDAR-Point-cloud\points.laz"
DEM = BASE + r"\Sample Data\LiDAR-Point-cloud\output.tin.tif"
CACHE = BASE + r"\spike\lidar\cache"
OUT = BASE + r"\spike\lidar\out"
FT = 0.3048  # m per ft (international foot; survey-foot difference ~2ppm, negligible here)
BUF1, BUF2 = 100 * FT, 200 * FT  # 30.48, 60.96 m

ALIGN_ORDER = ["A", "B", "D", "C", "E", "G", "F", "H"]
ALIGN = {  # (N, E) EPSG:2227 US survey ft
    "A": (2120587.32, 5996020.18), "B": (2120362.99, 5995453.54), "D": (2120398.11, 5995416.40),
    "C": (2120311.94, 5994592.86), "E": (2120369.61, 5994434.65), "G": (2120732.34, 5993150.39),
    "F": (2120760.47, 5993175.86), "H": (2120702.87, 5993114.16),
}
t = Transformer.from_crs("EPSG:2227", "EPSG:6339", always_xy=True)
verts = np.array([t.transform(ALIGN[k][1], ALIGN[k][0]) for k in ALIGN_ORDER])  # (8,2) x,y

seg_a = verts[:-1]
seg_b = verts[1:]
seg_len = np.linalg.norm(seg_b - seg_a, axis=1)
cum_len = np.concatenate([[0], np.cumsum(seg_len)])  # station (m) at each vertex
total_len = cum_len[-1]
print(f"corridor vertices: {ALIGN_ORDER}, total polyline length {total_len:.1f} m")


def dist_and_station(px, py):
    """Min distance (m) from each point to the polyline, and along-corridor station (m) at closest approach."""
    best_d = np.full(px.shape, np.inf)
    best_s = np.zeros(px.shape)
    for i in range(len(seg_a)):
        ax, ay = seg_a[i]
        bx, by = seg_b[i]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        tt = ((px - ax) * dx + (py - ay) * dy) / L2
        tt = np.clip(tt, 0, 1)
        cx, cy = ax + tt * dx, ay + tt * dy
        d = np.hypot(px - cx, py - cy)
        s = cum_len[i] + tt * seg_len[i]
        better = d < best_d
        best_d[better] = d[better]
        best_s[better] = s[better]
    return best_d, best_s


# bounding box for fast prefilter: polyline extent + 200ft buffer + margin
pad = BUF2 + 5
bx0, by0 = verts[:, 0].min() - pad, verts[:, 1].min() - pad
bx1, by1 = verts[:, 0].max() + pad, verts[:, 1].max() + pad
print(f"prefilter bbox: E {bx0:.0f}-{bx1:.0f}  N {by0:.0f}-{by1:.0f}")

cache_npz = os.path.join(CACHE, "q4_class6_17_pts.npz")
if os.path.exists(cache_npz):
    d = np.load(cache_npz)
    x6, y6, z6, x17, y17, z17 = d["x6"], d["y6"], d["z6"], d["x17"], d["y17"], d["z17"]
else:
    x6l, y6l, z6l, x17l, y17l, z17l = [], [], [], [], [], []
    with laspy.open(LAZ) as f:
        for pts in f.chunk_iterator(3_000_000):
            inbb = (pts.x >= bx0) & (pts.x <= bx1) & (pts.y >= by0) & (pts.y <= by1)
            if not np.any(inbb):
                continue
            cls = np.asarray(pts.classification)[inbb]
            xs, ys, zs = np.asarray(pts.x)[inbb], np.asarray(pts.y)[inbb], np.asarray(pts.z)[inbb]
            m6 = cls == 6
            m17 = cls == 17
            x6l.append(xs[m6]); y6l.append(ys[m6]); z6l.append(zs[m6])
            x17l.append(xs[m17]); y17l.append(ys[m17]); z17l.append(zs[m17])
    x6, y6, z6 = np.concatenate(x6l), np.concatenate(y6l), np.concatenate(z6l)
    x17, y17, z17 = np.concatenate(x17l), np.concatenate(y17l), np.concatenate(z17l)
    np.savez(cache_npz, x6=x6, y6=y6, z6=z6, x17=x17, y17=y17, z17=z17)

print(f"class-6 (building) points in bbox: {len(x6)}")
print(f"class-17 (bridge deck) points in bbox: {len(x17)}")

d6, s6 = dist_and_station(x6, y6)
d17, s17 = dist_and_station(x17, y17)

in100 = d6 <= BUF1
in200 = d6 <= BUF2
print(f"class-6 points within 100ft buffer: {in100.sum()}")
print(f"class-6 points within 200ft buffer: {in200.sum()}")

in200_17 = d17 <= BUF2
print(f"class-17 (bridge deck) points within 200ft buffer: {in200_17.sum()} / {len(x17)} total in bbox")
if in200_17.sum() > 0:
    print(f"  bridge deck station range along corridor: {s17[in200_17].min():.1f} - {s17[in200_17].max():.1f} m")
    print(f"  bridge deck elevation range: {z17[in200_17].min():.2f} - {z17[in200_17].max():.2f} m")

# --- DEM for height-above-ground ---
with rasterio.open(DEM) as ds:
    dem = ds.read(1).astype(np.float32)
    nodata = ds.nodata
    dem_masked = np.where(dem == nodata, np.nan, dem)
    dem_transform = ds.transform


def dem_at(xs, ys):
    rows, cols = rasterio.transform.rowcol(dem_transform, xs, ys)
    rows = np.clip(rows, 0, dem.shape[0] - 1)
    cols = np.clip(cols, 0, dem.shape[1] - 1)
    return dem_masked[rows, cols]


def cluster_report(mask, buf_name):
    xs, ys, zs = x6[mask], y6[mask], z6[mask]
    if len(xs) == 0:
        print(f"[{buf_name}] no class-6 points -- nothing to cluster")
        return []
    # 1m grid connected components over local bbox
    gx0, gy0 = xs.min() - 1, ys.min() - 1
    w = int(np.ceil(xs.max() - gx0)) + 2
    h = int(np.ceil(ys.max() - gy0)) + 2
    grid = np.zeros((h, w), dtype=bool)
    ix = (xs - gx0).astype(int)
    iy = (ys - gy0).astype(int)
    grid[iy, ix] = True
    structure = np.ones((3, 3), dtype=int)  # 8-connected
    labels, nlab = ndimage.label(grid, structure=structure)
    print(f"[{buf_name}] {len(xs)} class-6 pts -> {nlab} clusters (1m grid, 8-connected)")
    point_labels = labels[iy, ix]
    clusters = []
    for lab in range(1, nlab + 1):
        pm = point_labels == lab
        if pm.sum() < 3:
            continue  # drop noise cells (<3 pts)
        cx, cy = xs[pm].mean(), ys[pm].mean()
        footprint_cells = int((labels == lab).sum())
        ground = dem_at(np.array([cx]), np.array([cy]))[0]
        height = float(zs[pm].max() - ground) if not np.isnan(ground) else float("nan")
        clusters.append(dict(centroid=(cx, cy), footprint_m2=footprint_cells, npts=int(pm.sum()),
                              height_above_dem=height))
    clusters.sort(key=lambda c: -c["footprint_m2"])
    for c in clusters:
        print(f"    centroid=({c['centroid'][0]:.1f},{c['centroid'][1]:.1f}) "
              f"footprint={c['footprint_m2']}m2 npts={c['npts']} height_above_dem={c['height_above_dem']:.2f}m")
    return clusters


print()
clusters100 = cluster_report(in100, "100ft buffer")
print()
clusters200 = cluster_report(in200, "200ft buffer")

# --- plot ---
os.makedirs(OUT, exist_ok=True)
with rasterio.open(DEM) as ds:
    dem2 = ds.read(1).astype(np.float32)
    ext = (ds.transform.c, ds.transform.c + ds.width * ds.transform.a,
           ds.transform.f + ds.height * ds.transform.e, ds.transform.f)
    px = ds.transform.a
    gy, gx = np.gradient(np.where(dem2 == ds.nodata, np.nan, dem2), px)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.deg2rad(315), np.deg2rad(45)
    hs = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)

fig, ax = plt.subplots(figsize=(12, 7))
ax.imshow(hs, extent=ext, cmap="gray", origin="upper")
ax.plot(verts[:, 0], verts[:, 1], "y-", lw=2, label="corridor centerline")
for i, k in enumerate(ALIGN_ORDER):
    ax.annotate(k, verts[i], color="yellow", fontsize=9)
ax.scatter(x6[in200], y6[in200], s=2, c="orange", label="class-6 building (200ft buf)")
ax.scatter(x6[in100], y6[in100], s=2, c="red", label="class-6 building (100ft buf)")
if len(x17) > 0:
    ax.scatter(x17[in200_17], y17[in200_17], s=4, c="cyan", label="class-17 bridge deck (200ft buf)")
for c in clusters200:
    ax.scatter(*c["centroid"], marker="x", c="lime", s=60, zorder=6)
ax.set_xlabel("Easting (m)")
ax.set_ylabel("Northing (m)")
ax.set_title("Q4 rough encroachment screen: corridor buffers, buildings, bridge deck")
ax.legend(loc="lower right", fontsize=7)
ax.set_aspect("equal")
plt.tight_layout()
plt.savefig(os.path.join(OUT, "q4_encroachment.png"), dpi=150)
plt.close(fig)
print("wrote q4_encroachment.png")
print("DONE Q4")
