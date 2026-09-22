# State and resume point

Branch `caltrans-spike` on `gitlab.com/jrmccrery/dredge-code` (orphan branch; never merge into `main`).
Plan: `ROADMAP.md`. Layers for the screen: `spike/out/QGIS_LAYERS.md`. Run everything: `python spike/demo.py --fast`.

## Where the roadmap stands (as of the last commit)

| Roadmap item | State |
|---|---|
| D1–2 `demo.py` one command | Done, 78 s (`--fast`, of which tag reading 36 s). Was 232 s: `blocks.py` scanned the full 72-Mpx label image once per component (180 s) and `assemble()` was a Python double loop (25 s); both vectorised, output identical. |
| D1–2 `objects.geojson` provenance record | Done (`spike/objects.py`). |
| D1–2 QGIS project `demo.qgz` | Not built. Load order in `spike/out/QGIS_LAYERS.md`. |
| D3–6 table traverse | **Narrowed (option C, JR 2026-09-22)**: tag reading + tag→segment association + per-row check; closure/area target dropped because the tunnel easements 61985-1..4 are drawn as dashed lines with inline bearing/distance and R/Δ/L, not table tags. `spike/tags.py` reads tags without OCR: every glyph is a stroked path, table cells with keyed truth are labelled exemplars (165 distinct bitmaps, 20 characters), each drawing path is matched at 36 rotations; 36 of 44 table rows found on the drawing, 7 partial reads queued (`L1?`, `C9??`), none wrong on the four crops checked. `spike/tables.py` associates by the leader's arrowhead (20 of 21), else the one heavy line beside the tag; two candidates → queue. Lines: bearing 9/11 pass, distance 8/10 pass (both fails are L1, a 1.86 ft radial, and L21, the dash-dot centreline: not checkable). Radius 4/4. **Arc length 2/10: open.** The drawn curves are polylines that run through several table arcs (C15+C16+C18 = one R=1470 curve, C12+C13+C14 = one R=60 curve); splitting at circles / lines meeting the curve moves the cut points by 2–20 ft between variants. Needs a look at the actual junction geometry, not more tuning. |
| D7–8 exception page | Done: `spike/exceptions_page.py` → `spike/out/exceptions.html`, one offline file (7.9 MB), 172 items in 8 cause groups, each with a crop (red = label region, blue = the line the reader measured), reason, printed/drawn/difference, citation (sheet + region in PDF pt), a resolution select + note kept in the browser and exported as JSON. The scan's queue (fit not credible + 4 control pairs) is on the same page. **What the page exposed:** of 110 label-vs-line fails from `checks.py`, 103 are off by far too much to be drafting errors: the reader measured a different line (leader stubs, callout underlines, "BATTERY BLUFF" underline). Only 7 are genuine small disagreements. The page groups those 103 as "reader measured a different line" — honest, but `checks.nearest_line` needs the same leader/junction treatment `tables.py` got. |
| D9–10 LiDAR refresh | Depends on D3–6 parcels. `spike/encroach.py`, `spike/lidar/extract.py` already read `parcels.geojson`. |
| D11 fallback recording, Q&A sheet | Q&A answers are in `ROADMAP.md`. |

## Numbers to quote (measured, from the run)

- Georeferencing: 8 of 11 D4 vector sheets credible, 1 weak, 2 refused; Presidio 19/19 control, RMS 0.04 ft; vs Caltrans' own package ~0.6–1.1 ft (raster-limited).
- Checks (Presidio): where a label is associated, 0.01–0.07 ft and 0.2–0.9 arcmin; association pass rates 17/88 distances, 11/38 bearings, 1/13 arcs.
- Table tags (Presidio): 36/44 rows read on the drawing, 7 partial queued, 0 misread; 21 associated (20 by leader); bearing 9/11, distance 8/10, radius 4/4, arc length 2/10 (`spike/out/tags_checks.csv`, queue in `tags_queue.json`).
- Scan (1969 R-65.2): 273 boxes detected; two readers agree on 1–2 of 87 coordinate boxes; two chance 4-point fits caught by the grid-label scale check; not georeferenced.
- LiDAR: flown 2025-09-27; HTDP epoch shift 0.668 m N33°W; flightline RMSE 0.02–0.04 m off-slope; 32 pavement, 11 deck, 175 building polygons; 81% of highway pavement inside the drawn R/W faces.

## Known traps

- OCR confidence does not separate right from wrong; use geometry.
- A 4-point fit with 0.3 ft residuals can be wrong by 13% in scale; always check against independent control (grid labels, Caltrans package).
- Vision-model prompts must not contain example values (the model copies them).
- Admitting dashed lines to the parcel polygonisation shatters the corridor (70 faces). Chaining the 0.84-pt dashes with `lines_on_sheet(max_turn 6)` does not shatter (31 faces) but the easement strips still do not close.
- OCR text blocks beside the R/W line absorb stationing ticks and leader arrowheads (both glyph-sized), which skews their angle; read tags from the glyph paths instead (`tags.py`).
- Leaders share the lettering weight (1.02 pt) and end at a filled triangle; hatch is gray 0.50; the alignment curves are 0.36 pt; ticks are 7.2-pt stubs. Width alone does not separate "line a tag describes" from furniture.
- `checks.nearest_line` (label → nearest parallel line) mostly picks the label's own leader stub or underline: 103 of 110 fails on the Presidio sheet are wrong-line, not wrong-number. Seen only once the exception page drew the measured line. Fix belongs in `checks.py` (exclude leader paths and underlines, prefer the leader's arrowhead as `tables.py` does).
- Windows: Bash heredocs eat backslashes in regexes; write patch scripts with the Write tool. `PYTHONIOENCODING=utf-8` for any script printing survey symbols.
