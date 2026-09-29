# recon ceiling: no_traverse_edge, classified

class a = dimensioned here, not read/associated (next fix) | b = dimensioned on a matchline neighbour | c = referenced, not dimensioned here (a different sheet/deed) | c_T = a bare (T) total nearby, no per-piece breakdown yet (loop18 leg 1: reachable in principle, split out of c) | d = not dimensioned anywhere in the set (true ceiling loss) | e = contamination (not boundary)

| sheet | notrav_ft | a | b | c | c_T | d | e | recon_dim_denom | recon_dim_covered |
|---|---|---|---|---|---|---|---|---|---|
| presidio | 3318 | 1833 | 0 | 473 | 969 | 30 | 14 | 10000 | 4296 |
| r_10434_001_2020-09-16 | 3651 | 411 | 0 | 511 | 246 | 1429 | 1054 | 8172 | 2329 |
| r_10434_003_2020-09-16 | 4639 | 1213 | 0 | 758 | 1118 | 1551 | 0 | 13256 | 3782 |
| r_10741_001_2017-02-10 | 11 | 11 | 0 | 0 | 0 | 0 | 0 | 6325 | 5958 |
| r_10741_002_2017-02-10 | 1621 | 90 | 291 | 0 | 0 | 1240 | 0 | 8772 | 6653 |
| r_10741_003_2017-02-10 | 1109 | 143 | 333 | 0 | 0 | 632 | 0 | 6501 | 4606 |
| **total** | 14349 | 3701 | 624 | 1741 | 2332 | 4883 | 1068 | 53026 | 27623 |

## reached but unclean (loop18 leg 1, JR): a traverse row already sits on this stretch, but is itself flagged or misfit -- reachable in principle, a read/association fix rather than a missing record. recon_attrib.py's own buckets, summed per sheet:

| sheet | curve | distance_from_drawing | bearing_from_drawing | misfit | unclean total |
|---|---|---|---|---|---|
| presidio | 0 | 0 | 0 | 0 | 0 |
| r_10434_001_2020-09-16 | 1283 | 670 | 240 | 0 | 2192 |
| r_10434_003_2020-09-16 | 2214 | 1752 | 529 | 340 | 4835 |
| r_10741_001_2017-02-10 | 0 | 0 | 0 | 357 | 357 |
| r_10741_002_2017-02-10 | 217 | 280 | 0 | 0 | 497 |
| r_10741_003_2017-02-10 | 0 | 621 | 165 | 0 | 786 |
| **total** |  |  |  |  | 8668 |

## ceiling implied by this split

ceiling_reachable = covered + a + b + c_T + unclean (record dimensions or already reaches it, pipeline could in principle complete it); ceiling_honest = ceiling_reachable / (denom - c - d - e) (denominator narrowed to boundary THIS record actually dimensions, on this or a neighbour sheet -- c_T and unclean stay IN the denominator, since both are already-dimensioned boundary a fix can reach, unlike c/d/e).

| sheet | current_pct | ceiling_reachable_pct | ceiling_honest_pct (denom - c,d,e) |
|---|---|---|---|
| presidio | 43.0 | 71.0 | 74.8 |
| r_10434_001_2020-09-16 | 28.5 | 63.4 | 100.0 |
| r_10434_003_2020-09-16 | 28.5 | 82.6 | 100.0 |
| r_10741_001_2017-02-10 | 94.2 | 100.0 | 100.0 |
| r_10741_002_2017-02-10 | 75.8 | 85.9 | 100.0 |
| r_10741_003_2017-02-10 | 70.8 | 90.3 | 100.0 |
| **total (per-sheet sum, OLD basis)** | 52.1 | 81.0 | 94.7 |

### same split, denominator/covered from the deduped SET (recon_set.py) instead of the per-sheet sum

current_pct and ceiling_reachable_pct only -- ceiling_honest_pct (denom - c,d,e) is NOT restated here: c/b/c_T/unclean/d/e are still the per-sheet SUM (recon_ceiling's own run_sheet() classifies one sheet's own no_traverse_edge pool at a time, not the pooled/deduped set), so subtracting them from the SET's own deduped, overlap-free denominator double-subtracts the shared matchline ground and can push the ratio past 100% (measured, dropped rather than published wrong). A deduped class breakdown is a separate leg.

| basis | current_pct | ceiling_reachable_pct |
|---|---|---|
| OLD (per-sheet sum) | 52.1 | 81.0 |
| NEW (deduped set) | 52.4 | 84.7 |

## top 5 class-a runs (next fixes)

- presidio 346.4 ft az 105.7: bearing N74°18'38"W (25.3 ft away, diff 0.001 deg) in "N74°18'38"W"
- presidio 324.8 ft az 255.1: bearing S75°04'24"W (200.1 ft away, diff 0.029 deg) in "S75°04'24"W|154.98'"
- r_10434_003_2020-09-16 146.5 ft az 348.0: distance 147.28' (164.0 ft away, diff 0.87 ft) in "N69°25'55"E|147.28'"
- presidio 143.7 ft az 284.8: bearing S74°57'42"E (46.5 ft away, diff 0.23 deg) in "S74°57'42"E|113.39'"
- r_10741_003_2017-02-10 137.2 ft az 231.4: bearing N51°26'23"E (44.2 ft away, diff 0.016 deg) in "～—/N51°26'23"E"
