# Numbers from the run — r_10434_002_2020-09-16

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: True; RMS 0.044 ft; scale 1.38886 ft/pt; grid north +0.536° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
| distance | 39 | 13 |
| bearing | 32 | 17 |
| arc length | 14 | 3 |

- Where a label passes, printed vs drawn agrees to 0.03 ft median (max 0.1) and 0.4′ median bearing.
- Exception queue: 86 items = 11 genuine disagreements, 41 where the reader measured a different line, 30 labels with no line found, 4 lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- 36 of 44 table rows found on the drawing (36 distinct), 8 partial reads queued, 18 associated (18 by leader arrowhead), 32 queue items.
| check | checked | pass |
|---|---|---|
| bearing | 9 | 9 |
| distance | 8 | 8 |
| radius | 7 | 5 |
| arc length | 5 | 1 |

## Parcels
- 52 faces from the heavy linework, 4 named by a label or leader, 3 with a parcel-table area, 0 within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift 0.668 m toward 327° (dN 0.561 m, dE -0.362 m), applied to the sheet before overlay.
- Features: 33 pavement (131,754 m²), 11 viaduct deck (29,292 m²), 281 building (132,129 m²); 175 buildings pass the roof-flatness test.
- Encroachment screen: 90 building-class clusters inside parcel faces, 15 with a building verdict, 9 in named parcels (61806-9|63269|61806, 61985-2, 61985-4).
- Tunnel easements, ground over them: 61985-2 310 m, 16.3–35.4 m; 61985-4 535 m, 17.8–34.9 m (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (61985-2 +779 %, 61985-4 +19191 %, 61806-5 -99 %) the profile runs along the wrong figure. Say so on the slide.
