# recon ceiling: no_traverse_edge, classified

class a = dimensioned here, not read/associated (next fix) | b = dimensioned on a matchline neighbour | c = referenced, not dimensioned here | d = not dimensioned anywhere in the set (true ceiling loss) | e = contamination (not boundary)

| sheet | notrav_ft | a | b | c | d | e | recon_dim_denom | recon_dim_covered |
|---|---|---|---|---|---|---|---|---|
| presidio | 4104 | 1833 | 0 | 1468 | 30 | 774 | 10577 | 3881 |
| r_10434_001_2020-09-16 | 4090 | 411 | 0 | 757 | 1429 | 1493 | 8556 | 2033 |
| r_10434_003_2020-09-16 | 4677 | 1251 | 0 | 1875 | 1551 | 0 | 13142 | 3119 |
| r_10741_001_2017-02-10 | 11 | 11 | 0 | 0 | 0 | 0 | 6282 | 5300 |
| r_10741_002_2017-02-10 | 1621 | 90 | 106 | 0 | 1425 | 0 | 8772 | 6653 |
| r_10741_003_2017-02-10 | 1109 | 143 | 333 | 0 | 632 | 0 | 6501 | 4606 |
| **total** | 15612 | 3739 | 439 | 4099 | 5067 | 2267 | 53829 | 25592 |

## ceiling implied by this split

ceiling_reachable = covered + a + b (record dimensions it, pipeline could in principle reach it); ceiling_honest = ceiling_reachable / (denom - c - d - e) (denominator narrowed to boundary THIS record actually dimensions, on this or a neighbour sheet).

| sheet | current_pct | ceiling_reachable_pct | ceiling_honest_pct (denom - c,d,e) |
|---|---|---|---|
| presidio | 36.7 | 54.0 | 68.8 |
| r_10434_001_2020-09-16 | 23.8 | 28.6 | 50.1 |
| r_10434_003_2020-09-16 | 23.7 | 33.3 | 45.0 |
| r_10741_001_2017-02-10 | 84.4 | 84.5 | 84.5 |
| r_10741_002_2017-02-10 | 75.8 | 78.1 | 93.2 |
| r_10741_003_2017-02-10 | 70.8 | 78.2 | 86.6 |
| **total** | 47.5 | 55.3 | 70.2 |

## top 5 class-a runs (next fixes)

- presidio 346.4 ft az 105.7: bearing N74°18'38"W (25.3 ft away, diff 0.001 deg) in "N74°18'38"W"
- presidio 324.8 ft az 255.1: bearing S75°04'24"W (200.1 ft away, diff 0.029 deg) in "S75°04'24"W|154.98'"
- r_10434_003_2020-09-16 146.5 ft az 348.0: distance 147.28' (164.0 ft away, diff 0.87 ft) in "N69°25'55"E|147.28'"
- presidio 143.7 ft az 284.8: bearing S74°57'42"E (46.5 ft away, diff 0.23 deg) in "S74°57'42"E|113.39'"
- r_10741_003_2017-02-10 137.2 ft az 231.4: bearing N51°26'23"E (44.2 ft away, diff 0.016 deg) in "～—/N51°26'23"E"
