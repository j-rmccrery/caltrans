# Caltrans Pitch Day: SWYFT Record Twin spikes

Feasibility spikes for the Caltrans Vendor Pitch Day demo (AI Problem Statement #6,
Automated Data Extraction and Digital Twin). Throwaway code: it answers "does this work"
for the risky pieces, it is not the demo.

Scope: `Caltrans_Demo_Scope.pdf`.

## What it does

Takes a Caltrans right of way record map (vector PDF) and an airborne LiDAR tile and,
with no hand-typed coordinates, draws the sheet's linework on the LiDAR in ground position.

| Step | Script | Result on R/W Record Map R-10434.2 |
|---|---|---|
| Find text blocks from vector glyph strokes, with exact box and angle | `spike/blocks.py` | 1,345 blocks, 605 rotated |
| Level each crop, read with RapidOCR, parse survey notation | `spike/ocr.py rapid` | 208 / 227 table values correct (91.6%); misses are mostly row IDs such as `R-1` |
| Hand-keyed ground truth, self-checked with L = R·Δ on all 23 curves | `spike/gt.py` | 227 values |
| Pair N/E callouts, trace leader lines to the labelled point, fit sheet to CCS83 Zone 3 | `spike/georef.py` | 12 of 14 control points used, 2 bad traces rejected; RMS 0.04 ft; scale 1.38885 ft/pt against a plot scale of 1.38889 |
| Transform linework to NAD83(2011) UTM 10N with the HTDP epoch shift, draw on LiDAR intensity, export GeoJSON | `spike/overlay.py` | `spike/out/overlay_zoom.png`, `spike/out/sheet_linework.geojson` |
| LiDAR checks: flight date, control on terrain, epoch offset, building points in corridor, flightline overlap QA | `spike/lidar/q1..q5` | logs in `spike/lidar/out_q*.txt`, plots in `spike/lidar/out/` |

Epoch offset 1991.35 to 2010.0 at the site, from NGS HTDP v3.6.0: 0.668 m (2.19 ft), N33°W.

## Run

Python 3.12. Data is not in the repo; place the sample files under `Sample Data/`
(`Right-of-Way Map Record/r_10434_002_2020-09-16.pdf`, `LiDAR-Point-cloud/points.laz`,
`LiDAR-Point-cloud/output.tin.tif`).

```
python -m venv .venv
.venv/Scripts/python -m pip install pymupdf opencv-python-headless rapidocr-onnxruntime numpy scipy matplotlib "laspy[lazrs]" rasterio pyproj
.venv/Scripts/python spike/blocks.py
.venv/Scripts/python spike/ocr.py rapid
.venv/Scripts/python spike/lidar/q2_terrain_check.py   # builds the intensity image cache used by overlay.py
.venv/Scripts/python spike/georef.py
.venv/Scripts/python spike/overlay.py
```

## Known gaps

- OCR confidence does not separate right from wrong reads; the exception queue has to be driven by deterministic checks.
- One-stroke characters (`1`, `-`, the `Δ=` prefix) and occasional merged table cells are the reader's weak spots.
- Callout leader lines share the heavy line weight with R/W lines and are drawn with them.
- No parcel polygons, no label-to-line association, no closure checks, no UI yet.
- The LiDAR is public airborne data, not mobile LiDAR; it has no colour channel.
