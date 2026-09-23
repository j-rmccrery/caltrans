# Numbers from the run — r_10434_002_2020-09-16

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: True; RMS 0.041 ft; scale 1.38885 ft/pt; grid north +0.536° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
| distance | 47 | 39 |
| bearing | 49 | 30 |
| arc length | 11 | 4 |
| curve L=R*delta | 10 | 10 |

- Where a label passes, printed vs drawn agrees to 0.03 ft median (max 0.24) and 0.55′ median bearing.
- Exception queue: 66 items = 18 genuine disagreements, 16 where the reader measured a different line, 27 labels with no line found, 5 lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- 33 of 44 table rows found on the drawing (32 distinct), 12 partial reads queued, 21 associated (18 by leader arrowhead), 33 queue items.
| check | checked | pass |
|---|---|---|
| bearing | 11 | 11 |
| distance | 10 | 10 |
| radius | 8 | 6 |
| arc length | 8 | 1 |

## Parcels
- 60 faces from the heavy linework, 8 named by a label or leader, 4 with a parcel-table area, 1 within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift 0.668 m toward 327° (dN 0.561 m, dE -0.362 m), applied to the sheet before overlay.
- Features: 35 pavement (132,757 m²), 11 viaduct deck (29,292 m²), 281 building (132,129 m²); 175 buildings pass the roof-flatness test.
- Encroachment screen: 91 building-class clusters inside parcel faces, 15 with a building verdict, 10 in named parcels (61806-2, 61806-4|61985-2, 61806|61806-4|61806-5|61806-9|63269, 61806|61985|61985-1|61985-2|61985-3|61985-4).
- Tunnel easements, ground over them: 61985-1 595 m, 20.1–71.7 m; 61985-2 595 m, 16.3–71.7 m; 61985-3 595 m, 20.1–71.7 m; 61985-4 595 m, 20.1–71.7 m (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (63269 -100 %, 61806-2 -38 %, 61806-5 -99 %) the profile runs along the wrong figure. Say so on the slide.

## Record twin, 2026-09-23 loop

Pass counts from `spike/out/bench.csv` (rows labelled `leg5-verify`):

| sheet | distance | bearing | arc length | tags associated | faces named |
|---|---|---|---|---|---|
| R-10434.2 Presidio | 39/46 | 30/49 | 4/11 | 23 | 8 |
| R-10434.1 | 25/30 | 19/30 | 4/26 | 14 | 5 |
| R-10434.3 | 41/71 | 31/50 | 7/18 | 26 | 13 |

Closed chain on r_10434_002_2020-09-16: 5 edges (5 with a full record), end misfit 0.14 ft, record area 6,970.6 sq ft.

Blocker: 61985-1..4: 0 of 4 close, blocker measured and cropped: the bubbles' leaders point to detached R/Δ/L data blocks, the easement arcs are the dashed strip elsewhere, no drawn arc within 5 glyph heights of any of the four `L=` labels.
