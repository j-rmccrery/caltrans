# State and resume point

Branch `caltrans-spike` on `gitlab.com/jrmccrery/dredge-code` (orphan branch; never merge into `main`).
Plan: `ROADMAP.md`. Layers for the screen: `spike/out/QGIS_LAYERS.md`. Run everything: `python spike/demo.py --fast`.

## Where the roadmap stands (as of the last commit)

| Roadmap item | State |
|---|---|
| D1–2 `demo.py` one command | Done, 89 s (`--fast`, of which tag reading 36 s; ends with the exception page and the QGIS project). Was 232 s: `blocks.py` scanned the full 72-Mpx label image once per component (180 s) and `assemble()` was a Python double loop (25 s); both vectorised, output identical. |
| D1–2 `objects.geojson` provenance record | Done (`spike/objects.py`). |
| D1–2 QGIS project `demo.qgz` | Done, verified. `spike/qgis_project.py` is PyQGIS, run under QGIS LTR's own Python (`%LOCALAPPDATA%\Programs\OSGeo4W\bin\python-qgis-ltr.bat`; `demo.py` routes it there, skips if QGIS is absent): 9 layers in order, hillshade + intensity, sheet linework by weight, parcels labelled, LiDAR features by kind, encroachments by verdict, object record split into points / lines / polygons by OGR `geometrytype=` and coloured by status, map tips with the provenance fields. Project CRS EPSG:6339, feet, relative paths. The script re-reads the written project, asserts every layer survives, and renders the opening view to `spike/out/demo_render.png` (the proof). First version was hand-written `.qgs` XML: loaded, but QGIS regenerated layer ids (tree links broke) and the raster renderer XML drew nothing — replaced. `objects.geojson` was cp1252 (degree signs); now UTF-8. |
| D3–6 table traverse | **Narrowed (option C, JR 2026-09-22)**: tag reading + tag→segment association + per-row check; closure/area target dropped because the tunnel easements 61985-1..4 are drawn as dashed lines with inline bearing/distance and R/Δ/L, not table tags. `spike/tags.py` reads tags without OCR: every glyph is a stroked path, table cells with keyed truth are labelled exemplars (165 distinct bitmaps, 20 characters), each drawing path is matched at 36 rotations; 36 of 44 table rows found on the drawing, 7 partial reads queued (`L1?`, `C9??`), none wrong on the four crops checked. `spike/tables.py` associates by the leader's arrowhead (20 of 21), else the one heavy line beside the tag; two candidates → queue. Lines: bearing 9/11 pass, distance 8/10 pass (both fails are L1, a 1.86 ft radial, and L21, the dash-dot centreline: not checkable). Radius 5/7. **Arc length 6/10** (4 of them "as a run"). What the drawing puts at an arc boundary, measured: a vertex circle, a boundary line *ending* on the curve (C18's end: drawn 62.10 ft vs record 62.14), or on the thin alignment curves a 7-pt radial tick — and sometimes **nothing** (the C16/C15 boundary on the R=1470 curve has no mark; the run between circles is 573.95 ft drawn vs 573.93 (T) printed). So `split_at` cuts runs at those marks only (no crossing cuts), and a tag passes on its own length or, when several tags share a run, the run passes against their sum with the result "pass as a run of N: the boundary between these arcs is not drawn". Remaining fails: C11 (its run-mate C10 has no leader, so no sum), C19/C21/C22 (runs cut wrong on the long R/W curves). |
| D7–8 exception page | Done: `spike/exceptions_page.py` → `spike/out/exceptions.html`, one offline file (4.8 MB), 100 items in 8 cause groups, each with a crop (red = label region, blue = the line the reader measured), reason, printed/drawn/difference, citation (sheet + region in PDF pt), a resolution select + note kept in the browser and exported as JSON. The scan's queue (fit not credible + 4 control pairs) is on the same page. **What the page exposed:** of 110 label-vs-line fails from `checks.py`, 103 are off by far too much to be drafting errors: the reader measured a different line (leader stubs, callout underlines, "BATTERY BLUFF" underline). Only 7 are genuine small disagreements. The page groups those 103 as "reader measured a different line" — honest, but `checks.nearest_line` needs the same leader/junction treatment `tables.py` got. |
| D9–10 LiDAR refresh | Done as far as it can be without traverse parcels (none came out of D3–6, so the faces are the same). `spike/slide_numbers.py` → `out/numbers.md` + `numbers.json`: every number to quote, from the run's files (georef, checks, exceptions, tags, parcels, LiDAR features, encroachment, tunnel profile, HTDP), plus `tunnel_profile.png`. `spike/figures.py` (PyQGIS, renders from `demo.qgz`): `fig_record.png` (checks on the LiDAR), `fig_parcels.png`, `fig_tunnel.png`, `fig_htdp.png` (linework before/after the 0.668 m epoch shift on the intensity image). Both are the last `demo.py` steps. numbers.md carries the caveat that the 61985-4 face is the unclosed 37-acre polygon, so its tunnel profile runs along the wrong figure. |
| D11 fallback recording, Q&A sheet | Q&A answers are in `ROADMAP.md`. |

