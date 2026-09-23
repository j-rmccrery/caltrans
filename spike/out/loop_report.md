# Overnight loop report, 2026-09-23 (04:00 to 09:00 PDT)

Presidio set: R-10434.2 (demo sheet), R-10434.1, R-10434.3, plus the 1969 scans R-65.1..4 on the tile.
Seven commits on `caltrans-spike`, `2e064bb` .. `d856479`. 11 implementer dispatches of 16 (sonnet),
gates re-measured by the orchestrator. Every number below was re-measured at 08:50 with
`python spike/bench.py final --tables --tags --parcels --traverse presidio r10434_1 r10434_3` unless marked.

## Bench, baseline vs final

| sheet | distance pass | bearing pass | arc pass | wrong-line | tags assoc. | faces named | closed chains |
|---|---|---|---|---|---|---|---|
| R-10434.2 | 17/39 -> **39/47** | 16/31 -> **30/49** | 3/14 -> 4/11 | 37 -> **16** | 18 -> 21* | 4 -> 8 | 0 -> 1 |
| R-10434.1 | 20/51 -> **25/30** | 10/19 -> **19/30** | 4/19 -> 4/26 | 47 -> 28 | 13 -> 14 | 2 -> 5 | 0 |
| R-10434.3 | 26/95 -> **41/71** | 15/43 -> **31/50** | 7/30 -> 7/18 | 93 -> 40 | 24 -> 26 | 4 -> 13 | 2 -> 0 |

\* Presidio jitters by one label between full-pipeline reruns (two `50.22'` annotations 14 pt apart): 39/46 with
tags 23 on most runs, 39/47 with tags 21 on this one. Pre-existing, logged, not fixed.

Denominators changed because the reads changed: annotations find more labels than the glyph reader, and
table cells, stationing and acreage figures no longer count as labels. Pass *rates* on distances:
44 % -> 83 %, 39 % -> 83 %, 27 % -> 58 %.

Other re-measured numbers: Presidio georef 18/19 control points, RMS 0.04 ft (unchanged); tables read
from annotations 44/44, 25/25, 83/83 rows clean (were 41/41, 12/23, 32/77); Presidio keyed table cells
111/111 (the glyph path found 101/101 and missed L1/L2/C1/C2); traverse 87 edges placed, 49 with a
full record (was 22 of 81), one closed chain of 5 edges, end misfit 0.14 ft, record area 6,970.6 sq ft
(figure 61806-9: drawn face 6,974 sq ft, +0.06 %); `demo.py --fast` 122-124 s, every step ok, QGIS
project 13 layers valid.

## Legs

| leg | outcome | what it did |
|---|---|---|
| 0 | pass | bench became the gate instrument: tags, faces, traverse, tables columns; R-10434.1 added |
| 1 | pass on retry | text from `AutoCAD SHX Text` annotations, one block per annotation, bearing+distance pairs joined; tables rebuilt from annotation text. First attempt poured annotation text into merged glyph blocks and lost 43/62/81 distance tokens as "curve data" |
| 2 | skipped, stash `loop-leg-2` | CAD layer taxonomy. As a hard filter it cut recall (34 -> 27 passes); as a ranking it changed nothing. Reusable pieces in the stash: `layers.py`, table-class furniture clusters, additive parcel-layer lines (+13 faces) |
| 3 | pass | measured: after leg 1 no stationing or table-cell token reached the checks; alignment-data tables (STATION/NORTHING headers) added to furniture; acreage context guard |
| 4 | pass by override | bearing, span and row-value filters became defaults; annotation boxes take their angle from the glyph cluster under them, else from their own strokes; `AC.` acreage context. Presidio wrong-line 26 -> 14, aggregate distance passes 102 -> 105; R-10434.1 lost 2 at one crowded vertex (traced: a 14.91 ft segment drawn 1.26° off), R-10434.3 lost 1 fake pass. 12 passing crops inspected, all on the right line |
| 5 | pass (alternate clause) | lone `L=` labels checked against arcs again (0 -> 4/4/7); traverse edges paired by annotation (50 of 88 full record); faces named through arrowhead/circle leaders (5 -> 8). Tunnel easements 61985-1..4: 0 of 4 close, cause cropped |
| 6 | pass | demo end to end with the traverse step; tunnel profile fixed for multi-label faces; numbers.md record-twin block; exceptions page 104 items, 16 wrong-line |
| 6b | pass | packages for R-65.1/.3/.4 fetched; four 1969 rasters on the tile with HTDP shift; "1969 record" QGIS group. The callout-vs-package check is not evidence about the scan reader (6 of 61 boxes parse, bridge is the refused fit) |

## Blockers, with evidence

- **Tunnel easements 61985-1..4 do not close.** Their parcel bubbles' leaders point to detached `R=/Δ=/L=`
  data blocks; the easement arcs are the dashed strip elsewhere, with no drawn arc within 5 glyph heights
  of any of the four `L=` labels (`spike/out/leg5_61985_1..4.png`). Needs leader-to-dashed-line association
  and curves placed from their radial bearings, not from proximity.
- **R-10434.1 stalls at 25/30.** The last two are `14.91'` and `8.12'` at one crowded vertex; the 14.91 ft
  segment is drawn 1.26° off its printed bearing and fails the 4° parallel test too. Length-dependent
  bearing tolerance did not change it.
- **Arc lengths 4/11, 4/26, 7/18.** Remaining misses have no leader tip within 4 pt; the "nearest arc"
  fallback was tried and matched wrong curves 12-14 times per sheet, so it stays off.
- **Scans.** R-65.2's reads still have no independent check: the local-grid-to-CCS83 bridge is the fit the
  pipeline refuses, and only 6 of 61 accepted boxes are N/E coordinates. The package rasters are on the
  tile; the reading problem is untouched (gap 1 in STATE.md).

## Findings worth keeping

- Annotation text is the reader for Civil 3D 2016+ sheets; the glyph alphabet stays for the 2012-era sheets.
- Layers did not help association once the reads were exact. Excluding by layer costs recall; ranking by
  layer changes nothing. Layers still tell furniture from map (tables clusters) and add parcel lines.
- The exception page's wrong-line group went 103 (first page) -> 16 on Presidio.
- `50.22'` twin-annotation jitter: one label flips between runs; fix belongs with de-duplicating annotations
  that share a rect within a glyph height.

## Files changed tonight

`spike/read_shx.py` (new), `spike/bench.py`, `spike/checks.py`, `spike/tables.py`, `spike/traverse.py`,
`spike/parcels.py`, `spike/encroach.py`, `spike/demo.py`, `spike/georef.py`, `spike/slide_numbers.py`,
`spike/qgis_project.py`, `spike/scan_on_tile.py` (new), `spike/leg4_crops.py`, `spike/leg5_61985.py`,
`spike/tags_shx.py` (new, informational), `spike/LOOP.md`. `annot_reads.py` removed. Stash `loop-leg-2`
holds the layer taxonomy.
