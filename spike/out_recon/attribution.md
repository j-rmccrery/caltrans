# recon attribution: every dimensioned-uncovered foot, one cause

total lost across 6 sheets: 32,513.4 ft

## per-sheet bucket table (ft)

| sheet | lost_ft | no_traverse_edge_unlabelled | curve | bearing_from_drawing | distance_from_drawing | no_traverse_edge_labelled | misfit | residual_contamination |
|---|---|---|---|---|---|---|---|---|
| presidio | 7369 | 2194 | 1171 | 514 | 776 | 1244 | 804 | 666 |
| r_10434_001_2020-09-16 | 6702 | 3563 | 1524 | 240 | 670 | 527 | 179 | 0 |
| r_10434_003_2020-09-16 | 10465 | 3068 | 2829 | 529 | 1752 | 1605 | 681 | 0 |
| r_10741_001_2017-02-10 | 1926 | 11 | 615 | 944 | 0 | 0 | 357 | 0 |
| r_10741_002_2017-02-10 | 2973 | 1585 | 217 | 854 | 280 | 36 | 0 | 0 |
| r_10741_003_2017-02-10 | 3079 | 1099 | 0 | 1405 | 565 | 9 | 0 | 0 |

## all-sheets ranking

| bucket | ft | % of total lost |
|---|---|---|
| no_traverse_edge_unlabelled | 11,520.0 | 35.4% |
| curve | 6,355.7 | 19.5% |
| bearing_from_drawing | 4,485.3 | 13.8% |
| distance_from_drawing | 4,043.6 | 12.4% |
| no_traverse_edge_labelled | 3,422.0 | 10.5% |
| misfit | 2,020.7 | 6.2% |
| residual_contamination | 666.1 | 2.0% |
| other_flag | 0.0 | 0.0% (never the nearest row) |
| anomaly | 0.0 | 0.0% (never the nearest row) |

no_traverse_edge splits unlabelled/labelled and residual_contamination (7) is carved out of it by hand -- together they are one cause ("the record never reached this line"): 48.0% combined, the largest single cause by a wide margin over any one flag/misfit/curve bucket.

## top 3 buckets: notes and examples

### no_traverse_edge_unlabelled (11,520 ft, 35.4%)
- 46825|61806|61806-1|61806-2|63269 vicinity (r_10434_001_2020-09-16): 3201.6 ft
- 46825-5 vicinity (r_10741_002_2017-02-10): 1584.6 ft
- the record simply never reached this stretch -- no traverse.json row of any kind (line, curve, flagged or not) sits within recon.py's own buffer+direction tolerance. "labelled" means a bearing/distance-shaped text block sits within 40 pt on the sheet but never became an edge (an association miss, not a missing record); "unlabelled" means no such text sits nearby either.

### curve (6,356 ft, 19.5%)
- L=660.20' (r_10741_001_2017-02-10): 614.6 ft
- L=577.57' (r_10434_003_2020-09-16): 447.6 ft
- loop16 leg E: a curve can be a clean rec_edge now (CB, or a tangent record line, gives its chord direction; see traverse.py's complete_curve_chords). What remains here is a curve still missing a record radius/delta, or one whose only candidate record tangents disagree (refused, not guessed).

### bearing_from_drawing (4,485 ft, 13.8%)
- 598.06' (r_10741_003_2017-02-10): 598.4 ft
- 598.06' (r_10741_002_2017-02-10): 596.2 ft

## parcel blockers (20 named faces short of closing; not summed into the ft total above)

0 faces are "one edge short" (>= 90% covered, exactly one uncovered ring piece). Closest to closing: 61806-9 (presidio) at 98.1% covered, 2 uncovered piece(s).

| sheet | parcel | pct_covered | counts | n_uncovered_pieces | one_edge_short | blockers_ft |
|---|---|---|---|---|---|---|
| presidio | 63269 | 0.0 | False | 3 | False | {'misfit': 28.2, 'no_traverse_edge': 166.6} |
| presidio | 61806-4|61985-2 | 17.95 | False | 191 | False | {'curve': 886.0, 'no_traverse_edge': 751.8, 'misfit': 242.5, 'bearing_from_drawing': 168.5} |
| presidio | 61806-2 | 40.17 | False | 48 | False | {'bearing_from_drawing': 325.5, 'no_traverse_edge': 1288.8, 'misfit': 182.6} |
| presidio | 61806-9 | 98.06 | False | 2 | False | {'no_traverse_edge': 8.0} |
| presidio | 61806-5 | 0.0 | False | 52 | False | {'no_traverse_edge': 249.2} |
| presidio | 61806 | 0.0 | False | 7 | False | {'no_traverse_edge': 485.3} |
| presidio | 61985-1|61985-2|61985-3|61985-4 | 6.72 | False | 124 | False | {'curve': 548.0, 'bearing_from_drawing': 151.5, 'misfit': 25.2, 'no_traverse_edge': 1097.4} |
| r_10434_001_2020-09-16 | 46825 | 0.42 | False | 3 | False | {'no_traverse_edge': 407.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 73 | False | {'no_traverse_edge': 617.0, 'bearing_from_drawing': 35.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 32 | False | {'no_traverse_edge': 303.9} |
| r_10434_003_2020-09-16 | 46825|63269 | 0.4 | False | 130 | False | {'curve': 574.8, 'no_traverse_edge': 904.2, 'misfit': 185.8, 'distance_from_drawing': 1161.0} |
| r_10434_003_2020-09-16 | 61806-6 | 31.55 | False | 20 | False | {'misfit': 89.0, 'no_traverse_edge': 249.6, 'bearing_from_drawing': 27.3, 'distance_from_drawing': 339.8} |
| r_10434_003_2020-09-16 | 61806-6|63269 | 14.18 | False | 187 | False | {'no_traverse_edge': 1162.0, 'bearing_from_drawing': 182.5, 'curve': 671.6, 'distance_from_drawing': 408.3} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 24 | False | {'curve': 141.6, 'no_traverse_edge': 160.7} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 35 | False | {'no_traverse_edge': 395.6} |
| r_10434_003_2020-09-16 | 61806-8|63269 | 25.53 | False | 73 | False | {'no_traverse_edge': 626.4, 'curve': 174.9} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 210.4} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 672.8} |
| r_10741_002_2017-02-10 | 46825-5 | 93.08 | False | 2 | False | {'no_traverse_edge': 167.1} |
| r_10741_003_2017-02-10 | 46825-5 | 59.26 | False | 5 | False | {'distance_from_drawing': 654.6, 'no_traverse_edge': 316.9} |
