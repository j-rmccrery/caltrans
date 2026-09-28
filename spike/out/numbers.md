# Numbers from the run — r_10434_002_2020-09-16

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: True; RMS 0.041 ft; scale 1.38885 ft/pt; grid north +0.536° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
| distance | 48 | 43 |
| bearing | 44 | 43 |
| arc length | 15 | 13 |
| curve L=R*delta | 10 | 10 |

- Where a label passes, printed vs drawn agrees to 0.03 ft median (max 0.24) and 0.9′ median bearing.
- Exception queue: 42 items = 1 genuine disagreements, 7 where the reader measured a different line, 28 labels with no line found, 6 lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- 32 of 44 table rows found on the drawing (32 distinct), 14 partial reads queued, 27 associated (20 by leader arrowhead), 30 queue items.
| check | checked | pass |
|---|---|---|
| bearing | 14 | 14 |
| distance | 10 | 10 |
| radius | 8 | 5 |
| arc length | 11 | 6 |

## Parcels
- 61 faces from the heavy linework, 9 named by a label or leader, 5 with a parcel-table area, 1 within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift 0.668 m toward 327° (dN 0.561 m, dE -0.362 m), applied to the sheet before overlay.
- Features: 35 pavement (132,757 m²), 13 viaduct deck (29,402 m²), 281 building (132,129 m²); 175 buildings pass the roof-flatness test.
- Encroachment screen: 94 building-class clusters inside parcel faces, 15 with a building verdict, 10 in named parcels (61806-2, 61806-4|61985-2, 61806|61806-4|61806-5|61806-9|63269, 61806|61985|61985-1|61985-2|61985-3|61985-4).
- Tunnel easements, ground over them: 61985-1 595 m, 20.1–71.7 m; 61985-2 595 m, 16.3–71.7 m; 61985-3 595 m, 20.1–71.7 m; 61985-4 595 m, 20.1–71.7 m (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (63269 -100 %, 61806-2 -38 %, 61806-5 -99 %, 61985-1|61985-2|61985-3|61985-4 -32 %) the profile runs along the wrong figure. Say so on the slide.

## Record twin, 2026-09-23 loop 2

Pass counts from `spike/out/bench.csv` (rows labelled `loop9-final`):

| sheet | distance | bearing | arc length | tags associated | faces named |
|---|---|---|---|---|---|
| R-10434.2 Presidio | 41/49 | 41/43 | 16/19 | 25 | 9 |
| R-10434.1 | 26/37 | 21/23 | 12/24 | 14 | 5 |
| R-10434.3 | 42/59 | 41/42 | 26/39 | 28 | 12 |
| R-10741.1 | 14/18 | 13/13 | 1/2 | 0 | 0 |
| R-10741.2 | 20/20 | 18/18 | 0/1 | 0 | 2 |
| R-10741.3 | 17/17 | 13/13 | 0/1 | 0 | 1 |

Closed chain on r_10434_002_2020-09-16: 5 edges (5 with a full record), end misfit 0.14 ft, record area 6,970.6 sq ft.

Blocker: 61985-1..4 do not close as separate figures. The drawing carries them as one strip (dashed easement layer under the R/W line and parallel to it), 48,410 sq ft against a table sum of 70,690 (-31.5 %); no drawn stroke divides the four, and their printed curve data sits on the R/W line. The four stay queued; the envelope is what is measured.
