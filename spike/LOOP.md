# Overnight loop: Presidio accuracy (started 2026-09-23, JR-approved)

Goal: raise measured association and reconstruction accuracy on the three Presidio vector sheets
(R-10434.1/.2/.3) using the CAD structure found on 2026-09-23 (layers, SHX annotations), every leg gated
by `spike/bench.py`, then the 1969 scans on the tile through Caltrans' packages. Morning report at the end.

Rules (from JR, 2026-09-23): commit each passed leg on `caltrans-spike`, no push; budget 16 dispatches or
7 h; implementers on sonnet; gate checks, crop inspection and the report by the orchestrator; scope is
`spike/` only, `Sample Data/` read-only; `demo.py --fast` must still run at the end. A leg that fails its gate
twice is skipped and logged; the diff is stashed as `loop-leg-N`.

## Legs

| # | Leg | Gate (measured by the orchestrator, not the implementer) |
|---|---|---|
| 0 | Bench: `.1` added, tags and faces columns; baseline rows for .1/.2/.3 | baseline row for all three sheets with every column |
| 1 | SHX annotation reads first, glyph reads second, disagreement queued; `georef.READS` picks the annotation file when present | tables clean rows >= 95 % on .1 and .3; Presidio georef 18/19, RMS <= 0.05 ft |
| 2 | Layer taxonomy (`spike/layers.py`) used by `checks.py`, `tables.py`, `parcels.py`, `frame.py` | wrong-line <= 15 on .2, <= 45 on .3; named faces >= 20 on .2; no distance pass lost vs leg 1 |
| 3 | Noise tokens out: stationing, `R=`, table cells by layer | noise bucket 0 on .2; passes unchanged or up |
| 4 | Civil 3D anchor rule for candidates; bearing, span, row-value filters become defaults; toggles removed | distance pass >= 60 % on .1/.2/.3; 12 random passing crops, none on a wrong line |
| 5 | Traverse rerun, parcel areas | >= 1 closed figure on .2; 61985-1..4 areas within 1 % of the parcel table, or the blocker named with a crop |
| 6 | `demo.py --fast`, `slide_numbers.py`, exception page | under 180 s; numbers.md regenerated; exceptions.html opens |
| 6b | 1969 scans R-65.1/.3/.4: fetch Caltrans packages from the D4 index, georeference by package, overlay on the tile | four R-65 sheets as GeoJSON on the tile; matchline vs the 2020 sheets reported |
| 7 | Report `spike/out/loop_report.md` | every number re-measured at report time or marked unverified |

## Status

| leg | state | dispatches | gate result | commit |
|---|---|---|---|---|
| 0 | pass | 1 | 3 baseline rows, 17 columns | 8acedf0 |
| 1 | pass on retry | 2 | tables 44/44, 25/25, 83/83 clean; keyed 111/111; georef 18/18 rms 0.04; but distance tokens skipped as curve-data 43/62/81 vs 0/10/24 glyph (annotations poured into merged glyph blocks), presidio bearing 14 < 16, .1 distance 18 < 20. Retry: one block per annotation, bearing+distance pairs only: distance 34/52, 27/35, 41/78; bearing 23/45, 18/29, 29/52; wrong-line 26/23/46; arc length 0 on all three (regression, to leg 2) | leg1 |
| 2 | skipped (failed twice), stash `loop-leg-2` | 2 | attempt 1, layers as hard filter: distance 27/35, 24/27, 32/52 vs leg 1 34/52, 27/35, 41/78; faces collapsed. Attempt 2, layers rank only: 34/51, 27/35, 37/64; bearing 23/18/28; wrong-line 27/27/43 vs leg 1 26/23/46: no gain. Finding: with annotation-quality reads, layer ranking adds nothing; layer exclusion trades recall for precision. Reusable from the stash: `layers.py`, lone `L=` arc-length fix (arc 0 -> 1), parcels additive parcel-sub lines (+13 faces on .2), table-class furniture clusters | - |
| 3 | pass | 1 | stationing and table-region tokens checked: already 0 after leg 1 (annotation keeps `65+48.80` in one block); added alignment-data table regions (STATION/NORTHING headers) to FURNITURE and an area-context guard. Bench identical to leg 1: 34/52, 27/35, 41/78 | leg3 |
| 4 | running | 1 | | |

Dispatches used: 4 of 16. Started 2026-09-23 ~04:00 local.

## Consult notes

gpt-oss:20b (2026-09-23): layer taxonomy in four classes, bridge same-layer endpoints, merge dashes, leader
direction and length filters, rank then flag. Its named libraries do not exist.
Qwen3 27B (2026-09-23, 27 min): same architecture; adds (a) parcel segments and alignment segments are
different objects that overlap, so weight candidates by label class (table tags and parcel labels ->
`RW-PARCEL-SEG-*`, alignment bearings -> `RW-ALGN-LNWK-*`), never hardcode; (b) label anchor is the
segment midpoint, leader tip when dragged (= leg 4); (c) Hungarian assignment via
`scipy.optimize.linear_sum_assignment` (measured headroom 1-2 labels per sheet, not planned); (d) wipeout
bridging as the primary fix (contradicted by measurement on Civil 3D: lines run through 69 of 90 wipeouts;
dash merging does apply, R-105.14 498.58 case); (e) stationing regex (= leg 3); (f) MicroStation level
dictionary by inspection (out of scope tonight). Blunt verdict from both: this is CAD data interpretation,
not computer vision. Point (a) goes into the leg 2 and leg 4 briefs.
