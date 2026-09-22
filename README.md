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
| Pair N/E callouts, trace leader lines to the labelled point, fit sheet to CCS83 Zone 3 | `spike/georef.py` | 19 of 19 control points, RMS 0.04 ft; scale 1.38885 ft/pt against a plot scale of 1.38889 |
| Transform linework to NAD83(2011) UTM 10N with the HTDP epoch shift, draw on LiDAR intensity, export GeoJSON | `spike/overlay.py` | `spike/out/overlay_zoom.png`, `spike/out/sheet_linework.geojson` |
| Second control path: grid tick labels give one linear equation per grid-line stub | `spike/georef_ticks.py` | CC-680: 12/12 lines, RMS 0.04 ft; ALA-84: 13/13, RMS 0.05 ft |
| One solver over every control type (callouts, monument notes, grid lines) with consensus and per-axis redundancy | `spike/solve.py` | SON-121: 1 callout + 4 grid lines, 0.31 ft from Caltrans' package, flagged weak in northing |
| Generalisation run over unrelated District 4 record maps from the public index | `spike/batch.py` | `spike/out/batch.csv`; per-sheet logs in `spike/out/<sheet>/` |
| Scanned sheets: OCR detection on tiles of a 300 dpi render, then callouts and circle candidates through the same solver | `spike/scan_read.py`, `spike/scan_georef.py` | 1969 R-65.2: 273 boxes found; two readers (RapidOCR and a local vision model) on 87 numeric boxes; 4-pair fits appear but are refused because their scale disagrees with the grid labels, which is the correct verdict: not georeferenced yet |
| LiDAR checks: flight date, control on terrain, epoch offset, building points in corridor, flightline overlap QA | `spike/lidar/q1..q5` | logs in `spike/lidar/out_q*.txt`, plots in `spike/lidar/out/` |

Epoch offset 1991.35 to 2010.0 at the site, from NGS HTDP v3.6.0: 0.668 m (2.19 ft), N33°W.

## Other sheets

The D4 map index (a public ArcGIS feature service) links every District 4 record map and, for most,
Caltrans' own georeferenced package. Across 11 vector sheets: 8 georeference automatically and agree
with the Caltrans package to about 1 ft or better (0.05 m on a metric sheet); 1 more fits from mixed
control but is flagged weak (its northing rests on one feature, and the sheet's own N grid label
disagrees with its callout by 10 ft); 2 are refused (no on-sheet control, or only off-sheet monuments). `SHEET=<pdf>` runs any sheet; outputs go
to `spike/out/<sheet>/`. Scanned sheets (most of the archive, including the 1969 predecessors of the
sample sheet) are not handled yet.

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
- On a scan, four callouts agreeing to 1 ft can happen by chance when each has dozens of circle candidates; a scan fit is only accepted when its scale also matches the grid labels. Two such chance fits were caught on R-65.2.
- Hand lettering: neither RapidOCR nor a local vision model (qwen2.5vl:7b, `spike/scan_vlm.py`) reads it reliably alone; where the two agree the read is right, which is the usable confidence signal.
- Some drafters end leaders in an arrowhead a few points short of the point symbol (CC-580); the trace lands about 8 ft off and the sheet is refused.
