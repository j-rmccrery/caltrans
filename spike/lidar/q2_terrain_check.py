"""Q2: does the record land on the terrain? Control + alignment pts vs hillshade & RGB ortho."""
import os
import numpy as np
import laspy
import rasterio
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = r"C:\Users\johnr\projects\caltrans"
LAZ = BASE + r"\Sample Data\LiDAR-Point-cloud\points.laz"
DEM = BASE + r"\Sample Data\LiDAR-Point-cloud\output.tin.tif"
CACHE = BASE + r"\spike\lidar\cache"
OUT = BASE + r"\spike\lidar\out"
RES = 1.0  # metre grid for ortho

CTRL = {  # record map control (N, E) EPSG:2227 US survey ft
    1: (2120414.20, 5995116.26), 2: (2120268.92, 5994468.77), 3: (2120335.49, 5994267.73),
    4: (2120410.24, 5994251.89), 5: (2120352.93, 5994151.00), 6: (2120378.27, 5993999.17),
    7: (2120468.40, 5994023.77),
}
ALIGN = {  # mainline stationing (N, E) EPSG:2227 US survey ft
    "A": (2120587.32, 5996020.18), "B": (2120362.99, 5995453.54), "D": (2120398.11, 5995416.40),
    "C": (2120311.94, 5994592.86), "E": (2120369.61, 5994434.65), "G": (2120732.34, 5993150.39),
    "F": (2120760.47, 5993175.86), "H": (2120702.87, 5993114.16),
}

t = Transformer.from_crs("EPSG:2227", "EPSG:6339", always_xy=True)


def to_utm(d):
    out = {}
    for k, (N, E) in d.items():
        x, y = t.transform(E, N)
        out[k] = (x, y)
    return out


ctrl_utm = to_utm(CTRL)
align_utm = to_utm(ALIGN)

