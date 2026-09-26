# record_checks.py summary

## R-10434.2
- Part A: 8 alignment rows read.
  - curve-flagged pairs (6, chord vs arc expected to differ): median 15.00 ft, max 25.09 ft
  - 2/6 row pairs are non-monotonic in station (table is not one single ascending traverse; expected where curves/points interleave)
  - 1 pair(s) with a huge station jump but a small, plausible chord: these rows sit on a DIFFERENT reference line/stationing than their table neighbour (two alignments sharing one coordinate table), not an error
  - vs georef fit -> nearest vertex: median 0.07 ft, max 3.06 ft over 8 rows
  - alt fit from alignment rows only (8 vertex-matched points): scale 1.38905 ft/pt (callout fit +0.00020 diff), rotation diff +0.0247 deg, rms 0.97 ft
- Part B: no drawn station labels found outside table regions.
- Part C: 23 curve rows (L=R*delta fails: 0), 21 line rows (bad cell count: 0).
  - chord check: no chord column printed in this sheet's curve tables (cells are always R, delta, L)
  - tangency (info): 25 tags have traced geometry; adjacent-endpoint pairs found {'line-line': 4, 'line-curve': 5, 'curve-curve': 5}; 0/0 direct line-curve-line joins match printed delta within tolerance

## R-10434.1
- Part A: 17 alignment rows read.
  - straight pairs (3): |chord - station diff| median 17.21 ft, max 22.68 ft
  - curve-flagged pairs (11, chord vs arc expected to differ): median 16.50 ft, max 758.30 ft
  - 4/14 row pairs are non-monotonic in station (table is not one single ascending traverse; expected where curves/points interleave)
  - 2 pair(s) with a huge chord but a plausible station step: OCR/SHX misread N or E digit, not a record fact -- crops rendered: 113+69.58 PCC, 117+26.79 EC, 122+98.84 POT
  - vs georef fit -> nearest vertex: median 0.04 ft, max 236.84 ft over 16 rows
  - 1 row(s) off by >1000 ft vs the fit: same misread rows as above, excluded from the stat
  - alt fit from alignment rows only (14 vertex-matched points): scale 1.38889 ft/pt (callout fit +0.00001 diff), rotation diff +0.0116 deg, rms 0.80 ft
- Part B: 1 station labels on the drawing, 1 within 15 pt of a drawn segment.
- Part C: 7 curve rows (L=R*delta fails: 0), 18 line rows (bad cell count: 0).
  - chord check: no chord column printed in this sheet's curve tables (cells are always R, delta, L)
  - tangency (info): 14 tags have traced geometry; adjacent-endpoint pairs found {'line-line': 8, 'line-curve': 0, 'curve-curve': 0}; 0/0 direct line-curve-line joins match printed delta within tolerance

## R-10434.3
- Part A: 33 alignment rows read.
  - curve-flagged pairs (24, chord vs arc expected to differ): median 0.12 ft, max 32.91 ft
  - 7 pair(s) with a huge station jump but a small, plausible chord: these rows sit on a DIFFERENT reference line/stationing than their table neighbour (two alignments sharing one coordinate table), not an error
  - vs georef fit -> nearest vertex: median 0.02 ft, max 2.47 ft over 33 rows
  - alt fit from alignment rows only (33 vertex-matched points): scale 1.38882 ft/pt (callout fit -0.00004 diff), rotation diff +0.0082 deg, rms 0.41 ft
- Part B: 7 station labels on the drawing, 7 within 15 pt of a drawn segment.
  - along-line distance (straight-line proxy) vs station diff, 5 consecutive pairs: median |diff| 364.8 ft, max 615.8 ft
  - line_dist is straight-line ft between the two labels' nearest-segment points, not arc-traced along curves, and 'nearest segment' can pick the wrong parallel line (same ambiguity STATE.md's Known Traps already documents for this codebase)
- Part C: 38 curve rows (L=R*delta fails: 0), 33 line rows (bad cell count: 12).
  - chord check: no chord column printed in this sheet's curve tables (cells are always R, delta, L)
  - tangency (info): 28 tags have traced geometry; adjacent-endpoint pairs found {'line-line': 6, 'line-curve': 0, 'curve-curve': 0}; 0/0 direct line-curve-line joins match printed delta within tolerance
  - crops rendered for classification: L34, L35, L36, L37, L38, L39, L40, L41, L42, L43, L44, L45

## R-10741.1
- Part A: no ALIGNMENT DATA table (no STATION/NORTHING/EASTING header) on this sheet.
- Part B: no drawn station labels found outside table regions.
- Part C: no L#/C# line/curve table found on this sheet.

## R-10741.2
- Part A: no ALIGNMENT DATA table (no STATION/NORTHING/EASTING header) on this sheet.
- Part B: no drawn station labels found outside table regions.
- Part C: no L#/C# line/curve table found on this sheet.

## R-10741.3
- Part A: no ALIGNMENT DATA table (no STATION/NORTHING/EASTING header) on this sheet.
- Part B: no drawn station labels found outside table regions.
- Part C: no L#/C# line/curve table found on this sheet.
