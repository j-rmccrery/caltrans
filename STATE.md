# State and resume point

Branch `caltrans-spike` on `gitlab.com/jrmccrery/dredge-code` (orphan branch; never merge into `main`).
Plan: `ROADMAP.md`. Layers for the screen: `spike/out/QGIS_LAYERS.md`. Run everything: `python spike/demo.py --fast`.

## Loop 15 (2026-09-27): a fail needs proof, a no-line cause found, a third gold set

- **Arc fails need proof.** An arc fail stands only when its association is proven: a lone candidate in the leader's reach, a clear touch (<= 1 pt, others > 2 pt), or a tag whose radius and placement hold up. Otherwise it is queued as "association unproven" (`checks.at_tip`, `tables.py`).
  - R-10434.3: fails 44 -> 27, gold wrong-line 24 -> 7, all 19 real kept.
  - R-10434.1: 20 -> 12.
  - Presidio: unchanged.
- **The "no line found beside label" cause.** It was nearest_line's box-rotation prefilter: stacked blocks read 10-15 deg off their line. A candidate that agrees with the printed bearing is now admitted, and may only pass. +12 label passes, each crop viewed; two wrong-line passes in the first attempt were removed.
- **Gold set on R-10434.1** (`spike/gold/r10434_1_assoc.json`): passes 83/0/0, fails 7 real / 9 wrong / 4 unsure.
- **attribution.md regenerated:** `a-runtotal` 0/0/0; it was stale, not an incomplete fix.
- Bench row `loop15-final` is the baseline: coverage 102/171, 62/171, 121/248; gold wrong-pass 0 on all three keyed sheets. Demo 161 s cold.
- Commits 3f632a5, 56facb5, 0b99c00, e9a5f46. Plan and status in `spike/LOOP.md`.

## Next (logged 2026-09-27 after loop 15; plan and status in `spike/LOOP.md`)

A scan-detector trial is running separately in `spike/det/` (untracked, not part of any loop). Leave it alone unless JR says otherwise.

