# Coverage attribution: where every parsed bearing/distance token goes

One item per (block, kind) that spike/bench.py's read_cols() counts toward bearings_parsed/distances_parsed. Denominators below match bench.csv exactly (82/307, 47/255, 83/497 -- bucket d-pass alone, not d-pass+d-pass-arc).

## presidio (307 tokens, 831 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| d-pass | 82 | reached a check and passed (counted in bench's coverage numerator) |
| c-table-tag | 55 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| a-table | 45 | not a drawing label: table cell (no tag-check found) |
| f-queued | 33 | queued with a reason (exceptions.json) |
| a-curvedata | 24 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| a-radial | 22 | not a drawing label: radial bearing, deliberately not checked |
| d-pass-arc | 16 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| a-area | 13 | not a drawing label: area/acreage figure |
| e-fail | 12 | reached a check and failed |
| a-runtotal | 3 | not a drawing label (as checked): a bare '(T)' run total, silently skipped by the distance branch's is_total guard |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| a-titleblock | 1 | not a drawing label: title block / notes / legend |
| **total** | **307** | = bearings_parsed + distances_parsed |

## r10434_1 (255 tokens, 721 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| f-queued | 51 | queued with a reason (exceptions.json) |
| d-pass | 47 | reached a check and passed (counted in bench's coverage numerator) |
| c-table-tag | 30 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| a-curvedata | 29 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| e-fail | 24 | reached a check and failed |
| a-table | 23 | not a drawing label: table cell (no tag-check found) |
| a-radial | 20 | not a drawing label: radial bearing, deliberately not checked |
| d-pass-arc | 12 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| a-area | 11 | not a drawing label: area/acreage figure |
| a-runtotal | 5 | not a drawing label (as checked): a bare '(T)' run total, silently skipped by the distance branch's is_total guard |
| a-titleblock | 2 | not a drawing label: title block / notes / legend |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| **total** | **255** | = bearings_parsed + distances_parsed |

## r10434_3 (497 tokens, 1403 blocks read, majority 2-decimal distances)

| bucket | n | meaning |
|---|---|---|
| a-table | 104 | not a drawing label: table cell (no tag-check found) |
| d-pass | 83 | reached a check and passed (counted in bench's coverage numerator) |
| c-table-tag | 68 | checked as a table tag instead (tags_checks.csv, L#/C# row) |
| f-queued | 58 | queued with a reason (exceptions.json) |
| a-radial | 54 | not a drawing label: radial bearing, deliberately not checked |
| a-curvedata | 37 | not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere |
| e-fail | 30 | reached a check and failed |
| d-pass-arc | 26 | reached a check and passed as an arc-length row (bench's coverage numerator skips this check column) |
| a-area | 13 | not a drawing label: area/acreage figure |
| a-runtotal | 12 | not a drawing label (as checked): a bare '(T)' run total, silently skipped by the distance branch's is_total guard |
| a-titleblock | 11 | not a drawing label: title block / notes / legend |
| a-notes | 1 | not a drawing label: coordinate-basis note (EPOCH/DATUM) |
| **total** | **497** | = bearings_parsed + distances_parsed |

## Crops: bucket g-dropped is EMPTY (0/0/0): every token resolved to a named reason once the '(T)' run-total guard (a-runtotal) was added. Shown here instead: every a-runtotal token

- `spike\out_coverage\crops\g_00_presidio.png` -- presidio distance `860.77'(T)` -- VERDICT: confirmed -- printed beside the R/W line inside the hatched strip, a real run total over the two leader-tagged pieces below it (860.77 = the drawn run the 2 arrows point to); genuinely checkable, currently dropped outright.
- `spike\out_coverage\crops\g_01_presidio.png` -- presidio distance `399.86'(T)` -- VERDICT: confirmed -- "MAIN LINE 2" run total beside a long straight R/W line; a real, measurable drawn length.
- `spike\out_coverage\crops\g_02_presidio.png` -- presidio distance `241.32'(T)` -- VERDICT: confirmed -- run total over L2/L5/L6/L7 (all visible, circled vertices on the drawn curve/line chain in the crop); a real sum a run-sum check could verify today.
- `spike\out_coverage\crops\g_03_r10434_1.png` -- r10434_1 distance `57.52'(T)` -- VERDICT: confirmed -- printed beside a short R/W segment near a "SEE DETAIL" callout; measurable.
- `spike\out_coverage\crops\g_04_r10434_1.png` -- r10434_1 distance `127.57'(T)` (paired with bearing N88°28'28"W, which DOES get checked) -- VERDICT: confirmed -- the bearing half of this same block is checked; only the (T) distance half is dropped. Direct evidence the guard is over-broad (kills the distance even when the line is already found for the bearing).
- `spike\out_coverage\crops\g_05_r10434_1.png` -- r10434_1 distance `222.86'(T)` -- VERDICT: confirmed -- beside a line leading into "SEE DETAIL C", paired with a coordinate callout above it (N/E) that is itself correctly excluded elsewhere.
- `spike\out_coverage\crops\g_06_r10434_1.png` / `g_07_r10434_1.png` -- r10434_1 distance `134.03'(T)` (two separate occurrences, two different lines) -- VERDICT: confirmed both -- one sits inside a NOT-TO-SCALE detail inset (arguably should also hit the `nts` exception path, but the silent is_total continue fires first and pre-empts it); the other is a normal full-scale run total.
- `spike\out_coverage\crops\g_08_r10434_3.png` -- r10434_3 distance `114.34'(T)` -- VERDICT: confirmed -- beside a fence/line-data-table boundary line, paired with a normal (checked) bearing on the same block.
- `spike\out_coverage\crops\g_09_r10434_3.png` -- r10434_3 distance `115.41'(T)` -- VERDICT: confirmed -- same block as g_08 (adjacent line), same pattern.
- `spike\out_coverage\crops\g_10_r10434_3.png` -- r10434_3 distance `494.26'(T)` -- VERDICT: confirmed -- printed along "MAIN POST SUBSTATION" boundary, a real long run.
- `spike\out_coverage\crops\g_11_r10434_3.png` -- r10434_3 distance `195.48'(T)` -- VERDICT: confirmed -- ordinary R/W line run total.
- `spike\out_coverage\crops\g_12_r10434_3.png` -- r10434_3 distance `141.40'(T)` -- VERDICT: confirmed -- ordinary run total, ordinary line.
- `spike\out_coverage\crops\g_13_r10434_3.png` -- r10434_3 distance `74.43'(T)` -- VERDICT: confirmed -- beside a line near an easement note, paired with a bearing that IS checked (same over-broad-guard pattern as g_04).
- `spike\out_coverage\crops\g_14_r10434_3.png` / `g_18_r10434_3.png` -- r10434_3 distance `102.46'(T)`/`114.34'(T)` cluster near an L#/C# line-data table header -- VERDICT: confirmed -- genuine drawn-line run totals, sitting close to (but outside) the table region.
- `spike\out_coverage\crops\g_15_r10434_3.png` -- r10434_3 distance `156.09'(T)` -- VERDICT: confirmed -- ordinary run total.
- `spike\out_coverage\crops\g_16_r10434_3.png` -- r10434_3 distance `31.57'(T)` -- VERDICT: confirmed -- beside a curve inside "DETAIL 7"; paired with a radial bearing "(R)" (itself correctly unchecked) on the same crop, unrelated to this token.
- `spike\out_coverage\crops\g_17_r10434_3.png` -- r10434_3 distance `524.56'(T)` -- VERDICT: confirmed -- "MAIN LINE 1" run total beside a long straight line crossing another alignment.
- `spike\out_coverage\crops\g_19_r10434_3.png` -- r10434_3 distance `102.46'(T)` -- VERDICT: confirmed -- see g_14.

**Summary for this set: 20/20 confirmed.** Every bare `NNN.NN'(T)` distance token is a real, measurable drawn-line run total, sitting right beside real linework. None are noise, mislabels, or table cells that leaked into the drawing population. Two (g_04, g_13) additionally show the guard firing even when the SAME block's bearing half already found and checked a line -- the drawn piece is already in hand, only the length is thrown away.

## Crops: biggest single reason (156 tokens): a-table / table cell, no matching row in tags_checks.csv (tag's own row never checked)

- `spike\out_coverage\crops\top_00_presidio.png` -- presidio distance `58.79'`, CURVE DATA TABLE(1) LENGTH column -- VERDICT: confirmed table cell; a plain, legible LENGTH value in the row above the checked 41.07'/44.62' rows. No structural reason it couldn't be checked -- its curve's tag was simply never associated.
- `spike\out_coverage\crops\top_01_presidio.png` -- presidio distance `113.14'`, CURVE DATA TABLE(2) LENGTH column, row above shows `123.12'(T)` -- VERDICT: confirmed table cell; note the row directly above is itself a table-side `(T)` run total (same is_total pattern as bucket a-runtotal, but for a table cell -- tags.py presumably also drops these).
- `spike\out_coverage\crops\top_02_presidio.png` -- presidio bearing `N74°13'41"W`, LINE DATA TABLE row L19, distance `1334.50'` on the same row -- VERDICT: confirmed table cell, and a clean one -- L19's whole row (bearing + distance) is legible with no strikethrough, no "(T)", nothing unusual, and still has no tags_checks.csv row. This is the tag-association gap, not a data-quality problem.
- `spike\out_coverage\crops\top_03_r10434_1.png` -- r10434_1 bearing `S39°04'34"E`, LINE DATA TABLE row L15 (distance 9.51') -- VERDICT: confirmed table cell; two rows above it (L13/L14) are themselves `(T)` totals. Ordinary short-course row, tag not associated.
- `spike\out_coverage\crops\top_04_r10434_1.png` -- r10434_1 distance `141.63'`, CURVE DATA TABLE LENGTH column -- VERDICT: confirmed table cell, clean row, no anomaly.
- `spike\out_coverage\crops\top_05_r10434_3.png` -- r10434_3 distance `2726.91'`, CURVE DATA TABLE row C6(T) -- VERDICT: confirmed, AND it is itself a `(T)` row (radius column, "C6(T) 2726.91' 5°37'37""); a table-side twin of the a-runtotal finding.
- `spike\out_coverage\crops\top_06_r10434_3.png` -- r10434_3 distance `31.84'`, CURVE DATA TABLE LENGTH column, row above is `35.00'(T)` -- VERDICT: confirmed clean table cell next to another table-side `(T)` row.
- `spike\out_coverage\crops\top_07_r10434_3.png` -- r10434_3 distance `10.00'`, CURVE DATA TABLE row C20 RADIUS column -- VERDICT: confirmed clean table cell (a 10 ft fillet radius, plausible small curb return).
- `spike\out_coverage\crops\top_08_r10434_3.png` -- r10434_3 distance `984.00'`, CURVE DATA TABLE row C28 RADIUS column -- VERDICT: confirmed table cell, **but rows C27-C29 are struck through** (a horizontal strike line runs across all three rows in the crop) -- these three curves are voided/superseded on the record. This is a genuinely un-checkable value for a different reason than "tag not associated": it is deliberately crossed out and should be excluded from the denominator entirely, not counted as a coverage miss.
- `spike\out_coverage\crops\top_09_r10434_3.png` -- r10434_3 distance `211.76'`, LINE DATA TABLE, unlabeled NO. column visible off-crop -- VERDICT: confirmed clean table cell.
- `spike\out_coverage\crops\top_10_r10434_3.png` -- r10434_3 bearing `S83°09'08"E`, LINE DATA TABLE row L24 (distance 15.42') -- VERDICT: confirmed clean table cell.
- `spike\out_coverage\crops\top_11_r10434_3.png` -- r10434_3 distance `45.93'`, LINE DATA TABLE, row below is `90.22'(T)` -- VERDICT: confirmed clean table cell next to a table-side `(T)` row.

**Summary for this set: 12/12 confirmed as genuine L#/C# course-table cells** (LINE DATA TABLE or CURVE DATA TABLE), all legible, almost all with no data-quality issue at all -- 1 of 12 (top_08) is struck through/voided on the record, a separate and legitimate reason to exclude it. The other 11 have nothing wrong with the cell itself: their row's tag was never associated on the drawing, so tables.py/tags.py never attempted the check. Table population totals confirm this at scale: table_rows vs tags_assoc from bench.csv (legE row) -- Presidio 44 rows / 25 tags associated (19 rows unresolved), R-10434.1 25/14 (11 unresolved), R-10434.3 83/32 (51 unresolved, with 111 queued tag reads never resolving to a clean tag) -- unresolved-row counts track the a-table population (32/23/101) almost exactly at ~2 tokens/row.

## Join rule

Bench's denominator is one item per (block, kind), kind in {bearing, distance}, wherever `checks.BEAR`/`checks.DIST`
matches some token inside the block -- bench's own `read_cols()` logic, reproduced verbatim in `coverage_attrib.py`
so the totals match `bench.csv` exactly (82/307, 47/255, 83/497). `checks.py`'s `main()` walks the same blocks list
(mirrored via `reads_path()`) and stamps every value it measures with `region(b)` = `[cx-w/2-4, cy-h/2-4, cx+w/2+4,
cy+h/2+4]` into `labels.json` (every fully-checked value, pass or fail) and `exceptions.json` (every fail plus every
unmatched/queued label). An exact region-box match against those two files tells us what `checks.py` did with a
token, with no need to re-run its geometry (leader tracing, nearest-line search, arc stitching, chord fallback). A
table cell never reaches `checks.py`'s loop at all (masked by `FURNITURE` before the loop starts) -- those are
matched instead to `tags_checks.csv` by check-kind (bearing / distance / arc length / radius) + value
(`checks.azimuth()` or float, tolerance 1e-4 deg / 0.005 ft), not 1:1 consumed, since two curves can legitimately
share one design radius or length. Region lookup resolved every token on all three sheets except the bare `(T)`
run-total case (`a-runtotal`), root-caused directly from `checks.py`'s own `is_total` guard rather than left as an
unexplained miss -- **bucket g-dropped is 0/0/0**, not a residual.

## (1) The honest denominator

"Labels on the drawing that a check could address" excludes: table cells (`a-table`, `c-table-tag` -- a different
object class, table row vs. drawing annotation), title block/notes/legend text (`a-titleblock`, `a-notes`), area
figures (`a-area`), and radial bearings (`a-radial` -- not addressable by a label-to-line check by construction, a
bearing to a curve's own center rather than along a drawn line). It keeps curve-data values (`a-curvedata` --
genuine drawing labels, addressed by the separate L=R\u0394 / drawn-radius check, which passes 40/41 times when all
three of R, \u0394, L are present: 10/10 Presidio, 17/18 R-10434.1, 13/13 R-10434.3), the bare run-totals
(`a-runtotal`), and every reached-a-check outcome (`d-pass`, `d-pass-arc`, `e-fail`, `f-queued`).

| sheet | bench denom | honest denom | bench passes (d-pass) | bench coverage | honest passes (d-pass+d-pass-arc) | honest coverage |
|---|---|---|---|---|---|---|
| presidio | 307 | 170 | 82 | 26.7% | 98 | **57.6%** |
| r10434_1 | 255 | 168 | 47 | 18.4% | 59 | **35.1%** |
| r10434_3 | 497 | 246 | 83 | 16.7% | 109 | **44.3%** |

Coverage roughly doubles once the denominator is table cells, boilerplate, and by-design exclusions instead of
"every string on the page shaped like a number." The remaining honest-denominator gap (72, 109, 137 tokens) is
almost entirely `f-queued` (33/51/58, real geometry misses: no line found, piece too short, matchline edge) and
`e-fail` (12/24/30, real disagreements) -- both legitimate outcomes checks.py already reports; nothing further to
recover from those without new geometry work.

## (2) The 2-3 biggest recoverable causes

1. **Table-row tag association gate (biggest, ~156 tokens).** `spike/tags.py`'s tag-symbol reading feeds
   `spike/tables.py`'s per-row check, which only runs once a row's own L#/C# tag is found and associated on the
   drawing. Rows with a perfectly legible bearing/distance/radius/length cell (12/12 crops confirmed clean, one
   struck-through/voided) never get *any* check when their tag isn't associated: table_rows vs tags_assoc (bench.csv,
   legE) is 44/25 Presidio (19 rows short), 25/14 R-10434.1 (11 short), 83/32 R-10434.3 (51 short, with 111 queued
   tag reads that never resolved) -- tracking the `a-table` "no matching row" counts (32/23/101) almost exactly at
   ~2 tokens/row. Fixing tag association would move ~150 tokens from unchecked to checked (mix of pass/fail, not a
   guaranteed +150 passes) but these land in `tags_checks.csv`/`tags_pass`, a column `bench.py`'s own `coverage`
   formula never reads -- this is the dominant honest-denominator gap, not a lever on bench's reported coverage
   number as computed today.
2. **`bench.py`'s own coverage arithmetic drops arc-length passes (54 tokens, zero pipeline risk).** `spike/bench.py`
   function `run()`, the line `passes = sum(int(str(res[k]).split("/")[0]) for k in ("distance", "bearing"))`, sums
   only `checks.csv` rows whose check column is exactly "distance"/"bearing" (matching `chord distance`/`chord
   bearing` via the `ks` filter above it, but never "arc length"). A distance-shaped token that passes as an
   arc-length check (a standalone `L=NNN.NN'` label, or a bare distance beside a curve) is a real, already-computed
   pass that never reaches this sum: +16 Presidio (82->98), +12 R-10434.1 (47->59), +26 R-10434.3 (83->109). One-line
   fix, no geometry change, no regression surface: add `"arc length"` to the same tally.
3. **Bare `(T)` run-total distances, dropped outright (20 tokens, small but clean).** `spike/checks.py`'s distance
   branch, `if is_total or curve_data or STATION.search(...) or AREA_CTX.search(...) or NOTES_CTX.search(...):
   continue` (~line 1552): a standalone `L=NNN.NN'(T)` block gets the sophisticated run-sum treatment
   (`len_pending`/`by_run`, further down in `main()`), but a bare `NNN.NN'(T)` with no `L=` prefix has no such
   fallback -- it is dropped unconditionally, even when (g_04, g_13 above) the SAME block's paired bearing already
   found and checked the very line the distance would measure. All 20 occurrences across the three sheets are real,
   measurable run totals (20/20 crops confirmed). Fix: route a bare is_total distance into the same run-sum pool the
   `L=`-prefixed case already uses, seeded from the paired bearing's matched line when one exists. Recoverable: up to
   20 more checked outcomes (Presidio +3, R-10434.1 +5, R-10434.3 +12); most would likely pass given how reliably the
   `L=(T)` run-sum already does.
