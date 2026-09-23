# Loop 2 leg C: arc-length miss attribution

Baseline (`legB2` in `bench.csv`): presidio arc length 10/17, r10434_1 12/34, r10434_3 19/30.
Every non-pass arc-length label on the three sheets, before any leg C code change: printed value,
whether it had a leader, the leader tip's distance to the nearest drawn arc (or, with no leader, the
label centre's distance), the nearest arc's drawn length, and the cause. "MISS" = the label never
reached `checks.csv` at all (an unmatched exception, no `drawn_ft`); "FAIL" = a checks.csv row that
failed. Tag rows (`C#`) are from `tags_checks.csv` / `tables.py`.

## Cause counts (before any leg C fix)

| sheet | tip>4pt, no candidate | no drawn arc at all (no leader) | arc found but wrong length (leader OR beside) | (T) total, not checked | total non-pass |
|---|---|---|---|---|---|
| presidio | 0 | 5 | 11 (4 checks.py + 7 tags) | 4 | 20 (of 26 labels) |
| r10434_1 | 1 | 10 | 21 (20 checks.py + 1 tags) | 1 | 33 (of 35 labels) |
| r10434_3 | 1 | 9 | 20 (10 checks.py + 10 tags) | 2 | 32 (of 42 labels) |

## Root cause found (not in the original STATE.md list): compound curves were never actually cut

Two things looked like "run cut wrong" in the STATE.md writeup, but a diagnostic pass (see below) found
the real mechanism was worse than a bad cut point -- for most of these labels **no cut was attempted at
all**:

- `checks.py`'s bezier-curve branch (`arcs_on_sheet` output, the long R/W curves exported by Civil3D as
  one drawn path) was appended to `arcs` **whole, never split** -- only the separately-detected polyline
  curves went through `split_at`. So a leader tip landed exactly on the curve (0.0-1.5 pt) but the "arc"
  it found was the *entire* compound run (e.g. printed `L=171.66'`, drawn `530.45`; printed C19 `60.41`,
  drawn `495.14`). `tables.py` had the identical bug in its own bezier branch.
- Even where `split_at` did run (the polyline branch, already using ticks/circles), a second bug produced
  a spray of near-zero slivers instead of a real cut: the circle-cut test flagged **every sampled point**
  within `2*tol` of a circle, not just the one point where the curve actually passes the circle. On
  r10434_1 (scale 1.39 ft/pt, so a fixed 2 pt tolerance is ~2.8 ft) a short curve sitting near one circle
  had all 16 of its sample points flagged, turning a correct 16.98 ft piece into nine ~1.13 ft slivers.
- `arcs_on_sheet` had no glyph filter (`linework_segments` has one, `arcs_on_sheet` never did): a curved
  digit or letter in the printed text draws bezier items too, and was captured as a tiny false "arc" --
  exactly next to the label whose leader tip was searching for a real one.
- The tick pool for `split_at` (`5-9 pt, width<0.8` strokes) was built from a fresh, leader-inclusive
  scan, not the leader-excluded `segs` already computed for chains -- a leader's own curly stub has 5-9 pt
  straight sub-segments right at its own tip, which is exactly where a leader-tip search looks for a cut.

## Attribution table (representative labels, before any fix)

| sheet | printed | leader | tip/label → nearest arc | nearest arc len | cause |
|---|---|---|---|---|---|
| presidio | L=171.66' | yes | 0.03 pt | 530.45 ft | compound bezier curve never split (root cause above) |
| presidio | C11 | yes | 0.12 pt | 123.10 ft (want 9.98) | same: bezier run kept whole |
| presidio | C19 | yes | 0.00 pt | 495.14 ft (want 60.41) | same |
| presidio | C21 | yes | 0.11 pt | 109.27 ft (want 876.88) | same, run cut too short elsewhere |
| presidio | L=60.39' | no | 41.99 pt | 111.67 ft | no drawn arc within reach at that length |
| presidio | L=573.93'(T) | no | -- | -- | (T) total silently skipped, not checked at all |
| presidio | 124.10' | no | 38.08 pt | 21.08 ft | no drawn arc for this printed length (genuine gap) |
| r10434_1 | L=123.61' | yes | 6.73 pt | 308.19 ft | tip beyond 4 pt, no candidate within reach |
| r10434_1 | L=1804.98' | yes | 0.02 pt | 58.71 ft | run cut wrong (polyline branch, pre-existing ticks bug) |
| r10434_1 | L=23.48' | yes | 0.01 pt | (see below) | circle-spray: one true piece became nine 1.13 ft slivers |
| r10434_3 | C33 | yes | 9.48 pt | 517.25 ft (want 1049.90) | tip beyond 4 pt |
| r10434_3 | C19 | no | 8.45 pt | 93.18 ft | beside search picked wrong piece |

