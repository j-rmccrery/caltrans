# recon attribution: every dimensioned-uncovered foot, one cause

total lost across 6 sheets: 25,402.9 ft

## per-sheet bucket table (ft)

| sheet | lost_ft | no_traverse_edge_unlabelled | curve | distance_from_drawing | no_traverse_edge_labelled | bearing_from_drawing | misfit | residual_contamination |
|---|---|---|---|---|---|---|---|---|
| presidio | 5704 | 2230 | 825 | 806 | 1074 | 483 | 272 | 14 |
| r_10434_001_2020-09-16 | 5843 | 3221 | 1283 | 670 | 430 | 240 | 0 | 0 |
| r_10434_003_2020-09-16 | 9474 | 3873 | 2214 | 1752 | 767 | 529 | 340 | 0 |
| r_10741_001_2017-02-10 | 368 | 11 | 0 | 0 | 0 | 0 | 357 | 0 |
| r_10741_002_2017-02-10 | 2118 | 1585 | 217 | 280 | 36 | 0 | 0 | 0 |
| r_10741_003_2017-02-10 | 1895 | 1108 | 0 | 621 | 0 | 165 | 0 | 0 |

## all-sheets ranking

| bucket | ft | % of total lost |
|---|---|---|
| no_traverse_edge_unlabelled | 12,026.9 | 47.3% |
| curve | 4,538.4 | 17.9% |
| distance_from_drawing | 4,130.1 | 16.3% |
| no_traverse_edge_labelled | 2,308.0 | 9.1% |
| bearing_from_drawing | 1,417.1 | 5.6% |
| misfit | 968.4 | 3.8% |
| residual_contamination | 14.0 | 0.1% |
| other_flag | 0.0 | 0.0% (never the nearest row) |
| anomaly | 0.0 | 0.0% (never the nearest row) |

no_traverse_edge splits unlabelled/labelled and residual_contamination (7) is carved out of it by hand -- together they are one cause ("the record never reached this line"): 56.5% combined, the largest single cause by a wide margin over any one flag/misfit/curve bucket.

## top 3 buckets: notes and examples

### no_traverse_edge_unlabelled (12,027 ft, 47.3%)
- 46825|61806|61806-1|61806-2|63269 vicinity (r_10434_001_2020-09-16): 2859.4 ft
- 46825-5 vicinity (r_10741_002_2017-02-10): 1584.6 ft
- the record simply never reached this stretch -- no traverse.json row of any kind (line, curve, flagged or not) sits within recon.py's own buffer+direction tolerance. "labelled" means a bearing/distance-shaped text block sits within 40 pt on the sheet but never became an edge (an association miss, not a missing record); "unlabelled" means no such text sits nearby either.

### curve (4,538 ft, 17.9%)
- L=577.57' (r_10434_003_2020-09-16): 448.6 ft
- L=573.93'(T) + C16 (presidio): 430.2 ft
- loop16 leg E: a curve can be a clean rec_edge now (CB, or a tangent record line, gives its chord direction; see traverse.py's complete_curve_chords). What remains here is a curve still missing a record radius/delta, or one whose only candidate record tangents disagree (refused, not guessed).

### distance_from_drawing (4,130 ft, 16.3%)
- S5°49'27"E (r_10434_003_2020-09-16): 1150.1 ft
- N37°30'09"E (presidio): 491.1 ft

## parcel blockers (19 named faces short of closing; not summed into the ft total above)

0 faces are "one edge short" (>= 90% covered, exactly one uncovered ring piece). Closest to closing: 46825-5 (r_10741_002_2017-02-10) at 93.1% covered, 2 uncovered piece(s).

| sheet | parcel | pct_covered | counts | n_uncovered_pieces | one_edge_short | blockers_ft |
|---|---|---|---|---|---|---|
| presidio | 63269 | 0.0 | False | 3 | False | {'distance_from_drawing': 28.2, 'no_traverse_edge': 166.6} |
| presidio | 61806-4|61985-2 | 30.59 | False | 121 | False | {'curve': 624.1, 'no_traverse_edge': 746.9, 'misfit': 220.1, 'bearing_from_drawing': 168.5} |
| presidio | 61806-2 | 46.27 | False | 47 | False | {'bearing_from_drawing': 325.5, 'no_traverse_edge': 1288.8} |
| presidio | 61806-5 | 0.0 | False | 52 | False | {'no_traverse_edge': 249.2} |
| presidio | 61806 | 0.0 | False | 7 | False | {'no_traverse_edge': 485.3} |
| presidio | 61985-1|61985-2|61985-3|61985-4 | 36.0 | False | 80 | False | {'bearing_from_drawing': 151.5, 'no_traverse_edge': 1097.4, 'curve': 8.8} |
| r_10434_001_2020-09-16 | 46825 | 0.42 | False | 3 | False | {'no_traverse_edge': 407.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 73 | False | {'no_traverse_edge': 617.0, 'bearing_from_drawing': 35.6} |
| r_10434_003_2020-09-16 | 46825 | 0.0 | False | 32 | False | {'no_traverse_edge': 303.9} |
| r_10434_003_2020-09-16 | 46825|63269 | 1.9 | False | 121 | False | {'curve': 536.4, 'no_traverse_edge': 904.2, 'misfit': 182.5, 'distance_from_drawing': 1161.0} |
| r_10434_003_2020-09-16 | 61806-6 | 40.58 | False | 17 | False | {'no_traverse_edge': 249.6, 'bearing_from_drawing': 27.3, 'distance_from_drawing': 339.8} |
| r_10434_003_2020-09-16 | 61806-6|63269 | 14.18 | False | 187 | False | {'no_traverse_edge': 1162.0, 'bearing_from_drawing': 182.5, 'curve': 671.6, 'distance_from_drawing': 408.3} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 24 | False | {'curve': 141.6, 'no_traverse_edge': 160.7} |
| r_10434_003_2020-09-16 | 61806-8 | 0.0 | False | 35 | False | {'no_traverse_edge': 395.6} |
| r_10434_003_2020-09-16 | 61806-8|63269 | 25.53 | False | 73 | False | {'no_traverse_edge': 626.4, 'curve': 174.9} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 210.4} |
| r_10434_003_2020-09-16 | 61806-5 | 0.0 | False | 4 | False | {'no_traverse_edge': 672.8} |
| r_10741_002_2017-02-10 | 46825-5 | 93.08 | False | 2 | False | {'no_traverse_edge': 167.1} |
| r_10741_003_2017-02-10 | 46825-5 | 59.26 | False | 5 | False | {'distance_from_drawing': 654.6, 'no_traverse_edge': 316.9} |