## Alphabet without keying, and other sheets

`spike/alphabet.py`: a sheet's own alphabet from its tables. Seed = the public-domain Hershey simplex font (parent of AutoCAD's txt/simplex; digits within 0–2.5 of this lettering, 0 and 6 at 5–7). The seed finds the line/curve tables' NO. cells (L1, L2, … / C1, C2, …), the consecutive run validates them, their glyphs become exact exemplars, a second pass finds the columns the seed misread, and the row cells to the right are labelled by structure (cap-height glyphs are digits/letters, the small glyphs are ° ' " . in fixed order; N|S and E|W picked among letters; `(T)` suffixes; E's separate middle bar merged). Presidio: **95/101 table cells exact vs the hand-keyed tables, 0 wrong**, the 6 misses are `(T)` total cells left as `?`; L1/L2/C1/C2 not found (no cell of their own under the header). `gt.py` is now a validation set; `tags.py` and `tables.py` read `alphabet.npz` / `tables.json` and fall back to it only when absent. With the bootstrapped alphabet Presidio tags 36/40 rows, table checks bearing 8/8, distance 8/8, radius 5/7, arc 5/9.

`spike/sheets.py --run` (alphabet → tags → tables → checks on every sheet with a credible fit; `out/sheets.csv`):

| sheet | lettering | tables read (rows / clean) | tags read | tag checks pass/fail | label checks distance, bearing, arc | exceptions (wrong-line) |
|---|---|---|---|---|---|---|
| R-10434.2 Presidio | stroked | 41 / 35 | 36 | 26 / 6 | 25/46, 12/20, 3/13 | 61 (31) |
| R-10434.1 sibling | stroked, same drafter | 23 / 11 | 15 | 17 / 9 | 13/41, 3/17, 5/25 | 84 (57) |
| R-10434.3 sibling | stroked, same drafter | 77 / 26 | 59 (+30 partial) | 7 / 16 | 19/122, 10/55, 6/22 | 208 (151) |
| R-17x.1, R-102.1aa, R-105.14 | real PDF text (Times) | no stroked tables | — | — | 13/42 9/16 0/22 · 4/13 24/28 0/8 · 13/29 17/25 0/12 | 94 (49) · 27 (20) · 48 (28) |
| R-10258.1 | real text (RomanS), few labels | — | — | — | 0/0, 3/7, 0/2 | 7 (3) |

What it says: the alphabet and table reader carry to the same drafter's other sheets (clean rows 48 % and 34 %: more `(T)` and other cell formats to add). Tag association on the siblings is weak (13 and 12 associated): `MAP_AREA` / `FURNITURE` are still Presidio's frame, and .3 is a denser sheet. The real-text sheets skip the whole glyph path (their tables are not stroked; `real_text_blocks` feeds the label checks directly, and distances from real text are now checked). Wrong-line counts on every other sheet say the leader/tick conventions differ per drafter: that is the adapter work, per sheet, and it is now measurable.

## Numbers to quote (measured, from the run)