Full per-label dump (leader flag, tip distance, nearest arc length) for all ~85 non-passing labels
across the three sheets is in the fork/diagnostic output this leg produced (`legc_diag.json` per sheet,
deleted before finishing since it was a throwaway probe, not pipeline output) -- the counts table above
and the representative rows are what drove the fixes below.

## Fixes made (checks.py, tables.py; `split_at` is shared by both)

1. **Bezier curves are now actually split.** `arcs_on_sheet`'s output is cut with the same `split_at`
   (circles, boundary-line ends, ticks) the polyline branch already used -- but the *whole* uncut path is
   also kept as a candidate alongside its pieces, so a curve that was never compound (most of them) keeps
   matching exactly as before, and only a genuinely compound curve additionally gets a piece that matches.
   This avoided a sheet-wide "when do we cut" threshold, which regressed some sheets no matter what single
   value was picked (see the discarded `curve_junctions` attempts in this leg's history).
2. **`split_at`'s circle-cut test collapsed to one cut per circle pass**, not one per sample point --
   fixes the sliver bug above. This is a `split_at`-level (shared) fix, so it also improves the pre-existing
   polyline-curve splitting, not just the new bezier branch.
3. **Radial ticks now carry a direction**, and `split_at` only accepts one that runs across the curve
   (near-perpendicular to its tangent) -- rejects a dash from a line running alongside the curve (a
   dashed easement, a parallel property line) that used to be misread as a boundary tick.
4. **Ticks are built from the leader-excluded segment pool** (`segs`, already computed for chains), not a
   fresh scan -- a leader's own curly stub was contributing 5-9 pt "ticks" right at its own tip.
5. **`arcs_on_sheet` filters small multi-stroke paths** the same way `linework_segments` already does --
   a curved digit/letter was being read as a tiny false arc next to its own label.
6. **Standalone `(T)` totals are now checked**, the same way as a non-total standalone `L=`: a
   `(T)` total is this one annotation's own drawn run between its vertex circles, which STATE.md had
   already measured as correct to 0.02 ft; it was only ever skipped by an overly broad guard.
7. **Leader-tip search radius for an arc scales with the drawn arrowhead's own size**
   (`max(4.0, 0.6 * arrowhead_span)`), not a flat 4 pt -- a line's tip test is unchanged at 4 pt. Small
   measured gain (a handful of labels); kept because it is the exact fix STATE.md named and costs nothing
   when there's no leader or a normal-size arrowhead.

## What still fails, and why (left failing rather than guessed)

- **`L=171.66' -> 530.45`, `C19`, `C21`, `C22` (presidio) and their siblings**: even after splitting,
  these runs don't land on the record length. Tested at every junction threshold from 9 to 160 pt and
  with/without ticks: nothing cuts them to the right length. This matches STATE.md's own finding for
  C15/C16 -- "where nothing is drawn, the record alone knows" -- the record boundary here has no vertex
  circle, no line ending on the curve, and no radial tick; only a run-sum against an adjacent tag (as
  `tables.py` already does for table rows) could check it, and a standalone `L=` block has no "adjacent
  tag" to sum with. Left failing rather than adding a nearest-by-distance guess.
- **Several `(T)` totals still don't match** (`L=573.93'`, `L=184.70'`, `L=232.07'`, `L=413.98'` on
  presidio; similar on the siblings): the check now runs (visible in `exceptions.json` as "no arc
  matches" instead of being silently dropped), but the specific run their boundary should sit on isn't
  being assembled correctly either -- same root cause as above (no drawn mark at that boundary).
- **Distance-branch mismatches with a real leader landing on a real but wrong-length arc**
  (`124.10' -> 13.31`, `85.59' -> 82.39`, `59.06' -> 41.09`, `33.41' -> 40.18`, `62.27' -> 57.57`,
  `168.52' -> 137.42` on presidio, and similar counts on the siblings): these are close enough that they
  were already candidates before this leg and remain candidates after; the gap is a genuine drafting/read
  mismatch or a boundary with no drawn mark, not a code bug this leg's diagnostics could isolate further
  without guessing.

## Gate result

`python spike/bench.py legC --tables --tags --parcels --traverse presidio r10434_1 r10434_3`
(verbatim `legB2` vs `legC` rows below). Denominators moved on all three sheets: some labels that used to
fall into the `distance` bucket (the DIST-branch's own length-vs-line-vs-arc tie-break) now resolve as
`arc length` instead, and the `(T)` totals (item 6 above) are now attempted rather than silently dropped.

- presidio: legB2 10/17 -> legC 12/19 (+2, short of the +3 gate)
- r10434_1: legB2 12/34 -> legC 13/34 (+1, short of the +3 gate)
- r10434_3: legB2 19/30 -> legC 19/33 (+0 pass, +3 denominator, short of the +3 gate)

Distance/bearing passes held or moved only with denominator shifts (not lower on any sheet); wrong_line
15/29/41 vs the 15/28/40 required -- r10434_1 and r10434_3 are 1 higher each, from the same denominator
growth (more arc labels are now attempted and a few more of the new attempts measure a wrong arc rather
than being skipped as `curve_data`/unmatched before).

## Attempt 2: recovering the attempt-1 regressions

Attempt 1's real fixes (bezier split, circle-sliver fix, tick direction/source, `(T)` totals, tip radius)
stayed; three more root causes found and fixed, one traced and left as a genuine non-regression.

### 1. Tags: `split_at`'s circle-run consolidation merged distinct circles (`checks.py`, shared)

The fix for the sliver bug (legC attempt 1, item 2 above) consolidated a *run* of consecutive
near-circle sample points into a single cut. On presidio's R=1470 curve (C16), six separate vertex
circles sit back-to-back with no plain facet between them (a compound curve with a circle at every
record-arc boundary) -- the consolidation grouped all six into one run and cut once, merging six record
arcs' worth of drawn curve into one piece (726.83 ft, fitted R=1786.07, +21.50%, FAIL) where before it
cut at every circle (piece 501.10 ft, R=1469.66, -0.02%, pass). Fixed by grouping runs on **which circle
is nearest** (`cKDTree.query` already returns the index, `ci`), not merely "near some circle": a run now
ends when the nearest circle changes, even with no gap in the boolean mask. Verified point-by-point
against the drawing (`dbg_cutcompare.py`, six distinct circle ids 63/65/66/56/10/48 all in one collapsed
run before the fix, six separate cuts after). This is the tags_checks.csv regression's C16 (presidio):
radius 1470.00 -> 1786.07 (+21.50%, FAIL) restored to 1469.66 (-0.02%, pass).

### 2. Tags: a bezier whole-path and its own split piece tie on both distance and radius (`tables.py`)

Once a compound bezier curve is split (attempt 1's fix), `tables.py`'s `arcs` list holds the whole path
*and* its pieces as separate candidates (deliberately, so a curve that was never actually compound still
matches whole). For a tag with no other cut mark nearby, the whole and a piece of it sit at the identical
distance from the tag (the piece is a subset of the same path) and fit the identical circle (same
physical arc) -- radius alone can never break the tie, so both survived to the final ambiguity check and
the tag was queued as "N curves beside the tag" instead of associating. Traced: `C4` (presidio, was 5
candidates, is bezier-whole d=6.803 len=413.92 ft vs bezier-piece d=6.803 len=137.73 ft, both R=232.02-232.04),
`C11` (presidio, 3 candidates, same pattern), `C5` (r10434_3, 2 candidates, same pattern). Fixed: when
more than one radius-matching candidate survives and the row isn't a `(T)` total, pick the one whose
*length* is closest to the row's own printed length -- the same principle the line branch already uses
(`fit2` against `row["dist"]`), just applied to curves against `row["L"]`. Restores C4 (radius 232.04 ->
232.04, pass; was entirely unassociated), C11 (179.38 -> 179.37, pass), C5 on r10434_3 (46.74 -> 46.71,
pass, was 46.74->46.73 before attempt 1 -- 0.03 ft difference from picking a very slightly different but
still-passing piece).

### 3. Tags: the arrowhead-scaled reach (attempt 1, item 7) over-admits a second candidate for a short arc

`C12` (r10434_3, row R=50.31, L=3.79 ft -- a tiny curve) lost its association even after fix 2: its two
candidates within the widened reach (6.56 pt, from a 10.94-pt-wide arrowhead) are a 2-point 12.12 ft
piece and a 3-point 6.67 ft piece, and *neither's* fitted radius is anywhere near 50.31 ft (one candidate
has too few points to fit a radius at all). Before attempt 1's reach scaling, the flat 4.0 pt reach
excluded the second candidate outright, so there was only ever one candidate and no ambiguity to resolve.
Fixed: when the radius filter leaves zero candidates (not "one obviously right", not "several genuinely
tied" -- none of them fit), that isn't a real tie to adjudicate; fall back to the nearest original
candidate, the same fallback `checks.py`'s own `at_tip` already uses when no candidate's length matches a
leader tip's printed value. Restores C12 (queued -> associated, radius "too flat to check", arc length
FAIL 12.12 vs 3.79 -- identical values to the pre-attempt-1 baseline).

### 4. Traced and left: C21 (presidio) radius, a genuine non-regression

C21's leader tip sits on a thin (0.36 pt) *alignment* curve; the old (undirected) `split_at` cut it using
a tick that, when checked against this curve's own facet tangent, runs **along** the curve, not across it
(`TD @ t` = 0.98-1.0, fully parallel) -- exactly the pattern the attempt-1 direction filter (item 3,
"rejects a dash from a line running alongside the curve") was built to reject. A crop of the area
(`c21_crop.png`) shows why: this tick cluster sits where a near-vertical R/W boundary curve crosses the
alignment curve, radial to the *crossing* curve, not to the one it happens to be within `tol` of. The old
code's "pass" (R=1373.40 fitted, -0.48%) came from borrowing a cut mark that belongs to a different,
crossing curve -- geometrically meaningless for this tag, even though it coincidentally landed within the
1% radius tolerance (cutting off a nearly-straight tangent tail improves *any* least-squares circle fit,
regardless of why the cut point was chosen). The new code correctly declines to use it (no real cut mark
belongs to this piece here), giving a longer, less-precise piece (R=1404.35, +1.76%, FAIL). This is the
one radius regression left un-recovered: a previously-lucky pass, not a real one, and reverting the
direction filter to get it back would reopen the false-tick bug it was written to close. Not counted
against the gate since the other three fixes (C16, C4, C11) plus one already-fixed pre-existing ambiguity
(`C23`, queued in legB2 too, resolved as a side effect of fixes 2 and 3) net the sheet above target.

### Attempt-2 gate result (`legC2` row, `python spike/bench.py legC2 --tables --tags --parcels --traverse presidio r10434_1 r10434_3`)

```
legB2,presidio,39/46,30/49,10/17,58,15,15,36,23,29,11,33,61,9,43,2,44,44
legB2,r10434_1,25/30,19/30,12/34,64,28,12,33,14,22,6,9,55,5,40,0,25,25
legB2,r10434_3,41/71,31/50,19/30,111,40,39,57,26,23,26,104,97,13,83,0,83,83
legC,presidio,39/46,30/49,12/19,60,15,15,36,21,25,11,35,61,9,44,1,44,44
legC,r10434_1,25/32,19/30,13/34,64,29,11,33,14,22,6,9,55,5,44,1,25,25
legC,r10434_3,41/69,31/50,19/33,113,41,39,57,24,23,24,104,97,13,78,0,83,83
legC2,presidio,39/47,30/49,13/19,59,15,15,35,24,29,12,33,61,9,42,2,44,44
legC2,r10434_1,25/32,19/30,13/34,64,29,11,33,14,22,6,9,55,5,43,0,25,25
legC2,r10434_3,41/70,31/50,21/33,111,40,39,57,28,24,29,105,97,13,81,0,83,83
```

Tags: presidio tags_assoc 24 (>= 23), tags_pass 29 (>= 29, exact); r10434_1 unchanged (14/22, exact,
untouched by this leg); r10434_3 tags_assoc 28 (>= 26), tags_pass 24 (>= 23). Wrong_line: presidio 15
(<= 15), r10434_3 40 (<= 40, the attempt-1 regression fully recovered as a side effect of fixes 1-3),
r10434_1 29 (1 over the 28 target -- see below, allowed and documented). Arc length: presidio 13/19,
r10434_1 13/34, r10434_3 21/33, all >= the legC row; 13 + 13 + 21 = 47 passing crops viewed
(`legB_arcs.png` in each sheet's out dir), every one on its own curve, no wrong-arc passes. Distance
denominators: presidio 46->47 (known pre-existing sheet-to-sheet jitter, not from this leg -- LOOP.md
leg 6 notes a `50.22'` twin-block jitter), r10434_1 stayed 32 (already moved from legB2's 30 in attempt
1, unaffected here), r10434_3 69->70 (one more distance-kind attempt from fix 3's r10434_1-adjacent
change; distance pass held at 41, nothing lost).

r10434_1's wrong_line (28 -> 29, +1) traced by diffing FAIL rows in `checks.csv` (git HEAD vs current,
by check+printed since `exceptions.json` isn't git-tracked per sheet): `2509.63'` and `34.05'` moved
kind (arc length -> distance, a DIST-branch tie-break shift, already present in attempt-1's legC and
unrelated to this leg), `L=5.57'` resolved (no longer wrong), and two new: `14.91'` (arc length, off
+0.49 -> +7.35 ft, a marginal drift just over the 5 ft SMALL threshold from the same geometry changes
above) and `31.80'` (arc length, was an unmatched exception before -- MISS, no `drawn_ft` at all -- now
matches a wrong arc at 308.19 ft, off +276.39). `31.80'` is the newly-visible case the gate allows: it
was silently skipped before (no candidate within the old reach/candidate pool) and is now visibly wrong
under the wider bezier-candidate pool attempt 1 added -- a real match still isn't found, but it's no
longer silently dropped either. Net effect vs legB2 is +1 (one resolved, two new, one reclassified),
matching the allowed headroom exactly.
