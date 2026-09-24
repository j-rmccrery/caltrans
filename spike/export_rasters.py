"""Write the LiDAR intensity ortho and a hillshade as GeoTIFFs so QGIS can show them under the
sheet layers (sheet_linework.geojson, parcels.geojson, encroachments.geojson). No custom UI.

One tile's rasters per run: SHEET=<pdf> picks the tile via tiles.tile_for (default Presidio).
Always written to spike/out/tiles/<name>/; the south tile is ALSO written to the legacy
spike/out/lidar_intensity.tif / lidar_hillshade.tif that qgis_project.py and figures.py read.
"""
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

sys.path.insert(0, str(Path(__file__).parent))
import tiles as tiles_mod  # noqa: E402
from georef import PDF  # noqa: E402  (SHEET-aware; used only to pick the tile)

HERE = Path(__file__).parent
TILE = tiles_mod.tile_for(PDF)
tiles_mod.ensure_cache(TILE)
CACHE = TILE["cache"]
DEM = TILE["dem"]
DESTS = [HERE / "out" / "tiles" / TILE["name"]]
if TILE["name"] == "south":
    DESTS.append(HERE / "out")  # legacy location: qgis_project.py, figures.py read from here

img = np.load(CACHE / "ortho_intensity_1m.npy").astype(np.float32)
xmin, xmax, ymin, ymax = np.load(CACHE / "ortho_bounds.npy")[:4]
lo, hi = np.percentile(img[img > 0], [2, 98])
img8 = (np.clip((img - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
prof = dict(driver="GTiff", height=img8.shape[0], width=img8.shape[1], count=1, dtype="uint8", crs="EPSG:6339",
            transform=from_bounds(xmin, ymin, xmax, ymax, img8.shape[1], img8.shape[0]), compress="deflate")

with rasterio.open(DEM) as ds:
    z = ds.read(1).astype(np.float32); z[z == ds.nodata] = np.nan; T = ds.transform
gy, gx = np.gradient(np.nan_to_num(z, nan=float(np.nanmedian(z))), abs(T.e), T.a)
az, alt = np.radians(315), np.radians(45)
slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
hs8 = (np.clip(hs, 0, 1) * 255).astype(np.uint8)

for d in DESTS:
    d.mkdir(parents=True, exist_ok=True)
    with rasterio.open(d / "lidar_intensity.tif", "w", **prof) as dst:
        dst.write(img8, 1)
    with rasterio.open(d / "lidar_hillshade.tif", "w", driver="GTiff", height=hs8.shape[0], width=hs8.shape[1], count=1, dtype="uint8", crs="EPSG:6339", transform=T, compress="deflate") as dst:
        dst.write(hs8, 1)
    print("wrote", d / "lidar_intensity.tif", "and", d / "lidar_hillshade.tif")
