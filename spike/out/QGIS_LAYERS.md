# Loading the demo layers in QGIS

Open `spike/out/demo.qgz` (built by `spike/qgis_project.py`, last step of `demo.py`): all layers below plus
the object record (points / lines / polygons, coloured by status: green verified, orange queued, red refused,
grey record-only) with a map tip on hover (sheet, region, printed, measured, residual, rule, status). Relative
paths: the whole `spike/out` folder moves as one. Needs QGIS 3.28 or later.

If the project does not open, add the layers by hand in this order (bottom to top):

| Layer | File | CRS |
|---|---|---|
| Hillshade | `lidar_hillshade.tif` | EPSG:6339 (NAD83(2011) UTM 10N) |
| LiDAR intensity | `lidar_intensity.tif` | EPSG:6339 |
| Sheet linework (R-10434.2) | `sheet_linework.geojson` | EPSG:6318 (NAD83(2011) lon/lat) |
| Parcels from the sheet | `parcels.geojson`, style by `parcel` | EPSG:6318 |
| Encroachment clusters | `encroachments.geojson`, style by `verdict` | EPSG:6318 |

The sheet layers already include the 1991.35 to 2010.0 epoch shift (`spike/lidar/htdp.json`), so they sit on
the LiDAR without further transformation. Set the project CRS to EPSG:6339.

Regenerate: `blocks.py`, `ocr.py rapid`, `solve.py`, `overlay.py`, `parcels.py`, `encroach.py`, `export_rasters.py`
(the LiDAR spike's `q2_terrain_check.py` builds the intensity cache first).
