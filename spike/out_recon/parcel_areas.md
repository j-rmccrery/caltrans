# parcel score vs AREAS tables (loop18 leg 1 + loop19 leg 4)

headline: **2 / 19** parcels reconstructed (before loop19 leg 4's cross-sheet joins + DETAIL "A": 1 / 19); of 19 listed across the six AREAS tables, deduped by id; 15 have a matching face on some sheet.

## cross-sheet joined parcels (task 2)

| parcel | pieces (sheet:face) | pct covered | closure ft | closes | face area sqft | record area sqft | diff % |
|---|---|---|---|---|---|---|---|
| 46825 | r10434_1:46825, r10434_3:46825 | - | - | no (union is MultiPolygon, not one polygon -- pieces do not abut) | - | - | - |

## DETAIL "A" (R-10741.2, 46825-5, task 3)

status: **attached** -- 

| gap_len_ft | courses_sum_ft | len_diff_ft | pct_covered_before | pct_covered_after | closure_ft | closes |
|---|---|---|---|---|---|---|
| 167.09 | 166.97 | 0.12 | 93.08 | 100.0 | 0.01 | True |

| drawn gap piece | assigned course | bearing err deg | drawn ft |
|---|---|---|---|
| 4 | N51 deg26'23"E | 0.23 | 11.01 |
| 5 | N19 deg41'37"W | 0.01 | 156.08 |

## per-parcel vs AREAS tables

| parcel | listed on | has face | reconstructed | record area (sqft) | face area (sqft) | diff % |
|---|---|---|---|---|---|---|
| 46825 | r10434_1,r10434_3 | yes | no | ? | 782 |  |
| 46825-4 | r10741_2 | no | no | ? |  |  |
| 46825-5 | r10741_2 | yes | YES | ? | 242,470 |  |
| 61806-1 | r10434_1 | yes | no | 455,638 | 5,414 (merged) | -99.6% |
| 61806-10 | r10434_1 | no | no | 51,401 |  |  |
| 61806-2 | presidio,r10434_1 | yes | no | 314,068 | 5,414 (merged) | -99.6% |
| 61806-4 | presidio | yes | no | 145,490 | 135,164 (merged) | -16.0% |
| 61806-5 | presidio,r10434_3 | yes | no | 229,561 | 1,644 | -99.3% |
| 61806-6 | r10434_3 | yes | no | 194,713 | 17,704 | -90.9% |
| 61806-7 | r10434_3 | yes | no | 164,221 | 3,912,027 (merged) |  |
| 61806-8 | r10434_3 | yes | no | 320,602 | 2,051 | -99.4% |
| 61806-9 | presidio | yes | YES | 6,970 | 6,974 | +0.1% |
| 61985-1 | presidio | yes | no | 2,518 | 48,412 (merged) | -31.5% |
| 61985-2 | presidio | yes | no | 15,372 | 48,412 (merged) | -31.5% |
| 61985-3 | presidio | yes | no | 49,552 | 48,412 (merged) | -31.5% |
| 61985-4 | presidio | yes | no | 3,248 | 48,412 (merged) | -31.5% |
| 63269 | presidio,r10434_1,r10434_3 | yes | no | 498,762 | 1,151 | -99.8% |
| 9178-16 | r10741_1,r10741_2 | no | no | 13,355 |  |  |
| 9178-3 | r10741_3 | no | no | ? |  |  |