- Georeferencing: 8 of 11 D4 vector sheets credible, 1 weak, 2 refused; Presidio 19/19 control, RMS 0.04 ft; vs Caltrans' own package ~0.6–1.1 ft (raster-limited).
- Checks (Presidio): where a label is associated, 0.01–0.07 ft and 0.2–0.9 arcmin; association pass rates 25/46 distances, 12/20 bearings, 3/13 arcs (were 17/88, 11/38, 1/13 before leaders, junction splitting and the table cells were handled; the denominators fell because table cells are no longer "labels"). Exceptions 61 (were 133); 31 still wrong-line, 12 "leader points at no line".
- Table tags (Presidio): 36/44 rows read on the drawing, 7 partial queued, 0 misread; 21 associated (20 by leader); bearing 9/11, distance 8/10, radius 5/7, arc length 6/10 of which 4 as a run (`spike/out/tags_checks.csv`, queue in `tags_queue.json`).
- Record arcs vs drawing: a drawn run between vertex circles is the (T) total to 0.02 ft (573.95 vs 573.93); a sub-arc boundary that is not drawn cannot be checked alone, only by sum.
- Scan (1969 R-65.2): 273 boxes detected; two readers agree on 1–2 of 87 coordinate boxes; two chance 4-point fits caught by the grid-label scale check; not georeferenced.
- LiDAR: flown 2025-09-27; HTDP epoch shift 0.668 m N33°W; flightline RMSE 0.02–0.04 m off-slope; 32 pavement, 11 deck, 175 building polygons; 81% of highway pavement inside the drawn R/W faces.

## Known traps

- OCR confidence does not separate right from wrong; use geometry.
- A 4-point fit with 0.3 ft residuals can be wrong by 13% in scale; always check against independent control (grid labels, Caltrans package).
- Vision-model prompts must not contain example values (the model copies them).
- Admitting dashed lines to the parcel polygonisation shatters the corridor (70 faces). Chaining the 0.84-pt dashes with `lines_on_sheet(max_turn 6)` does not shatter (31 faces) but the easement strips still do not close.
- OCR text blocks beside the R/W line absorb stationing ticks and leader arrowheads (both glyph-sized), which skews their angle; read tags from the glyph paths instead (`tags.py`).
- Leaders share the lettering weight (1.02 pt) and end at a filled triangle; hatch is gray 0.50; the alignment curves are 0.36 pt; ticks are 7.2-pt stubs. Width alone does not separate "line a tag describes" from furniture.
- `checks.nearest_line` (label → nearest parallel line) used to pick the label's own leader stub or underline: 103 of 110 fails were wrong-line. Fixed in `checks.py` (leaders by arrowhead or circle, leader paths and stubs and underlines excluded, gray hatch excluded, table cells skipped, straight chains split at circles/junctions/crossings, `split_chains`). Wrong-line is now 31: remaining causes are cut points 5–20 ft off where lines cross the R/W run, and leaders whose arrow lands where three pieces meet.
- `split_chains` in `tables.py` hurts (8/10 → 4/10): tag leaders land on whole segments that already end at circles; crossing dashes cut them. Left out there.
- The exception page's "reader measured a different line" group is the fastest diagnostic there is: render the measured line, look at 12 crops, fix the biggest cause, repeat. Four rounds took the wrong-line count 103 → 31.
- Qt reads an 8-digit hex colour as #AARRGGBB, not #RRGGBBAA: buildings came out magenta. Use `QColor(hex6)` + `setAlpha`.
- `QgsMapSettings.setLayers` takes the stack top-first (legend order); rasters listed first paint over everything.
- `blocks.py`'s vectorisation kept the block *set* but not the id order; `read_rapid.json` (OCR, not re-run under `--fast`) is now id-misaligned with `blocks.json`. Nothing joins the two by id any more, but re-run `ocr.py` before anything does.
- The tag reader must mask the tables wherever they are on a sheet (`_regions` in `tables.json`), not Presidio's coordinates: on R-10434.3 every NO. cell read as a drawing tag until it did.
- Never name a script after a stdlib module: `spike/numbers.py` shadowed `numbers` and broke numpy in every process that had `spike/` on `sys.path`.
- QGIS project files: do not hand-write the XML. QGIS regenerates layer ids on save (layer-tree links break) and half-specified renderers load "valid" but draw nothing. Build with PyQGIS and render a PNG as the check.
- Windows: Bash heredocs eat backslashes in regexes; write patch scripts with the Write tool. `PYTHONIOENCODING=utf-8` for any script printing survey symbols.
