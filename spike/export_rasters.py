"""Write the LiDAR intensity ortho and a hillshade as GeoTIFFs so QGIS can show them under the
sheet layers (sheet_linework.geojson, parcels.geojson, encroachments.geojson). No custom UI."""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

HERE = Path(__file__).parent
CACHE = HERE / "lidar" / "cache"
OUT = HERE / "out"
DEM = HERE.parent / "Sample Data" / "LiDAR-Point-cloud" / "output.tin.tif"

img = np.load(CACHE / "ortho_intensity_1m.npy").astype(np.float32)
xmin, xmax, ymin, ymax = np.load(CACHE / "ortho_bounds.npy")[:4]
lo, hi = np.percentile(img[img > 0], [2, 98])
img8 = (np.clip((img - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
prof = dict(driver="GTiff", height=img8.shape[0], width=img8.shape[1], count=1, dtype="uint8", crs="EPSG:6339",
            transform=from_bounds(xmin, ymin, xmax, ymax, img8.shape[1], img8.shape[0]), compress="deflate")
with rasterio.open(OUT / "lidar_intensity.tif", "w", **prof) as dst:
    dst.write(img8, 1)

with rasterio.open(DEM) as ds:
    z = ds.read(1).astype(np.float32); z[z == ds.nodata] = np.nan; T = ds.transform
gy, gx = np.gradient(np.nan_to_num(z, nan=float(np.nanmedian(z))), abs(T.e), T.a)
az, alt = np.radians(315), np.radians(45)
slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
hs8 = (np.clip(hs, 0, 1) * 255).astype(np.uint8)
with rasterio.open(OUT / "lidar_hillshade.tif", "w", driver="GTiff", height=hs8.shape[0], width=hs8.shape[1], count=1, dtype="uint8", crs="EPSG:6339", transform=T, compress="deflate") as dst:
    dst.write(hs8, 1)
print("wrote", OUT / "lidar_intensity.tif", "and", OUT / "lidar_hillshade.tif")
