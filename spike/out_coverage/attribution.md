# Coverage attribution: where every parsed bearing/distance token goes

One item per (block, kind) that spike/bench.py's read_cols() counts toward bearings_parsed/distances_parsed. Denominators below match bench.csv exactly (82/307, 47/255, 83/497 -- bucket d-pass alone, not d-pass+d-pass-arc).

## presidio (307 tokens, 831 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| d-pass | 82 | reached a check and passed (counted in bench's coverage numerator) |
| c-table-tag | 56 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| a-table | 44 | not a drawing label: table cell (no tag-check found) |
| f-queued | 41 | queued with a reason (exceptions.json) |
| a-curvedata | 24 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| a-radial | 21 | not a drawing label: radial bearing, deliberately not checked |
| d-pass-arc | 16 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| a-area | 13 | not a drawing label: area/acreage figure |
| e-fail | 8 | reached a check and failed |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| a-titleblock | 1 | not a drawing label: title block / notes / legend |
| **total** | **307** | = bearings_parsed + distances_parsed |

## r10434_1 (255 tokens, 721 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| f-queued | 64 | queued with a reason (exceptions.json) |
| d-pass | 48 | reached a check and passed (counted in bench's coverage numerator) |
| c-table-tag | 30 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| a-curvedata | 29 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| a-table | 23 | not a drawing label: table cell (no tag-check found) |
| a-radial | 18 | not a drawing label: radial bearing, deliberately not checked |
| e-fail | 17 | reached a check and failed |
| d-pass-arc | 12 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| a-area | 11 | not a drawing label: area/acreage figure |
| a-titleblock | 2 | not a drawing label: title block / notes / legend |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| **total** | **255** | = bearings_parsed + distances_parsed |

## r10434_3 (497 tokens, 1403 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| a-table | 107 | not a drawing label: table cell (no tag-check found) |
| d-pass | 89 | reached a check and passed (counted in bench's coverage numerator) |
| f-queued | 72 | queued with a reason (exceptions.json) |
| c-table-tag | 65 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| a-radial | 52 | not a drawing label: radial bearing, deliberately not checked |
| a-curvedata | 37 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| d-pass-arc | 26 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| e-fail | 24 | reached a check and failed |
| a-area | 13 | not a drawing label: area/acreage figure |
| a-titleblock | 11 | not a drawing label: title block / notes / legend |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| **total** | **497** | = bearings_parsed + distances_parsed |

## Crops: bucket g-dropped is EMPTY (0/0/0): every token resolved to a named reason once the '(T)' run-total guard (a-runtotal) was added. Shown here instead: every a-runtotal token


## Crops: biggest single reason (157 tokens): a-table / table cell, no matching row in tags_checks.csv (tag's own row never checked)

- `spike\out_coverage\crops\top_00_presidio.png` -- presidio distance `58.79'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_01_presidio.png` -- presidio distance `73.26'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_02_presidio.png` -- presidio bearing `N74°13'41"W` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_03_r10434_1.png` -- r10434_1 bearing `N38°57'14"W` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_04_r10434_1.png` -- r10434_1 distance `243.51'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_05_r10434_3.png` -- r10434_3 distance `56.26'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_06_r10434_3.png` -- r10434_3 distance `29.47'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_07_r10434_3.png` -- r10434_3 distance `969.64'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_08_r10434_3.png` -- r10434_3 distance `605.00'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_09_r10434_3.png` -- r10434_3 distance `752.02'` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_10_r10434_3.png` -- r10434_3 bearing `S83°09'08"E` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
- `spike\out_coverage\crops\top_11_r10434_3.png` -- r10434_3 bearing `N70°50'05"E` (reason: table cell, no matching row in tags_checks.csv (tag's own row never checked)) -- VERDICT: _pending_
