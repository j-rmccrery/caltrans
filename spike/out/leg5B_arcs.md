# Loop5 legB: arc-length attribution, south sheets (presidio, r10434_1, r10434_3)

Every non-pass `arc length` row plus every unmatched `L=`/`(T)` exception, current state (post leg5A,
before any legB code change; the numbers below are unchanged after legB's fix -- see "Rule fired" at
the bottom). Crops: `spike/out/leg5B_arcs.png` (presidio, 12), `spike/out/r_10434_001_2020-09-16/
leg5B_arcs.png` (r10434_1, 12), `spike/out/r_10434_003_2020-09-16/leg5B_arcs.png` (r10434_3, 12). Red
box = the label; blue = the drawn piece the reader measured, when one was found.

## Cause counts (65 non-passing arc-length items across the 3 sheets)

| sheet | MISS: standalone L=/(T), no drawn piece within reach (no neighbour to sum with) | L=/(T): a leader found a candidate, wrong length (the loop2 legC / STATE.md compound-curve pattern) | bare number (DIST-branch arc fallback): label on a line, or beside picked the wrong piece -- a different code path, out of legB's scope | total |
|---|---|---|---|---|
| presidio | 6 | 1 | 5 | 12 |
| r10434_1 | 10 | 4 | 14 | 28 |
| r10434_3 | 9 | 3 | 13 | 25 |
| **total** | **25 (38%)** | **8 (12%)** | **32 (49%)** | **65** |

Representative rows (printed / drawn / cause):

| sheet | printed | drawn | cause |
|---|---|---|---|
| presidio | L=171.66' | 530.45 (+358.79) | leader found a candidate (the whole undivided run split_at could cut this far and no further); no other pending L=/(T) label shares that exact drawn object -- the C15/C16-class run STATE.md names, but its own would-be run-mates (L=206.36', L=184.70'(T), L=232.07'(T)) each search their own leader/near-pool to a *different* candidate or none at all, so no group forms |
| presidio | L=573.93'(T) | MISS | no candidate within 5 glyph heights or 160pt matches; the piece STATE.md measured at 573.95' isn't in the current candidate pool at all (checked directly: nearest length match anywhere on the sheet is 530.45' at 98pt) -- a side effect of loop3/4/5A's own split_at changes (circle-run-by-nearest-circle-index, tick direction, arrowhead-scaled reach), not something legB's grouping can recover without guessing |
| r10434_1 | L=1804.98' | 58.71 (-1746.27) | leader found *a* candidate, but the wrong one by a wide margin -- not a same-run neighbour case, a wrong-piece pick |
| r10434_1 | 9.30' | 257.65 (+248.35) | bare number next to "N40°55'51"E 9.30'" (a bearing+distance line label); the DIST branch's arc-fallback grabbed an unrelated long curve when the line-length match failed first -- "label on a line, not a curve" |
| r10434_1 | 8.72' | 37.28 (+28.56) | bare "8.72'" is this curve's own printed *radius* (R=8.72'), not a length -- an OCR/split artifact fed into the arc-length check as if it were a distance |
| r10434_3 | L=409.98' | 143.37 (-266.61) | leader found a wrong-length candidate, no shared-run neighbour among the other pending labels |
| r10434_3 | L=349.23'(T) | 211.84 (-137.39) | leader found a wrong-length candidate; a (T) total with no group to check it as (own run only) |

## Cause class definition used above

- **MISS**: `at_tip` (leader) found nothing within reach, or there's no leader and neither the 5-glyph-height
  nor the 160pt search found a piece whose length matches within tolerance. All 25 are `L=`/`(T)` labels
  (the bare-number branch never MISSes this way -- see below).
- **L=/(T), wrong length**: the label's own leader (`at_tip`) landed on a real drawn piece, but that
  piece's length doesn't match the label's printed value. This is the class legB's rule targets: a
  compound curve whose *interior* record boundary isn't drawn, so the reader can only find the *outer*
  drawn run, which is longer than any one record arc printed on it.
- **bare number (DIST-branch fallback)**: `checks.py`'s distance branch (a plain `\d+\.\d\d'` token, no
  `L=` prefix) tries a line first; when the line doesn't match, it falls back to the nearest arc within
  5 glyph heights (`nearest_arc`, not `at_tip`'s tip-anchored search). This is a *different* branch of
  `checks.py`, not the standalone-`L=` code legB's rule touches -- confirmed by crop inspection (item 1,
  4, 9, 10 in `r_10434_001`'s crop grid): several of these are bearing+distance *line* labels or a
  radius value (`R=8.72'`) misrouted into the arc check, not compound-curve boundaries at all.

## Rule added (checks.py, shared with tables.py)

`run_sum(drawn, Ls)` (checks.py): `total = sum(Ls); by_sum = len(Ls) > 1 and abs(drawn - total) <=
DIST_TOL + 0.0005 * total` -- the exact test tables.py already ran inline for table-tag curves, now a
one-function shared rule both files call.

Inline `L=`/`(T)` labels (checks.py's standalone-`L=` branch): a label whose own length matches no
drawn piece is deferred (`len_pending`) instead of failing immediately. A leader tip already pins the
drawn run it points at, matched-or-not (`at_tip`'s existing fallback, unchanged); deferred labels are
grouped by that drawn object's identity (`id()`, the same key tables.py's own `by_run` uses) once every
block on the sheet has been scanned. A `(T)` total in a group is always checked directly against the
whole run (never summed in). The rest of the group: `len(group) <= 1` keeps the original single-label
FAIL ("stays as it is" -- nothing to sum with); `by_sum` true passes every member as "pass as a run of
N: the boundary between these arcs is not drawn" (tables.py's own result text); otherwise the group
fails **once**, against the sum, not once per label.

**A label with no leader gets no length-blind fallback.** A first version also let a no-leader label
grab the nearest drawn piece within 5 glyph heights regardless of length, so it could join a group too.
Measured: it fired on all three sheets, formed one group (presidio, below) and otherwise just converted
previously-silent MISS labels into visibly-wrong FAILs against the *wrong* piece -- wrong_line rose on
all three south sheets (+3 / +3 / +6) for zero pass gain. Reverted; a no-leader label without a length
match stays an unmatched exception, same as before this leg.

## Fire count

The grouping code runs (it evaluates every deferred label and builds `by_run`), but across all 65
non-passing items on the 3 south sheets, **zero** groups of size > 1 form under the safe (leader-only)
matching -- every one of the 8 "L=/(T), wrong length" items is alone on its drawn run as far as any
*other* pending label's own leader can show. The one candidate pair found during development (presidio's
`L=206.36'` + `L=171.66'`, both leading to the 530.45' piece) only appeared under the reverted no-leader
fallback and is not part of the shipped rule.

`checks.csv`/`exceptions.json` content is byte-identical to `leg5A-check` on all three sheets after this
leg (confirmed via `git diff`: only row *order* changed, since deferred rows are now appended after the
block loop instead of inline). No pass gained, none lost, wrong_line unchanged.