# --- DEM: hillshade + elevation sampling ---
with rasterio.open(DEM) as ds:
    dem = ds.read(1).astype(np.float32)
    nodata = ds.nodata
    dem_masked = np.where(dem == nodata, np.nan, dem)
    transform = ds.transform
    extent = (transform.c, transform.c + ds.width * transform.a,
              transform.f + ds.height * transform.e, transform.f)
    px = transform.a  # metres/pixel (positive)

    # simple analytical hillshade (az=315, alt=45) from gradient
    gy, gx = np.gradient(dem_masked, px)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.deg2rad(315), np.deg2rad(45)
    hillshade = (np.sin(alt) * np.cos(slope) +
                 np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    hillshade = np.clip(hillshade, 0, 1)

    # sample elevation at control + alignment points
    def sample(pts):
        coords = list(pts.values())
        vals = list(ds.sample(coords))
        return {k: (float(v[0]) if v[0] != nodata else float("nan")) for k, v in zip(pts, vals)}

    ctrl_elev = sample(ctrl_utm)
    align_elev = sample(align_utm)

print("Control point DEM elevation (m):")
for k, v in ctrl_elev.items():
    print(f"  {k}: E={ctrl_utm[k][0]:.2f} N={ctrl_utm[k][1]:.2f} Z={v:.2f}")
print("Alignment point DEM elevation (m):")
for k, v in align_elev.items():
    print(f"  {k}: E={align_utm[k][0]:.2f} N={align_utm[k][1]:.2f} Z={v:.2f}")

# --- RGB ortho from point colours, 1m grid (cached); intensity grid as fallback ---
ortho_path = os.path.join(CACHE, "ortho_rgb_1m.npy")
intensity_path = os.path.join(CACHE, "ortho_intensity_1m.npy")
ortho_bounds_path = os.path.join(CACHE, "ortho_bounds.npy")
if os.path.exists(ortho_path):
    rgb = np.load(ortho_path)
    intensity = np.load(intensity_path)
    bounds = np.load(ortho_bounds_path)
else:
    with laspy.open(LAZ) as f:
        h = f.header
        xmin, ymin = h.mins[0], h.mins[1]
        xmax, ymax = h.maxs[0], h.maxs[1]
        w = int(np.ceil((xmax - xmin) / RES))
        hgt = int(np.ceil((ymax - ymin) / RES))
        ncells = w * hgt
        sumc = np.zeros((3, ncells), dtype=np.float64)
        sumi = np.zeros(ncells, dtype=np.float64)
        cnt = np.zeros(ncells, dtype=np.int64)
        for pts in f.chunk_iterator(2_000_000):
            col = np.column_stack([pts.red, pts.green, pts.blue]).astype(np.float64) / 65535.0 * 255.0
            ix = np.clip(((pts.x - xmin) / RES).astype(np.int64), 0, w - 1)
            iy = np.clip(((ymax - pts.y) / RES).astype(np.int64), 0, hgt - 1)  # flip so row0=north
            flat = iy * w + ix
            for c in range(3):
                sumc[c] += np.bincount(flat, weights=col[:, c], minlength=ncells)
            sumi += np.bincount(flat, weights=pts.intensity.astype(np.float64), minlength=ncells)
            cnt += np.bincount(flat, minlength=ncells)
        rgb = np.zeros((hgt, w, 3), dtype=np.uint8)
        nz = cnt > 0
        for c in range(3):
            ch = np.zeros(ncells)
            ch[nz] = sumc[c][nz] / cnt[nz]
            rgb[:, :, c] = ch.reshape(hgt, w).astype(np.uint8)
        imean = np.zeros(ncells)
        imean[nz] = sumi[nz] / cnt[nz]
        intensity = imean.reshape(hgt, w)
        bounds = np.array([xmin, xmax, ymin, ymax])
        np.save(ortho_path, rgb)
        np.save(intensity_path, intensity)
        np.save(ortho_bounds_path, bounds)

ortho_extent = (bounds[0], bounds[1], bounds[2], bounds[3])
rgb_all_zero = bool(np.all(rgb == 0))
print(f"RGB channel all-zero across whole point cloud: {rgb_all_zero} "
      f"(no camera colour in this dataset -- consistent with a nighttime flight per Q1)")

os.makedirs(OUT, exist_ok=True)


def plot_points(ax, pts, color, marker, label):
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    ax.scatter(xs, ys, c=color, marker=marker, s=40, edgecolors="black", linewidths=0.6, label=label, zorder=5)
    for k, (x, y) in pts.items():
        ax.annotate(str(k), (x, y), fontsize=7, color=color, xytext=(3, 3), textcoords="offset points")


def make_figure(base_img, base_extent, cmap, fname, title):
    zoom_pad = 150
    xs = [p[0] for p in list(ctrl_utm.values()) + list(align_utm.values())]
    ys = [p[1] for p in list(ctrl_utm.values()) + list(align_utm.values())]
    zx0, zx1 = min(xs) - zoom_pad, max(xs) + zoom_pad
    zy0, zy1 = min(ys) - zoom_pad, max(ys) + zoom_pad

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    for ax, is_zoom in zip(axes, [False, True]):
        ax.imshow(base_img, extent=base_extent, cmap=cmap, origin="upper")
        plot_points(ax, ctrl_utm, "red", "o", "record control")
        plot_points(ax, align_utm, "cyan", "^", "alignment (station)")
        if is_zoom:
            ax.set_xlim(zx0, zx1)
            ax.set_ylim(zy0, zy1)
            ax.set_title(title + " (zoom on control cluster)")
        else:
            ax.set_title(title + " (full extent)")
        ax.set_xlabel("Easting (m, UTM10N)")
        ax.set_ylabel("Northing (m)")
        ax.legend(loc="lower right", fontsize=8)
        ax.set_aspect("equal")
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, fname), dpi=150)
    plt.close(fig)
    print(f"wrote {fname}")


hs_extent = extent  # (xmin, xmax, ymin, ymax)
make_figure(hillshade, hs_extent, "gray", "q2_control_on_hillshade.png", "Record control on DEM hillshade")
if rgb_all_zero:
    print("RGB ortho is uniformly black (no colour data) -- skipping it as a real deliverable;")
    print("using intensity-return ortho instead for visual context.")
    # log-stretch intensity for visibility
    ilog = np.log1p(np.clip(intensity, 0, None))
    p2, p98 = np.percentile(ilog[ilog > 0], [2, 98]) if np.any(ilog > 0) else (0, 1)
    istretch = np.clip((ilog - p2) / max(p98 - p2, 1e-6), 0, 1)
    make_figure(istretch, ortho_extent, "gray", "q2_control_on_intensity_ortho.png",
                "Record control on intensity-return ortho (RGB channel empty in source data)")
else:
    make_figure(rgb, ortho_extent, None, "q2_control_on_ortho.png", "Record control on RGB point-cloud ortho")

print("DONE Q2")
