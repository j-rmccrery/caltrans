# State and resume point

Branch `caltrans-spike` on `gitlab.com/jrmccrery/dredge-code` (orphan branch; never merge into `main`).
Plan: `ROADMAP.md`. Layers for the screen: `spike/out/QGIS_LAYERS.md`. Run everything: `python spike/demo.py --fast`.

## Where the roadmap stands (as of the last commit)

| Roadmap item | State |
|---|---|
| D1–2 `demo.py` one command | Done, 232 s. Over the 3-min target: `blocks.py` assembly is 207 s (Python double loop in `assemble()`); vectorise it. |
| D1–2 `objects.geojson` provenance record | Done (`spike/objects.py`). |
| D1–2 QGIS project `demo.qgz` | Not built. Load order in `spike/out/QGIS_LAYERS.md`. |
| D3–6 table traverse | Not started. Design: parse line/curve tables (reads exist in `spike/out/read_rapid.json`, keyed truth in `spike/gt.py`), associate short tags `L8`/`C16` on the drawing to line chains (`checks.lines_on_sheet`), walk parcel boundaries by tag sequence, closure per figure, parametrise curves from R/Δ/L. Assignment with uniqueness: ambiguous → queue. Target: tunnel easements 61985-1..4 closed and within 1% of the parcel table. |
| D7–8 exception page | Not started. Source: `spike/out/exceptions.json` + crops via `spike/checks_debug.py` rendering. |
| D9–10 LiDAR refresh | Depends on D3–6 parcels. `spike/encroach.py`, `spike/lidar/extract.py` already read `parcels.geojson`. |
| D11 fallback recording, Q&A sheet | Q&A answers are in `ROADMAP.md`. |

## Numbers to quote (measured, from the run)

- Georeferencing: 8 of 11 D4 vector sheets credible, 1 weak, 2 refused; Presidio 19/19 control, RMS 0.04 ft; vs Caltrans' own package ~0.6–1.1 ft (raster-limited).
- Checks (Presidio): where a label is associated, 0.01–0.07 ft and 0.2–0.9 arcmin; association pass rates 17/88 distances, 11/38 bearings, 1/13 arcs.
- Scan (1969 R-65.2): 273 boxes detected; two readers agree on 1–2 of 87 coordinate boxes; two chance 4-point fits caught by the grid-label scale check; not georeferenced.
- LiDAR: flown 2025-09-27; HTDP epoch shift 0.668 m N33°W; flightline RMSE 0.02–0.04 m off-slope; 32 pavement, 11 deck, 175 building polygons; 81% of highway pavement inside the drawn R/W faces.

## Known traps

- OCR confidence does not separate right from wrong; use geometry.
- A 4-point fit with 0.3 ft residuals can be wrong by 13% in scale; always check against independent control (grid labels, Caltrans package).
- Vision-model prompts must not contain example values (the model copies them).
- Admitting dashed lines to the parcel polygonisation shatters the corridor (70 faces).
- Windows: Bash heredocs eat backslashes in regexes; write patch scripts with the Write tool. `PYTHONIOENCODING=utf-8` for any script printing survey symbols.