1. Demo prep: slides, Q&A sheet, recorded fallback; two rehearsals; freeze 10-03.
2. **Wrong-line fails still standing:** 7 on R-10434.3 (distance labels 147.28/150.95/152.49/42.44/87.86, arc 324.13', tag C33), 6 on R-10434.1, 2 on Presidio.
   - A lone candidate the leader does not touch still counts as proven (324.13' lands 4.0 pt off).
   - C33 lies on its tagged curve, with only a partial extent measured (607.70 of 1049.90). Re-key it in gold, or join its pieces.
3. **Coverage:** 21 of 32 cropped no-line labels have no reachable candidate or are compound line+curve totals (`spike/out/leg2_crops/classes.md`).
4. **Key the 12 new passes into gold** (Presidio 4, R-10434.1 2, R-10434.3 6; they show as unkeyed passes in `loop15-final`), so gold wrong-pass counts cover them.
5. **Small fixes:**
   - Rewrite `coverage_attrib.py`'s dead `a-runtotal` wording.
   - Re-run `coverage_attrib.py` whenever `checks.py`/`tables.py` change.
   - Delete loop 13's orphaned `g_*.png` crops.
6. Carried from the loop 13 Next items 3-4 (`tags.py` time; loop 12 items 2-4).

## Loop 14 (2026-09-26 17:30): fails are claims about the record

A result far beyond any keyed real disagreement is queued as "wrong line likely" (checks.wrong_line_likely; cuts in commit
ba144e9); tags resolved by SHX/record and bare (T) totals may only add passes. Fails Presidio 26 -> 16 (gold 13 real / 2 wrong
/ 1 unkeyed), R-10434.1 31 -> 21, R-10434.3 72 -> 44 (19 / 24 / 1). Passes identical. Bench row `legI` is the baseline;
demo 160 s cold. Cuts tuned on the two keyed sheets; wrong-line arc fails on R-10434.3 mostly remain (no safe cut).
Status page version 14 separates pass rate, pass precision, fail quality and coverage (JR read coverage as a drop).

## Next as of loop 13, kept for the record

### Next (logged 2026-09-26 15:15 after loop 13; plan and status in `spike/LOOP.md`)

**Loop 13 (precision on a second sheet, then coverage).** Bench row `legH2` (second of the two) is the baseline.
- Gold set on R-10434.3 (`gold_assoc.py --sheet r10434_3`): 152/0/0 after this loop; Presidio 134/0/1 (L20 unsure).
  No wrong-line pass anywhere keyed; the one the agent reported (label 95) was on the right curve.
- Coverage attribution (`coverage_attrib.py`, `out_coverage/attribution.md`): every parsed token has a named bucket.
  Bench `coverage` is now honest (drawing-label passes incl. arcs over addressable labels): Presidio 98/170,
  R-10434.1 60/168, R-10434.3 115/246.
- Leg H: partly read tags resolved from SHX text or by the record (exactly one unclaimed row passes); bare (T) totals
  checked, with the printed bearing (own block or stacked beside it) required on the measured run. +16 passes, 0 lost.
- demo --fast 177 s cold under load: headroom is thin; `tags.py` (51 s, glyph sweeps) is the next cut.

Do this, in order:

1. Demo prep: slides, Q&A sheet, recorded fallback; two rehearsals; freeze 10-03.
2. Coverage, next causes (attribution.md): f-queued drawing labels (33/51/58: no line, too short, matchline);
   several labels claiming one line (R-10434.3 labels 40/41/114/130); station ticks cut centrelines into pieces
   (Presidio L21 distance 1529.50 vs a 74 ft piece); 42 partly read tags still queued on R-10434.3.
3. `tags.py` time (cache like build_pool) to restore demo headroom.
4. Carried from loop 12 Next items 2-4.

## Next as of loop 12, kept for the record

### Next (logged 2026-09-26 13:00 after loop 12, the review legs; plan and status in `spike/LOOP.md`)

**Loop 12 (review gaps 1-4, five sonnet legs, four in parallel).** Pushed `caltrans-spike` to 2b3b4a4 first; loop 12 commits
1841651..66618a6 are local. Bench row `legE` is the baseline now.
- **Perf:** `demo.py --fast` 245 s -> 160 s cold (checks 64 -> 28 s, tables 66 -> 4 s): vectorised `dashes.estimate_reach`,
  disk cache of `checks.build_pool` keyed on inputs and every spike/*.py. Outputs byte-identical.
- **Gold set:** `spike/gold/presidio_assoc.json`, all 155 checked labels on Presidio keyed by crop. Pass precision 132/132
  (no luck passes on this sheet); fails 9 wrong-line, 13 real, 1 unsure. Bench column `gold` = right/wrong/unkeyed from the
  current run; column `coverage` = distance+bearing passes over parsed tokens (Presidio 82/307).
- **Record self-checks** (`record_checks.py`, in demo): alignment coordinate tables land on the fit at median 0.02-0.07 ft
  (independent of the callouts; not better control); L=R*Delta holds on all 68 curve rows; found a drafting error on the
  record (R-10434.1 row L prints northing 2,21,919.67) and a table-reader bug (R-10434.3 L34-L45 lost DISTANCE; fixed in
  `read_shx.build_tables`, tags 26 -> 31 passes). No chord columns printed; tangency check found no simple joins.
- **Matchline** (`matchline.py`): proven same-line pairs across sheets agree to <= 0.17 ft; R-10741.2/.3 12 shared labels,
  median 0.19 ft. R-10741.1/.2 share no line. The ROADMAP Q&A claim is now measured.
- **Ground check** (`lidar/ground_check.py`): none of the six sheets draws buildings, walls or pavement edges; deck vs drawn
  corridor is a width, not a tie. The 0.668 m epoch shift cannot be tested from these sheets.
- Noise: `EPOCH 1991.35` no longer checked as a distance.

Do this, in order:

1. Demo prep: slides, Q&A sheet (add matchline and record-error findings), recorded fallback; two rehearsals; freeze 10-03.
2. Gold set on a second sheet (R-10434.3, busiest) before quoting precision beyond Presidio.
3. Epoch shift on the ground needs a tie the LiDAR sees: NGS marks on hard surface, or a sheet that draws structures.
4. Carried: gap-tile highway surface; C21 scoped fix; scan text-line detection (SAM unconfirmed); north row segmentation;
   R-71.70 1.29 deg; exceptions_page.crop hides the measured line when it is > 190 pt from the label (7 Presidio crops).

## Next as of loop 11 (2026-09-26 04:40), kept for the record

### Next (logged 2026-09-26 04:40 after loop 11; plan and status in `spike/LOOP.md`)

**Session close 2026-09-26 04:50.** Loops 3-11 committed on `caltrans-spike` (cd8b498..0fd9117, 66 commits), nothing pushed.
Status page version 13; field guide `docs/record-twin-how-it-works.html`. Memory index for the session:
`caltrans-session-2026-09-23-to-26`.

**Loop 11 (the road as one surface).** Purple in the renders was the vendor's class-17 deck only. Now: `extract.py --audit`
prints each tile's class histogram (ground is class 2 everywhere; class 17 present on all three tiles); deck grows from
class-17 seeds into dark, flat cells >= 2 m above the ground DTM; the 3DEP gap tile's pavement (190 fragments under the
400 m2 floor) comes through a wider closing; `lidar/surface.py` dissolves pavement + deck inside the union of the R/W
faces per tile into one highway surface (structure / at grade), drawn in `six.qgz` above the per-kind layers; tunnel
easement faces are styled record-only. Gains are honest and small (deck +45 / +91 m2 inside R/W; gap pavement 2,176 m2);
the continuity in the render comes from the union. Pavement outside the R/W unchanged (Presidio 9,606 m2).

**Regression to fix first: `demo.py --fast` is 245 s** (checks 64 s, tags 51 s, tables 66 s), over the 180 s gate; loops
8-9 added curve stitching, dash-dot trains and window searches. Profile those three and restore < 180 s without moving
`loop9-final`.

Note (JR, 2026-09-25 16:50): pull in the new SAM information. Which SAM is unconfirmed.

Do this, in order:

1. **demo.py --fast under 180 s** (above).
2. **Highway surface for the gap tile** (`surface.py` ran for south and north only) and a per-tile mosaic of features.
3. **C21 and the point-of-tangency class, scoped** (loop 10: >= 100 ft radius windows; PT cuts inside a failing tag's parent).
4. **Scan text-line detection**; **north row segmentation**; **south bearings/arcs left**; **R-71.70's 1.29 deg**.
5. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze by 10-03.

## Next as of loop 10 (2026-09-26 03:10), kept for the record

### Next (logged 2026-09-26 03:10 after loop 10; plan and status in `spike/LOOP.md`)

**Loop 10 (C21 traced by eye; one leg, two attempts, no code shipped).** `spike/c21_trace.py` found C21 whole on the
sheet: a tangent, then five pieces of one thin line across the C9/C10 fillet (255.91 + 193.93 + 86.86 + 278.14 + 62.04 =
876.88) ending where three straight lines start along the curve's tangent at [1931, 660], a point of tangency. Two
defects named and measured: the join across the fillet compares a blended whole-piece radius (production has no cut
inside p104, so it fits R 1418.75 against p97/1's 1382), and `split_at` has no point-of-tangency cut. Both fixes were
tried and rejected on the gate: 40 ft end-fit windows are numerically unstable at 2-decimal precision (R swings 1535 ->
1382 between 40 ft and the whole tail; ~100 ft is the floor), and a sheet-wide PT cut fragments other curves (R-10434.3
loses C33 and C25 radius passes, R-10741.1 a distance pass). Diff kept at `spike/out/loop10_legA.patch`. `loop9-final`
stands as the baseline.

Note (JR, 2026-09-25 16:50): pull in the new SAM information. Which SAM is unconfirmed.

Do this, in order:

1. **C21 (and the PT class), scoped**: radius fits on windows of at least 100 ft; the PT cut applied only inside the
   parent of a tag whose own window search failed, never sheet-wide; then re-run the trace script to confirm the five
   pieces sum. Gate as loop 10's.
2. **Scan text-line detection on the binarised page**; if "SAM" is Segment Anything, it is a candidate detector.
3. **Row segmentation of multi-line blocks on 2012-era sheets**: the north reads.
4. **South bearings and arcs, what is left**: bearings 2/2/1 fails; inline arcs 3/12/13.
5. **R-71.70's 1.29 deg**; **mosaic south + gap**; **1950s scans on the north tile**.
6. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze by 10-03.

## Next as of loop 9 (2026-09-25 20:00), kept for the record

### Next (logged 2026-09-25 20:00 after loop 9; plan and status in `spike/LOOP.md`)

**Loop 9 (stitch drawn curves, dash-dot trains, consecutive rows; one leg, two attempts).** Curve paths whose ends meet
are one parent now (`checks.chain_curve_paths`, 1 pt / 3 deg / 2 %); dash-dot patterns chain into trains
(`dashes.dashdot_trains`) but their pieces are kept out of the no-leader proximity search (by proximity they gave six
fake fails on R-10434.3, all the alignment centreline); consecutive table rows around a failing tag are checked as a run
against the drawn run between the marks that exist, untagged rows included (`tables.row_run`): Presidio C15 passes as a
run of C15 + C16 + C18. Presidio row checks 33 / 9 -> 34 / 10 (C20 now reaches a check and fails honestly); nothing else
moved on any sheet. C21 stays a real fail: its stitched parent is 706.79 ft of the record's 876.88, and the 10.65 pt gap
beyond it holds a different curve (tangent 8.4 deg off, radius 9.3 % off). Bench row `loop9-final`.

Note (JR, 2026-09-25 16:50): pull in the new SAM information. Which SAM is unconfirmed.

Do this, in order:

1. **Scan text-line detection on the binarised page** (replace the OCR detector's boxes); if "SAM" is Segment Anything,
   it is a candidate detector; gate: the 32 keyed boxes landing on their text (24 today).
2. **Row segmentation of multi-line blocks on 2012-era sheets**: the north reads.
3. **C21 and C20 class**: the record cites a long thin curve the drawing carries in pieces with other curves between
   them, or a centreline the leader crosses. Trace by eye where the record's 876.88 ft actually runs on the sheet before
   writing any rule; the stitched parent and the dash-dot trains are in place to measure against.
4. **South bearings and arcs, what is left**: bearings 2/2/1 fails; inline arcs 3/12/13.
5. **R-71.70's 1.29 deg**; **mosaic south + gap**; **1950s scans on the north tile** through their packages.
6. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze by 10-03.

## Next as of loop 8 (2026-09-25 17:00), kept for the record

### Next (logged 2026-09-25 17:00 after loop 8; plan and status in `spike/LOOP.md`)

**Loop 8 (table tags by parent curve, one leg).** `tables.py` now takes curve arcs from `checks.build_pool` (every piece
carries its parent curve and sequence) and a curve tag tries its own piece, then a contiguous window of its own curve
(`checks.parent_window`, shared with the inline L= path), then a same-parent run against the sum; a leader tip on a
radial tick resolves to the curve piece the tick meets. Presidio row checks 31 pass / 12 fail -> 33 / 9 (C16 as a run of
its own two pieces, C19's arc; C19's false radius fail gone; C21 now measured on the right piece and still a real fail).
No other column moved on any sheet; no same-parent partner exists for any remaining curve fail on .1/.3. C15 on
Presidio cannot pass alone: the drawn run is C15 + C16 + C18 (C18 untagged on this sheet) = 573.93 (T), which passes as
the total. Bench row `loop8-final`.

Note (JR, 2026-09-25 16:50): pull in the new SAM information. Which SAM is unconfirmed (see the loop 7 Next below).

Do this, in order:

1. **Scan text-line detection on the binarised page** (replace the OCR detector's boxes); if "SAM" is Segment Anything,
   it is a candidate detector here; gate: the 32 keyed boxes landing on their text (24 today).
2. **Row segmentation of multi-line blocks on 2012-era sheets**: the north reads.
3. **Curve tags, what is left**: C21-class (leader on the long curve, record is a short sub-arc: 449.84 vs 876.88),
   C20-class (record cites a dash-dot boundary no pool models), C15-class (a row whose piece includes an untagged
   neighbour: check consecutive table rows as a run even when a row has no tag on the drawing).
4. **South bearings and arcs, what is left**: bearings 2/2/1 fails; inline arcs 3/12/13.
5. **R-71.70's 1.29 deg**; **mosaic south + gap**; **1950s scans on the north tile** through their packages.
6. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze by 10-03.

## Next as of loop 7 (2026-09-25 09:25), kept for the record

### Next (logged 2026-09-25 09:25 after loop 7; plan and status in `spike/LOOP.md`)

**Loop 7 (the scan by its own alphabet, R-65.2).** `spike/scan_alphabet.py`: boxes levelled and binarised, glyphs
segmented (fused pairs split at projection valleys), clustered by stroke-direction zoning (579 cap clusters, 98.6 %
purity on the keyed glyphs), clusters named by gapped alignment to the boxes RapidOCR and qwen2.5vl agree on, by
structure, and by the vision model shown each cluster's contact strip once. On the keyed 32: template alone 4 right /
2 wrong / 26 queued; gated by consensus 7 / 0 / 25; the old two-reader consensus 16 / 1 / 15; union 18 / 32. It is a
third reader with zero wrong, not a replacement. What bounds it: 552 of 730 clusters are too rare or too fused to
name, and 8 of the 32 keyed boxes are detector boxes on the wrong text before any reader runs. Box 15 reads R=584 by
all three readers against a keyed 1015.13'; re-key it.

Six-sheet bench untouched by this loop: `loop6-final` stands (presidio 41/49 41/43 16/19 wl 12; .1 26/37 21/23 12/24
wl 21; .3 42/59 41/42 26/39 wl 27; R-10741.1 14/18 13/13 1/2 wl 3; .2 20/20 18/18 0/1 wl 0; .3 17/17 13/13 0/1 wl 1).

**Note (JR, 2026-09-25 16:50): pull in the new SAM information.** Not yet specified which SAM; if it is Meta's Segment
Anything, the fit is scan text-line detection (item 1 below): prompt-free mask proposals on the binarised page as the box
detector, scored on the 32 keyed boxes landing on their text (24 today). Ask JR before spending a leg on it.

Do this, in order:

1. **Scan text-line detection on the binarised page** (replace the OCR detector's boxes): horizontal and rotated
   runs of glyph components, one box per lettered line, gated on the 32 keyed boxes landing on their text (today 24).
   Then the alphabet reader and the two generic readers vote per box.
2. **Row segmentation of multi-line blocks on 2012-era sheets** (`block_rows` / `merge_pieces`): the north reads.
3. **South bearings and arcs, what is left**: bearings 2/2/1 fails; arcs 3/12/13 (`leg6A_missing.md` classes b, c).
4. **R-71.70's 1.29 deg**; **mosaic south + gap**; **1950s scans on the north tile** through their packages.
5. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze by 10-03.

## Next as of loop 6 (2026-09-24 23:30), kept for the record

### Next (logged 2026-09-24 23:30 after loop 6; plan and status in `spike/LOOP.md`)

**Loop 6 (accuracy items 1-6).** Bench row `loop6-final`: presidio 41/49 41/43 16/19 wl 12; .1 26/37 21/23 12/24 wl 21;
.3 42/59 41/42 26/39 wl 27; R-10741.1 14/18 13/13 1/2 wl 3; .2 20/20 18/18 0/1 wl 0; .3 17/17 13/13 0/1 wl 1.
What moved: lone `L=` labels sum contiguous pieces of one parent curve (+6 arcs; 573.93 (T) is back); a bearing
tolerance that scales with piece length, capped at 30 arcmin, with pieces under 10 pt queued as too short (+10
bearings, 5 luck passes retired); chords beside curves by geometry (+4); parallel neighbours by printed bearing (+1);
leader landing piece at busy vertices (+1); not-to-scale detail bubbles found by their dashed outline (R-10434.1's
four, R-10741.2's one; four coincidence passes retired). Bearing denominators are now checkable pieces only.
Findings that close items: the north seed font is not the read limit (LibreCAD simplex/romans digits are byte-
identical to the Hershey seed; the unread blocks are prose paragraphs, a row-segmentation limit; code under
`spike/out/leg6E_stash/`); R-10434.1's closed chain of loop 2 was a transient state, never committed, and no real
loop closes there at any tolerance (`traverse.py` now drops arc edges with L < chord and snaps loose ends).

Do this, in order:

1. **Row segmentation of multi-line blocks on 2012-era sheets** (`block_rows` / `merge_pieces` in read_glyphs.py):
   R-10741.2's unread blocks are GRANTOR NOTES and TITLE CODES paragraphs. Reads first, then the selector rule
   (OCR vs glyph) re-measured.
2. **South bearings, what is left**: 2/2/1 fails on .2/.1/.3 plus the too-short queue (6/8/11). The queue is the
   drawing's own limit; the fails need crops.
3. **Arcs, what is left**: presidio 3 fails, .1 12 (matchline cuts, details), .3 13. `leg6A_missing.md` classes (c) and (b).
4. **R-71.70's 1.29 deg** (loop 4): crop both NGS marks against the two-point fit; basis-of-bearings note.
5. **Mosaic south + gap**; the 2024 CA_SanFrancisco_B23 CRS.
6. **1950s scans on the north tile** (R-71.11/.20/.28, R-92.8/.9) through their packages like R-65.
7. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze.

## Next as of loop 5 (2026-09-24 19:10), kept for the record

### Next (logged 2026-09-24 19:10 after loop 5; plan and status in `spike/LOOP.md`)

**Loop 5 (south bearings, then arcs).** One root cause carried the bearings: a chained line kept its seed segment's
direction and handed it to every cut piece, so labels along a multi-piece record line were compared with one
arbitrary heading (17 of 36 south bearing fails). Each piece now takes the least-squares direction of its own
points: south bearings 30/49 18/31 32/51 -> 34/49 20/31 37/52, nothing lost. Arcs: the loop 2 attribution is
stale; the 65 south arc misses are bare distances grabbed by the length-blind arc fallback (32), standalone L= with
no drawn arc in reach (25), and the compound-curve boundary class (8). The fallback now needs the label along a
curve or a leader on one (7 fake arc fails gone), fillet L= is matched to the piece whose fitted radius equals its
R= (measured, none passing), run-sums are shared with the table path and fire 0 times. Bench row `loop5-final`:
presidio 40/48 34/49 13/17 wl 14; .1 26/38 20/31 14/30 wl 27; .3 42/59 37/52 23/36 wl 31; R-10741.1 14/18 12/13
1/2 wl 3; .2 20/22 20/20 0/1 wl 2; .3 17/17 13/13 0/1 wl 1.

Do this, in order:

1. **Arcs, the 25 standalone L= with no drawn arc in reach** (`spike/out/leg5B_arcs.md`): crop 12, say whether the
   arc is drawn at all (a fillet cut into slivers by `split_at`, a curve on a layer the pool skips, a matchline
   cut) and fix the biggest.
2. **South bearings, next cause**: leader to another line at a busy vertex (7 of 36); the leader's arrowhead
   should win over proximity, as in `tables.py`.
3. **R-71.70's 1.29 deg** (loop 4): crop both NGS marks against the two-point fit; read the basis-of-bearings note.
4. **Not-to-scale insets on OCR sheets**: detect the inset by its dashed circle.
5. **R-10434.1 traverse** closed 1 -> 0 in loop 2 leg C; trace the moved edge.
6. **Mosaic south + gap**; pin down the 2024 CA_SanFrancisco_B23 CRS.
7. **1950s scans on the north tile** (R-71.11/.20/.28, R-92.8/.9) through their packages like R-65.
8. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze.

## Next as of loop 4 (2026-09-23 23:45), kept for the record

### Next (logged 2026-09-23 23:45 after loop 4; plan and status in `spike/LOOP.md`)

**Coverage after loop 4.** Three LiDAR tiles (`spike/tiles.py`): south/Presidio 2025, north/Marin 2025, gap (USGS 3DEP
2018, `Sample Data/LiDAR-Point-cloud/gap/`, ~9.7 pts/m2) for R-10741.1 and R-10434.3's east edge; all six baseline
sheets have ground under them. Nine bench sheets: the six plus R-71.71 (grid lines, rms 0.01 ft), R-10258.1
(callouts + grid, package 0.09 ft) and R-71.70 (unverified, below). Bench row `loop4-final`:
presidio 39/47 30/49 13/19 wl 15; .1 26/37 18/31 14/32 wl 29; .3 42/58 32/51 23/39 wl 33; R-10741.1 14/19 12/13 1/1
wl 3; .2 20/22 20/20 0/0 wl 2; .3 17/17 12/13 0/1 wl 1; R-71.71 14/19 16/21 1/4 wl 7; R-10258.1 12/52 17/28 2/16 wl 35.
What moved and why: north dashes are 8.6-8.9 pt (the 8 pt cap chained tick marks instead), the north drafter's
`A=` delta and OCR-joined curve blocks now feed L=R*delta, R-10434.3's line table was masked short by an unrelated
curve table at the same x (12 cells checked as labels), comma-grouped distances (`18,966.64'`) now parse.

**R-71.70 (CCS83 zone 2, 1"=~2900', NGS PIDs AE9850 RYER and AE9865 STAR RESET):** `georef.ngs_points` fetches the
published positions (cached `spike/lidar/ngs_pids.json`), finds both brass-disk marks by leader, and the two-point
fit gives scale 40.16 ft/pt, rotation 88.73; the sheet's own bearings say 90.02 (6/9 within 0.16 deg). 1.29 deg over
the 31,700 ft baseline is ~18 pt on one mark or a non-grid basis of bearings. Crop both marks against the fit before
trusting either. The mechanism is STATE gap 5, built; this sheet is its first test and does not verify yet.

Do this, in order:

1. **R-71.70's 1.29 deg**: render both PID marks with the two-point fit's reprojection of each other; read the
   sheet's basis-of-bearings note; decide which is off. Then the NGS path is a second independent check on every
   sheet that prints a PID.
2. **Not-to-scale insets on OCR sheets**: the mask is built (`checks.py`, text-based) but R-10741.2's caption reads
   as CJK glyphs; detect the inset by its dashed circle instead, or fix the OCR crop levelling for small captions.
3. **Chords and record residuals**: the north dashed line measures 175.04 vs 176.73 printed (1.7 ft), an honest
   exception; check whether the dashes stop short of the vertex circles by a cap and, if so, extend to the mark.
4. **Arc lengths, what is left** (`spike/out/legC_misses.md`): run-sums against a neighbour tag.
5. **R-10434.1 traverse** closed 1 -> 0 in loop 2 leg C; trace the moved edge.
6. **Mosaic south + gap** so R-10434.3 keeps the 2025 tile where it has it; CA_SanFrancisco_B23 (2024) covers both
   gap boxes but its LAZ carries no CRS, pin it down.
7. **1950s scans on the north tile** (R-71.11/.20/.28, R-92.8/.9) through their packages like R-65.
8. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze.

## Next as of loop 3 (2026-09-23 20:05), kept for the record

### Next (logged 2026-09-23 20:05 after loop 3; loop 3 plan and status in `spike/LOOP.md`)

**The six-sheet baseline exists and reproduces.** South R-10434.1/.2/.3 (Presidio tile) and north R-10741.1/.2/.3
(Marin tile, 2017, drafter CHaldenwang, no SHX annotations, no tables, read by OCR) all georeference from their
own callouts and sit on their tiles; Caltrans' packages check all six (max 0.4 ft on the north set) and place none.
`python spike/demo.py --fast --six` (640 s) runs the other five after Presidio and writes `spike/out/six.qgz`
(two tile groups, 27 + 21 layers, renders `six_render_south.png` / `six_render_north.png`). Bench over six:
`python spike/bench.py <label> --tables --tags --parcels --traverse presidio r10434_1 r10434_3 r10741_1 r10741_2 r10741_3`;
row `loop3-final` (equal to `six`, measured twice): presidio 39/47 30/49 13/19 wl 15 tags 24; .1 26/37 18/31 14/33
wl 30; .3 42/70 32/51 23/39 wl 45; R-10741.1 13/16 12/12 1/4 wl 6; .2 20/22 19/19 0/1 wl 3 (leg 5; was 0/3 wl 5); .3 17/17 12/13 0/1 wl 1 (was 0/2 wl 2).
The .1/.3 rows moved from loop 2's (25/32, 41/70): those were measured on stale sibling state. Every future leg is
gated on this row; a leg that moves a north row must say whether reads or association moved it.

**Two state bugs that made earlier baselines drift, fixed in loop 3 leg 3:** (1) `tables.json` was written last by
`alphabet.py` (glyph) in the demo but by `read_shx.py --tables` (annotations) in the bench, and checks mask table
cells by it, so table cells leaked into the distance pool (R-10434.3 41/70 vs 42/121). The demo now runs the
annotation rebuild after `alphabet.py` and the bench runs it before checks. (2) `georef.READS` took any
`tables.json` over 20 bytes as a validated alphabet (`{"_regions": []}` is 22), so sheets without tables read by
glyph or by OCR depending on the last writer; now validated = at least one table row (north = OCR, per the rule).
Presidio's tag count 22 vs 24 was the same thing: 24 is the annotation-tables state.

**LiDAR lies under four of the six.** South tile: R-10434.1/.2 (the "7 sheets" claim below was wrong for .3, whose
northing starts 5 m past the tile edge). North tile: R-10741.3 99 %, .2 60 %, .1 0.3 %. The bridge and the strait
between the tiles need USGS 3DEP.

Do this, in order:

1. **Chord checks.** On R-10741.2 the labels with no drawn line are chord citations: a bearing+distance pair
   beside a curve (`S16°20'26"E 176.73'` with `(176.77')` under it, arc 176.77 vs chord 176.73). Check them as the
   chord between the curve's ends. Loop 3 leg 5 did the rest of the north attribution (`spike/out/r_10741_002_2017-02-10/leg5_misses.md`):
   the `A=` delta prefix and OCR-joined curve blocks are read now (curve L=R*delta 2/2 on .2); a not-to-scale detail
   inset holds two labels no check can ever pass (mask NTS insets); `660.20'` has its degree sign OCR-read as a quote.
2. **Arc lengths, what is left** (`spike/out/legC_misses.md`): run-sums against a neighbour tag.
3. **R-10434.1 traverse** closed 1 -> 0 in loop 2 leg C; trace the moved edge.
4. **1950s scans on the north tile** (D4 index: R-71.11/.20/.28, R-92.8/.9) through their packages like R-65.
5. **Other Civil 3D 2016+ sheets** (R-71.70, R-71.71, R-10258) through `read_shx.py`; the 2012-era sheets need the
   real SHX fonts as the glyph seed, not Hershey (R-10741 reads about half by glyph, and OCR is what the rule picks).
6. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze.

Not next: layer taxonomy as an association filter (measured: no gain); more drawn-geometry work on 61985-1..4.

## Next as of loop 2 (2026-09-23 14:00), kept for the record

### Next (logged 2026-09-23 14:00 after loop 2; loop 1 report in `spike/out/loop_report.md`, loop 2 in `spike/LOOP.md`)

Presidio now (bench `loop2-final`): distance 39/47, 25/32, 41/70 on R-10434.2/.1/.3; bearing 30/49, 19/30, 31/50;
arc length 13/19, 13/34, 21/33 (were 4/11, 4/26, 7/18); wrong-line 15/29/40; tags associated 24/14/28; the bench is
deterministic (twin annotations folded, leg A). `demo.py --fast` 130 s, 21 steps ok.

**Tunnel easements 61985-1..4 (loop 2 leg B, measured twice): they do not close as separate figures on this sheet.**
The easement layer `rw_EASE_EXIST_align` draws one strip: a dashed line under the R/W line (train 0) and one
parallel to it ~17-25 pt south (trains 2+6+1+5), closed at the west end near ⑤/C3 and at C11 (`spike/dashes.py`,
`spike/out/legB_61985.png`). No stroke on the sheet divides the strip into four; the ovals' leaders go to R/W
vertex circles (61985-1 -> C7) and the R=/Δ=/L= blocks' arcs sit on the R/W line itself. Envelope 48,410 sq ft vs
the table's 70,690 (-31.5 %): the TCEs (61985-2/-3) overlap the tunnel easements rather than tile the strip.
The demo says so: the envelope is measured, the four stay queued, and the deed documents carry their outlines.
Do not spend more time on drawn geometry for these; a record walk needs their legal descriptions.

Do this, in order:

1. **Arc lengths, what is left** (`spike/out/legC_misses.md`): compound curves with no drawn mark at the record
   boundary (C15/C16 class, `L=171.66'`, C19/C21/C22) need a run-sum against an adjacent tag; standalone `L=`
   blocks have none. Four `(T)` totals on Presidio now reach the check and fail for the same reason.
2. **R-10434.1 traverse** lost its one closed chain in leg C (chains 44 -> 43, closed 1 -> 0). Trace which edge
   moved; the arc split changed an edge's endpoints.
3. **R-10434.1 wrong-line +1**: `31.80'` measures 308 ft under the wider bezier pool; `14.91'` drifted to +7.35 ft.
4. **Other Civil 3D 2016+ sheets** (R-71.70, R-71.71, R-10258) through `read_shx.py`; then the 2012-era sheets
   need the real SHX fonts as the glyph seed, not Hershey.
5. Slides, Q&A sheet, recorded fallback (roadmap day 11); two rehearsals; freeze.
6. Scans: unchanged (gap 1). Classify the 48 by lettering first; measure Leroy and CAD-plot classes.

Not next: layer taxonomy as an association filter (measured: no gain; stash `loop-leg-2`); more drawn-geometry
work on 61985-1..4 (above).

## 2026-09-23 16:00: new data on disk (North tile, R-10741.1..3)

`Sample Data/LiDAR-Point-cloud/north/` (points.laz 28.8 M pts, output.tin.tif; EPSG:6339; 545206-545842 E,
4186988-4188074 N; Marin approach of the Golden Gate Bridge). The "South" download was the existing Presidio tile
(identical). `Sample Data/d4/r_10741_00[123]_2017-02-10.pdf` (Route 101 MRN, Sausalito Rancho / Fort Baker,
drafter CHaldenwang) with their Caltrans packages in `d4/pkg/` (CCS83 zone 3), plus the R-10434.1 package.
The D4 index puts R-10741.1..3 and the 1950s scans R-71.11/.20/.28, R-92.8/.9 on the North tile.

Run as-is (`spike/out/r_10741_00*/`, log `spike/out/r10741_run.log`): Civil 3D 2012-style export, no SHX
annotations, no tables to validate an alphabet; glyph reader reads about half (R-10741.2: 20 bearings, 15
distances, 6 of 8 coordinate tokens, 195 blocks with `?`). Record frame: scale 1.3888 ft/pt, rotation from 19/19
bearings, .2 and .3 agree to 0.001 deg. **Refused: 0 coordinate callouts paired** -- the two-row N/E callouts read
as separate blocks and the leader trace does not fire for this drafter. No offset, no placement.

Next for this set (one leg): pair the two-row N/E callouts and trace their leaders on this drafter's sheets (4 on
.2) for the offset; check against the package; parametrise the LiDAR scripts by tile (`LAZ`/`DEM` hard-coded to
the Presidio paths in `lidar/extract.py`, `q1..q5`, `export_rasters.py`, `encroach.py`); run extract, overlay and
the QGIS project for the north set. Status report page: `docs/record-twin-status-2026-09-23.html`
(published at https://claude.ai/artifact/7rH9qavBuXxYtB3HUGb1Cz).

## 2026-09-23: CAD structure in the PDFs, and the association bench

**The PDFs carry CAD structure the pipeline never read.** 13 of 17 vector sheets have optional content
groups = CAD layers, and every path carries its layer (`page.get_drawings()[i]["layer"]`). Civil 3D
sheets (11): `RW-PARCEL-SEG-*`, `RW-ALGN-LNWK-*`, `rw_EASE_*` are the lines labels describe (Presidio:
~750 of 15,832 paths); `RW-ALGN-LBL-*` labels; `*-LBL-*-Line` leaders; `SU-FIG-PNT-MARK` point marks;
`RW-TBL` / `RW-SHEET-TBL` tables; `110_Sheet_Format`, `border*`, `SHEET*` furniture; `_Wipeout_Areas`
text masks (Presidio lines run through 69 of the 90 wipeouts they touch: not broken for text).
MicroStation sheets (4): named levels on R-102.1aa (`31 RW (exist)`), V8 numbered levels on R-105.14
(`Level 31`), R-17x.1 flattened. Caltrans CADD Users Manual Appendix A10 gives the named-level grammar
(152 `rw_*` names). Six Civil 3D 2016+ sheets (R-10434.1/.2/.3, R-71.70, R-71.71, R-10258) carry every
stroked label's text as `AutoCAD SHX Text` annotations (`page.annots()`, content + rect; `%%D` = degree):
Presidio 878, all 227 keyed table values verbatim. `spike/annot_reads.py` builds a block file from them;
with `READS=<file>` (new env override in `georef.py`) Presidio georeferences 18/19, RMS 0.04 ft, checks
equal the glyph read. On refused R-71.70 the annotations read 13 bearings where the glyph reader read 4.

**Association bench** (`spike/bench.py`, rows in `spike/out/bench.csv`; toggles `ASSOC=bearing,span,layers`
in `checks.py`, `ASSOC=tagrow` in `tables.py`, all off by default). Four ideas measured on Presidio,
R-10434.3, R-105.14, R-17x.1: (1) printed bearing filters candidates: bearings +1..2, distances 0;
(2) uniqueness headroom 1-2 labels per sheet, not built; span on any candidate +0/+1/+3/+2 distances;
(3) table-order adjacency settles 0 of 5 ambiguous tags, but the row's own bearing/length/radius settles
4 of 9 (tags associated 18 -> 22, all pass); (4) closure feedback: 0 figures close, no headroom. Ceiling of
all four: +2..6 passes per sheet. Attribution of the unmatched distance labels: 27-29 per clean sheet (84 on
R-10434.3) have no drawn chain of the printed length near the label at all (runs cut by ticks, solid line
continuing as dashes, lines broken for on-line text on MicroStation, stationing/`R=` tokens read as
distances). Layer-restricted candidates (`ASSOC=layers`) on Presidio: wrong-line 37 -> 17, pass precision
44 % -> 76 %, one pass lost (a border matchline).

**Scans, by eye** (one ink-dense crop each): ~22 hand-lettered originals (the measured hard class),
~10 Leroy/mechanical lettering, ~11 CAD plots printed then scanned, ~5 not judged. 33 of 48 were
re-plotted through Civil 3D; 11 carry a hidden OCR layer; 72-478 dpi. Only R-65.2 is measured.
**LiDAR:** the one tile (2.1 x 0.9 km, Presidio) covers 6 sheets: R-10434.1/.2 and the 1969 scans R-65.1-.4
(R-10434.3 lies 5 m north of the tile edge, measured 2026-09-23 loop 3); the Marin tile added 2026-09-23 covers
R-10741.2/.3; the other sheets have none on disk (USGS 3DEP would cover D4).

Plan from this: Presidio first, overnight loop in `spike/LOOP.md`.

## Where the roadmap stands (as of the last commit)

| Roadmap item | State |
|---|---|
| D1–2 `demo.py` one command | Done, 89 s (`--fast`, of which tag reading 36 s; ends with the exception page and the QGIS project). Was 232 s: `blocks.py` scanned the full 72-Mpx label image once per component (180 s) and `assemble()` was a Python double loop (25 s); both vectorised, output identical. |
| D1–2 `objects.geojson` provenance record | Done (`spike/objects.py`). |
| D1–2 QGIS project `demo.qgz` | Done, verified. `spike/qgis_project.py` is PyQGIS, run under QGIS LTR's own Python (`%LOCALAPPDATA%\Programs\OSGeo4W\bin\python-qgis-ltr.bat`; `demo.py` routes it there, skips if QGIS is absent): 9 layers in order, hillshade + intensity, sheet linework by weight, parcels labelled, LiDAR features by kind, encroachments by verdict, object record split into points / lines / polygons by OGR `geometrytype=` and coloured by status, map tips with the provenance fields. Project CRS EPSG:6339, feet, relative paths. The script re-reads the written project, asserts every layer survives, and renders the opening view to `spike/out/demo_render.png` (the proof). First version was hand-written `.qgs` XML: loaded, but QGIS regenerated layer ids (tree links broke) and the raster renderer XML drew nothing — replaced. `objects.geojson` was cp1252 (degree signs); now UTF-8. |
| D3–6 table traverse | **2026-09-23 loop:** tags read from SHX annotations, 21-23 of 44 rows associated on Presidio, all line checks pass; traverse 49 of 87 edges with full record, one closed chain; 61985 easements still open (see Next). Earlier: **Narrowed (option C, JR 2026-09-22)**: tag reading + tag→segment association + per-row check; closure/area target dropped because the tunnel easements 61985-1..4 are drawn as dashed lines with inline bearing/distance and R/Δ/L, not table tags. `spike/tags.py` reads tags without OCR: every glyph is a stroked path, table cells with keyed truth are labelled exemplars (165 distinct bitmaps, 20 characters), each drawing path is matched at 36 rotations; 36 of 44 table rows found on the drawing, 7 partial reads queued (`L1?`, `C9??`), none wrong on the four crops checked. `spike/tables.py` associates by the leader's arrowhead (20 of 21), else the one heavy line beside the tag; two candidates → queue. Lines: bearing 9/11 pass, distance 8/10 pass (both fails are L1, a 1.86 ft radial, and L21, the dash-dot centreline: not checkable). Radius 5/7. **Arc length 6/10** (4 of them "as a run"). What the drawing puts at an arc boundary, measured: a vertex circle, a boundary line *ending* on the curve (C18's end: drawn 62.10 ft vs record 62.14), or on the thin alignment curves a 7-pt radial tick — and sometimes **nothing** (the C16/C15 boundary on the R=1470 curve has no mark; the run between circles is 573.95 ft drawn vs 573.93 (T) printed). So `split_at` cuts runs at those marks only (no crossing cuts), and a tag passes on its own length or, when several tags share a run, the run passes against their sum with the result "pass as a run of N: the boundary between these arcs is not drawn". Remaining fails: C11 (its run-mate C10 has no leader, so no sum), C19/C21/C22 (runs cut wrong on the long R/W curves). |
| D7–8 exception page | 2026-09-23: 104 items, 16 wrong-line (was 103 at the first page). Done: `spike/exceptions_page.py` → `spike/out/exceptions.html`, one offline file (4.8 MB), 100 items in 8 cause groups, each with a crop (red = label region, blue = the line the reader measured), reason, printed/drawn/difference, citation (sheet + region in PDF pt), a resolution select + note kept in the browser and exported as JSON. The scan's queue (fit not credible + 4 control pairs) is on the same page. **What the page exposed:** of 110 label-vs-line fails from `checks.py`, 103 are off by far too much to be drafting errors: the reader measured a different line (leader stubs, callout underlines, "BATTERY BLUFF" underline). Only 7 are genuine small disagreements. The page groups those 103 as "reader measured a different line" — honest, but `checks.nearest_line` needs the same leader/junction treatment `tables.py` got. |
| D9–10 LiDAR refresh | Done as far as it can be without traverse parcels (none came out of D3–6, so the faces are the same). `spike/slide_numbers.py` → `out/numbers.md` + `numbers.json`: every number to quote, from the run's files (georef, checks, exceptions, tags, parcels, LiDAR features, encroachment, tunnel profile, HTDP), plus `tunnel_profile.png`. `spike/figures.py` (PyQGIS, renders from `demo.qgz`): `fig_record.png` (checks on the LiDAR), `fig_parcels.png`, `fig_tunnel.png`, `fig_htdp.png` (linework before/after the 0.668 m epoch shift on the intensity image). Both are the last `demo.py` steps. numbers.md carries the caveat that the 61985-4 face is the unclosed 37-acre polygon, so its tunnel profile runs along the wrong figure. |
| D11 fallback recording, Q&A sheet | Q&A answers are in `ROADMAP.md`. |

## No OCR on vector sheets

`spike/read_glyphs.py` reads every text block on a stroked sheet with the sheet's own alphabet (`alphabet.npz`) and writes `read_glyph.json` in the OCR's block format; `georef.READS` points every consumer at it when it exists, `demo.py` skips the OCR step. Per block: the reading angle is re-estimated from the glyphs' best rotations and refined in 2° steps (a 24-px bitmap costs 1–4 per 2° of error; every glyph is scored at the best of ±3°); rows come from the capitals, symbols join the nearest row; a bar inside a letter's width is that letter's (E, R); symbols are named by where they sit (top = ° ' " in order, the seconds mark being two ticks; baseline = . or , by size; mid = - or =); N|S, E|W, R|L, R|T slots are read among those letters with the seed font's looser threshold; a bolder variant of a character (the parcel labels' 6) is accepted at a looser bitmap distance when its stroke count matches (a 6 is 22 strokes, a 0 is 16, an 8 is 28: stroke counts are stored in the alphabet). Presidio, glyph vs OCR: bearings 107 vs 63 parseable, distances 173 vs 166, coordinates 64 vs 61, parcel numbers 22 vs 22; georef 18 of 18 control points, RMS 0.044 ft; label checks bearing 17/32 (OCR 9/17), distance 13/39, arc 3/14; 86 exceptions. Nothing reads by confidence: a glyph either matches or is `?`.

## Alphabet without keying, and other sheets

`spike/alphabet.py`: a sheet's own alphabet from its tables. Seed = the public-domain Hershey simplex font (parent of AutoCAD's txt/simplex; digits within 0–2.5 of this lettering, 0 and 6 at 5–7). The seed finds the line/curve tables' NO. cells (L1, L2, … / C1, C2, …), the consecutive run validates them, their glyphs become exact exemplars, a second pass finds the columns the seed misread, and the row cells to the right (split at the table's vertical rules) are labelled by structure: cap-height glyphs are digits/letters scaled by the cell's own cap height (the `(T)` rows are set smaller), the small glyphs are ° ' " . in fixed order, N|S and E|W picked among letters, a `(T)` suffix is two tall parens round a capital, an E's separate middle bar is merged. Presidio: **101/101 table cells exact vs the hand-keyed tables**; L1/L2/C1/C2 have no cell of their own under the header and are not found. `gt.py` is now a validation set; `tags.py` and `tables.py` read `alphabet.npz` / `tables.json` and mask the tables where they were found. With the bootstrapped alphabet Presidio tags 37/40 rows, table checks bearing 9/9, distance 8/8, radius 5/7, arc 5/9 (4 as runs).

`spike/frame.py`: `MAP_AREA` / `FURNITURE` per sheet (see traps). `spike/sheets.py --run` (frame → alphabet → tags → tables → checks on every sheet with a credible fit; `out/sheets.csv`), all on the fresh OCR:

| sheet | lettering | tables read (rows / clean) | tags read | tag checks pass / fail | label checks distance, bearing, arc | exceptions (wrong-line) |
|---|---|---|---|---|---|---|
| R-10434.2 Presidio | stroked, read by glyph | 41 / 41 | 36 (+8 partial) | 26 / 7 | 17/39, 17/32, 3/14 | 82 (37) |
| R-10434.1 sibling | stroked, same drafter | 23 / 12 | 15 (+2) | 20 / 6 | 20/51, 10/19, 4/19 | 76 (47) |
| R-10434.3 sibling | stroked, same drafter | 77 / 32 | 66 (+38) | 19 / 28 | 26/95, 15/43, 7/30 | 158 (93) |
| R-17x.1, R-102.1aa, R-105.14 | real PDF text (Times) | no stroked tables | — | — | 40/73 21/38 0/30 · 9/24 30/37 0/16 · 37/62 46/62 1/18 | 135 (65) · 50 (36) · 75 (42) |
| R-10258.1 | real text (RomanS) | — | — | — | 0/14, 6/13, 0/12 | 39 (25) |

Association adapter (`checks.span_for`, `nearest_line` on-line rule): the breaks on a drawn run (circles, line ends, crossings) are candidate endpoints and the printed distance says which pair — the contiguous span of pieces whose length matches, if exactly one does, else the piece at the tip; and a label written on the line itself (the real-text drafters) takes that line over a parallel neighbour. Distances: Presidio 13→17 of 39, R-105.14 22→37 of 62, R-17x.1 21→40 of 73, R-10434.3 18→26 of 95. Bearings unchanged. Arcs untouched (spans not yet applied to curved runs).

What it says: the alphabet and table reader carry to the same drafter's other sheets (clean rows 52 % and 42 %: more cell formats to add, e.g. `(R)` radials and stationing). Tag association on the siblings is 13 and 26 of 15 and 66. The real-text sheets skip the whole glyph path (`real_text_blocks` feeds the label checks; distances from real text are now checked). Wrong-line counts on every sheet, Presidio included, say the label → line association is the weakest link everywhere: that is the adapter work per drafter, and it is now measured.

## The archive as it is: what is on disk and what reads

65 sheets on disk (`Sample Data/`): **48 scans, 17 vector** (a scan = more than a megapixel of raster on the page, whether one image or strips; the first census called 17 bordered scans "vector" because they carry a few hundred drawn paths). The scans are hand-lettered originals; their filing dates (2017–2026) are scan dates. `spike/sheets.py --run --all [--missing]` runs every vector sheet — `out/sheets.csv`, `out/sheets_all3.log`.

Vector sheets through the whole chain: **7 of 17 georeferenced** (R-17x.1, R-71.71, R-102.1aa, R-105.14, R-10258.1, R-10434.1/.3; all by grid or callouts, R-71.71 only since the table-free alphabet). The other 10 fail at the georeference, all for one reason: **the reads**. They are other drafters' fonts; the Hershey-seeded alphabet without a NO. column to validate it reads them as fragments (R-10403: `?70°5,'55L(?` for `N70°52'55"E(R)`; its font draws an N as three paths, an E as a path plus two bars, a ° as 53 segments — `merge_pieces` joins the pieces now, the seed still does not fit), and OCR on stroked text gives 2–6 parseable bearings a sheet. `READS` now prefers the glyph read only where the tables validated the alphabet, else OCR. Where reads exist the frame follows: R-10462 has 4 callouts and 4 bearings, the two-callout fit and the bearings disagree by 0.53° and the solver refuses it (the Caltrans package sits 8.5 ft off that fit) — the refusal is right.

Scans, measured on R-65.2 (1969) against 32 boxes keyed by eye (`spike/gt_scan.py`; `spike/scan_readers.py`): digits exact — RapidOCR 20/32, local vision model (qwen2.5vl:7b, tight levelled crop, no example values) 20/32, either 25/32, both agree and right 15/32. Misses are dropped leading digits ("996.26" for N9996.26), a 4 read as 1, and box detection landing on the wrong line. `spike/scan_consensus.py` over all 273 boxes: 59 agree, 2 repaired (dropped leading digit restored inside the grid range read off the border labels), 212 queued with both reads (`read_scan.json`); on the keyed 32: 16 right, **1 wrong accepted** (both readers read the neighbouring line), 15 queued. Two generic readers agreeing is not yet a trusted read; the per-sheet template alphabet (gap 1) is.

## Gaps against the problem statement, and the bridges

The problem is the archive (record maps, most of them scans of hand lettering) plus LiDAR to a trusted, georeferenced object record. Measured against that, the gaps in order of what they cost:

| # | Gap | Measured | Bridge | Status |
|---|-----|----------|--------|--------|
| 1 | **Scans are most of the archive and read at ~half.** | 1969 R-65.2: 273 boxes, two readers agree on 59; on the 32 keyed boxes 16 right, 1 wrong accepted (both readers misread the same box), 15 queued. | A sheet's hand is one hand: cluster the glyph images per sheet, label each cluster once (the vector alphabet idea, on pixels), read the rest by template. Agreement of two generic readers is the floor, not the method. | not started |
| 2 | **Most R/W maps have no coordinate grid.** The grid/callout solver has nothing on them. | Of the vector sheets that failed the chain, every true stroked sheet failed here (see census below). | `solve.record_frame`: rotation from the printed bearings against the lines they label, scale from the printed distances, offset from the callouts; each a robust cluster (a label on the wrong line is an outlier, not a vote). Checked against the grid fit on two sheets: scale to 0.02 %, rotation to 0.002°, offset to 0.1 ft; 24 callouts within 4.5 ft on R-105.14. Gives every sheet with readable bearings a frame; without a callout it is a local frame the Caltrans package or a monument places. | built, validated |
| 3 | **Sheets in another lettering font read as nothing.** The alphabet seed (Hershey futural) fits Presidio's drafter; on the 10 vector sheets without tables the seed-only alphabet reads fragments and OCR reads 2–6 bearings. | 10 of 17 vector sheets: 0–6 bearings parsed, so no frame. | Built: `read_glyphs` learns by structure — a row that parses as a whole token (`VALID`) gives exact exemplars, unread N/S and E/W slots of bearing-shaped rows are pooled, clustered and named by the seed's relative call (`resolve_slots`); `tags.glyphs` no longer drops a character whose paths touch each other (only touching linework counts); `merge_pieces` shared with the alphabet. Then the unsupervised start (`structure_seed`): rows shaped like a bearing or a distance say which glyphs are digits before anything is read; those are clustered by bitmap and each cluster takes the seed digit it is nearest to, only if it is that digit's best cluster (a digit at two sizes is two clusters). Decimal point vs thousands comma by the digits after the mark (`read_row`); two- or three-decimal distances per sheet (`checks.set_decimals`). Result: R-10237 (font near the seed) names 9 digit clusters at cost 0–2 and parses 11 bearings, 6 agreeing on the rotation; R-10462 4/4 bearings agree; R-10403 `?70°52'55"E(R)`. **Still no frame on any of them**: the scale needs the distances placed on their lines, and on these dense sheets the distance→line association is scattered (R-10237: 34 distance tokens, 19 with no line, the rest at 0.03–0.44 ft/pt, no cluster); the printed scale ("1"=20'") reads on none of them. So on these sheets it is again association, not reading, that stops the frame. Presidio unchanged through all of it (18/18 control, distance 17/39, bearing 16/31). | built; frames still refused |
| 4 | **No reconstruction from the numbers yet.** Checks say a label agrees with its line; nothing walks a figure and closes it. | Presidio: 81 record edges placed on the drawing (`labels.json` + `tag_labels.json`), 22 lines with bearing and distance, 7 curves with R and L; they chain into runs of at most 3; **0 closed figures**. Walked by record, the 22 full edges land within a median 0.10 ft of the drawn vertex (90 %: 18.6 ft — the wrong-line associations, e.g. a 1520.00' on a 206 ft line). Named faces are the corridor, not parcels (148-edge figure; 11–33 % of a face boundary is under a record edge). | `traverse.py` built: edges from the placed record → chains by shared ends → walk by bearing/distance and chord → per-edge misfit vs the drawing, closure and record area where a chain closes; each named face walked with record where placed and drawing elsewhere, flags per piece (`traverse_figures.json`). What it needs to close a figure is what gap 3 and the association work supply: the rest of the edges. On this sheet the record is not on the drawing for most of a parcel's boundary (the tables describe the R/W line, the easements carry inline values on a few sides). | built; nothing closes yet |
| 5 | **Independent control is the sheet's own.** Fit credibility comes from agreement among the sheet's labels. | Caltrans georef packages exist for the D4 sheets (`vs_caltrans_package`, ~1 ft); some sheets print NGS PIDs with published coordinates (R-71.70: PID AE9850, AE9865). | Pull NGS datasheets by PID (public) and use them as control that did not come off the sheet; the package as the second check. Cheap, and the only thing that turns "consistent" into "true". | not started |
| 6 | **No per-object uncertainty.** | — | Falls out of 4 and 5: closure misfit, control residual, reader agreement, per object. | after 4 |

Tangential to the problem and parked until the last week: walkthrough refresh, run of show, QA rehearsals.

## Numbers to quote (measured, from the run)

- Georeferencing: 7 of 17 vector sheets credible, 10 refused (reads); Presidio 18 control points by glyph, RMS 0.043 ft; vs Caltrans' own package ~0.6–1.1 ft (raster-limited). Record frame (bearings + distances + callouts, no grid) vs grid fit: scale 0.02 %, rotation 0.002°, offset 0.1 ft on R-105.14 and R-71.71.
- Checks (Presidio, fresh OCR, derived frame): distance 15/41, bearing 9/17, arc 2/16 pass; where a label passes it agrees to a few hundredths of a foot; 80 exceptions (`spike/out/exceptions.json`).
- Table tags (Presidio, bootstrapped alphabet): tables 101/101 cells exact vs keyed; 37/40 rows found on the drawing, 9 partial queued, 0 misread; 18 associated (18 by leader); bearing 9/9, distance 8/8, radius 5/7, arc length 5/9 of which 4 as a run (`spike/out/tags_checks.csv`).
- Record arcs vs drawing: a drawn run between vertex circles is the (T) total to 0.02 ft (573.95 vs 573.93); a sub-arc boundary that is not drawn cannot be checked alone, only by sum.
- Scan (1969 R-65.2): 273 boxes detected; two readers agree on 59, 2 repaired, 212 queued; keyed 32: 16 right, 1 wrong accepted, 15 queued; two chance 4-point fits caught by the grid-label scale check; not georeferenced.
- LiDAR: flown 2025-09-27; HTDP epoch shift 0.668 m N33°W; flightline RMSE 0.02–0.04 m off-slope; 32 pavement, 11 deck, 175 building polygons; 81% of highway pavement inside the drawn R/W faces.

## Known traps

- OCR confidence does not separate right from wrong; use geometry.
- `alphabet.no_columns` can find a false NO. column on a sheet without tables (R-10334: 7 "rows" over `1345678L`): the run-of-consecutive-numbers test passes on a stationing column. A found table should also have cells to its right that parse as bearings or distances before it counts.
- A font that draws one letter as several touching paths (R-10403) needs `tags.glyphs` to count only linework as "connected"; and its period is bigger than 1 pt, so a low mark is named by the digits after it, not its size.
- A 4-point fit with 0.3 ft residuals can be wrong by 13% in scale; always check against independent control (grid labels, Caltrans package).
- Vision-model prompts must not contain example values (the model copies them).
- Admitting dashed lines to the parcel polygonisation shatters the corridor (70 faces). Chaining the 0.84-pt dashes with `lines_on_sheet(max_turn 6)` does not shatter (31 faces) but the easement strips still do not close.
- OCR text blocks beside the R/W line absorb stationing ticks and leader arrowheads (both glyph-sized), which skews their angle; read tags from the glyph paths instead (`tags.py`).
- Leaders share the lettering weight (1.02 pt) and end at a filled triangle; hatch is gray 0.50; the alignment curves are 0.36 pt; ticks are 7.2-pt stubs. Width alone does not separate "line a tag describes" from furniture.
- `checks.nearest_line` (label → nearest parallel line) used to pick the label's own leader stub or underline: 103 of 110 fails were wrong-line. Fixed in `checks.py` (leaders by arrowhead or circle, leader paths and stubs and underlines excluded, gray hatch excluded, table cells skipped, straight chains split at circles/junctions/crossings, `split_chains`). Wrong-line is now 31: remaining causes are cut points 5–20 ft off where lines cross the R/W run, and leaders whose arrow lands where three pieces meet.
- `split_chains` in `tables.py` hurts (8/10 → 4/10): tag leaders land on whole segments that already end at circles; crossing dashes cut them. Left out there.
- The exception page's "reader measured a different line" group is the fastest diagnostic there is: render the measured line, look at 12 crops, fix the biggest cause, repeat. Four rounds took the wrong-line count 103 → 31.
- Qt reads an 8-digit hex colour as #AARRGGBB, not #RRGGBBAA: buildings came out magenta. Use `QColor(hex6)` + `setAlpha`.
- `QgsMapSettings.setLayers` takes the stack top-first (legend order); rasters listed first paint over everything.
- The OCR was stale for longer than that: the committed `read_rapid.json` (1,345 blocks) predates the "whole-word paths" segmentation (1,173 blocks). Every label-check number quoted before the re-run (distance 25/46 etc.) was built on it. Re-run done; the fresh baseline on Presidio is distance 15/41, bearing 9/17, arc 2/16, 80 exceptions, georef 15 control points, RMS 0.043 ft. Two causes of the drop, one fixed: the new segmentation returns a bearing and its distance as one OCR line, which the whole-part regexes missed (`checks.TOKEN` now finds the tokens inside a line); the OCR itself reads the merged blocks worse (fewer coordinate callouts: 15 control points, were 19). `--fast` skips OCR, so re-run `ocr.py rapid` after any `blocks.py` change.
- `frame.py` derives `MAP_AREA` / `FURNITURE` per sheet (R/W-weight lines + vertex circles + used control points, padded; dense upright text + the tables alphabet.py found). Every attempt to include the 0.84-pt parcel lines pulled the box to the sheet border (title-block and legend lines share that weight). Cost on Presidio: the box stops at y 1086 where the constant said 1285, so the parcel faces below the highway are cut (60 faces / 5 named vs 27 / 6 with the constants). Kept because it is what every other sheet gets; the constants only ever fit Presidio.
- The tag reader must mask the tables wherever they are on a sheet (`_regions` in `tables.json`), not Presidio's coordinates: on R-10434.3 every NO. cell read as a drawing tag until it did.
- Never name a script after a stdlib module: `spike/numbers.py` shadowed `numbers` and broke numpy in every process that had `spike/` on `sys.path`.
- QGIS project files: do not hand-write the XML. QGIS regenerates layer ids on save (layer-tree links break) and half-specified renderers load "valid" but draw nothing. Build with PyQGIS and render a PNG as the check.
- Windows: Bash heredocs eat backslashes in regexes; write patch scripts with the Write tool. `PYTHONIOENCODING=utf-8` for any script printing survey symbols.
