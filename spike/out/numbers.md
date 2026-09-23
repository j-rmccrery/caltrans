# Numbers from the run — r_10434_002_2020-09-16

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: True; RMS 0.042 ft; scale 1.38886 ft/pt; grid north +0.536° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
| distance | 37 | 18 |
| bearing | 28 | 14 |
| arc length | 12 | 1 |
| curve L=R*delta | 12 | 12 |

- Where a label passes, printed vs drawn agrees to 0.03 ft median (max 0.15) and 0.4′ median bearing.
- Exception queue: 96 items = 15 genuine disagreements, 29 where the reader measured a different line, 47 labels with no line found, 5 lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- 33 of 44 table rows found on the drawing (32 distinct), 12 partial reads queued, 16 associated (16 by leader arrowhead), 37 queue items.
| check | checked | pass |
|---|---|---|
| bearing | 8 | 8 |
| distance | 8 | 8 |
| radius | 7 | 5 |
| arc length | 6 | 0 |

## Parcels
- 60 faces from the heavy linework, 5 named by a label or leader, 4 with a parcel-table area, 0 within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift 0.668 m toward 327° (dN 0.561 m, dE -0.362 m), applied to the sheet before overlay.
- Features: 35 pavement (132,757 m²), 11 viaduct deck (29,292 m²), 281 building (132,129 m²); 175 buildings pass the roof-flatness test.
- Encroachment screen: 91 building-class clusters inside parcel faces, 15 with a building verdict, 10 in named parcels (61806-2, 61806-9|63269|61806, 61985-2, 61985-4).
- Tunnel easements, ground over them: 61985-2 310 m, 16.3–35.4 m; 61985-4 595 m, 20.1–71.7 m (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (61985-2 +779 %, 61806-2 -38 %, 61985-4 +37572 %, 61806-5 -99 %) the profile runs along the wrong figure. Say so on the slide.
