# Numbers from the run — r_10434_002_2020-09-16

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: True; RMS 0.042 ft; scale 1.38886 ft/pt; grid north +0.536° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
| distance | 46 | 25 |
| bearing | 20 | 12 |
| arc length | 13 | 3 |

- Where a label passes, printed vs drawn agrees to 0.03 ft median (max 0.09) and 0.4′ median bearing.
- Exception queue: 61 items = 8 genuine disagreements, 31 where the reader measured a different line, 18 labels with no line found, 4 lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- 36 of 44 table rows found on the drawing (36 distinct), 7 partial reads queued, 21 associated (20 by leader arrowhead), 34 queue items.
| check | checked | pass |
|---|---|---|
| bearing | 11 | 9 |
| distance | 10 | 8 |
| radius | 4 | 4 |
| arc length | 10 | 2 |

## Parcels
- 27 faces from the heavy linework, 6 named by a label or leader, 5 with a parcel-table area, 0 within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift 0.668 m toward 327° (dN 0.561 m, dE -0.362 m), applied to the sheet before overlay.
- Features: 32 pavement (119,219 m²), 11 viaduct deck (29,292 m²), 281 building (132,129 m²); 175 buildings pass the roof-flatness test.
- Encroachment screen: 73 building-class clusters inside parcel faces, 9 with a building verdict, 6 in named parcels (61806-2, 61806-9|63269|61806, 61985-2, 61985-4, 63269).
- Tunnel easements, ground over them: 61985-2 310 m, 16.3–35.4 m; 61985-4 595 m, 24.2–66.2 m (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (63269 -68 %, 61985-2 +779 %, 61806-2 -39 %, 61985-4 +50484 %, 61806-5 -99 %) the profile runs along the wrong figure. Say so on the slide.
