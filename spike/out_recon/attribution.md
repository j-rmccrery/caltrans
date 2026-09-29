# recon attribution: every dimensioned-uncovered foot, one cause

total lost across 6 sheets: 24,063.4 ft

## per-sheet bucket table (ft)

| sheet | lost_ft | no_traverse_edge_unlabelled | distance_from_drawing | curve | no_traverse_edge_labelled | bearing_from_drawing | misfit |
|---|---|---|---|---|---|---|---|
| presidio | 4660 | 2016 | 806 | 463 | 933 | 169 | 272 |
| r_10434_001_2020-09-16 | 5618 | 3449 | 670 | 829 | 430 | 240 | 0 |
| r_10434_003_2020-09-16 | 9405 | 4206 | 1752 | 1604 | 850 | 652 | 340 |
| r_10741_001_2017-02-10 | 368 | 11 | 0 | 0 | 0 | 0 | 357 |
| r_10741_002_2017-02-10 | 2118 | 1688 | 284 | 0 | 146 | 0 | 0 |
| r_10741_003_2017-02-10 | 1895 | 1108 | 621 | 0 | 0 | 165 | 0 |

## all-sheets ranking

| bucket | ft | % of total lost |
|---|---|---|
| no_traverse_edge_unlabelled | 12,478.1 | 51.9% |
| distance_from_drawing | 4,134.0 | 17.2% |
| curve | 2,896.5 | 12.0% |
| no_traverse_edge_labelled | 2,360.1 | 9.8% |
| bearing_from_drawing | 1,226.3 | 5.1% |
| misfit | 968.4 | 4.0% |
| other_flag | 0.0 | 0.0% (never the nearest row) |
| anomaly | 0.0 | 0.0% (never the nearest row) |

no_traverse_edge splits unlabelled/labelled and residual_contamination (7) is carved out of it by hand -- together they are one cause ("the record never reached this line"): 61.7% combined, the largest single cause by a wide margin over any one flag/misfit/curve bucket.

## top 3 buckets: notes and examples

### no_traverse_edge_unlabelled (12,478 ft, 51.9%)
- 46825|61806|61806-1|61806-2|63269 vicinity (r_10434_001_2020-09-16): 3088.0 ft
- 46825-5 vicinity (r_10741_002_2017-02-10): 1687.8 ft
- the record simply never reached this stretch -- no traverse.json row of any kind (line, curve, flagged or not) sits within recon.py's own buffer+direction tolerance. "labelled" means a bearing/distance-shaped text block sits within 40 pt on the sheet but never became an edge (an association miss, not a missing record); "unlabelled" means no such text sits nearby either.

### distance_from_drawing (4,134 ft, 17.2%)
- S5°49'27"E (r_10434_003_2020-09-16): 1150.1 ft
- N37°30'09"E (presidio): 491.1 ft

### curve (2,896 ft, 12.0%)
- L=577.57' (r_10434_003_2020-09-16): 448.6 ft
- L=573.93'(T) (presidio): 430.2 ft
- loop16 leg E: a curve can be a clean rec_edge now (CB, or a tangent record line, gives its chord direction; see traverse.py's complete_curve_chords). What remains here is a curve still missing a record radius/delta, or one whose only candidate record tangents disagree (refused, not guessed).

## parcel blockers (19 named faces short of closing; not summed into the ft total above)

0 faces are "one edge short" (>= 90% covered, exactly one uncovered ring piece). Closest to closing: 46825-5 (r_10741_002_2017-02-10) at 93.1% covered, 2 uncovered piece(s).

| sheet | parcel | pct_covered | counts | n_uncovered_pieces | one_edge_short | blockers_ft |
|---|---|---|---|---|---|---|
| presidio | 63269 | 0.0 | False | 3 | False | {'distance_from_drawing': 28.2, 'no_traverse_edge': 166.6} |
| presidio | 61806-4|61985-2 | 31.3 | False | 119 | False | {'curve': 557.5, 'no_traverse_edge': 798.2, 'misfit': 220.1, 'bearing_from_drawing': 168.5} |
| presidio | 61806-2 | 73.56 | False | 43 | False | {'no_traverse_edge': 784.7, 'bearing_from_drawing': 10.7} |
| presidio | 61806-5 | 0.0 | False | 52 | False | {'no_traverse_edge': 249.2} |
| presidio | 61806 | 0.0 | False | 7 | False | {'no_traverse_edge': 485.3} |
| presidio | 61985-1|61985-2|61985-3|61985-4 | 36.0 | False | 80 | False | {'bearing_from_drawing': 151.5, 'no_traverse_edge': 1097.4, 'curve': 8.8} |
| r_10434_001_2020-09-16 | 46825 | 0.42 | False | 3 | False | {'no_traverse_edge': 407.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 73 | False | {'no_traverse_edge': 617.0, 'bearing_from_drawing': 35.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 32 | False | {'no_traverse_edge': 303.9} |
| r_10434_003_2020-09-16 | 46825|63269 | 1.9 | False | 121 | False | {'curve': 203.6, 'no_traverse_edge': 1237.0, 'misfit': 182.5, 'distance_from_drawing': 1161.0} |
| r_10434_003_2020-09-16 | 61806-6 | 40.58 | False | 17 | False | {'no_traverse_edge': 249.6, 'bearing_from_drawing': 27.3, 'distance_from_drawing': 339.8} |
| r_10434_003_2020-09-16 | 61806-6|63269 | 16.33 | False | 184 | False | {'no_traverse_edge': 1235.2, 'bearing_from_drawing': 241.9, 'curve': 480.5, 'distance_from_drawing': 408.3} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 24 | False | {'curve': 141.6, 'no_traverse_edge': 160.7} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 35 | False | {'no_traverse_edge': 395.6} |
| r_10434_003_2020-09-16 | 61806-8|63269 | 25.53 | False | 73 | False | {'no_traverse_edge': 801.3} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 210.4} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 672.8} |
| r_10741_002_2017-02-10 | 46825-5 | 93.08 | False | 2 | False | {'no_traverse_edge': 167.1} |
| r_10741_003_2017-02-10 | 46825-5 | 59.26 | False | 5 | False | {'distance_from_drawing': 654.6, 'no_traverse_edge': 316.9} |
