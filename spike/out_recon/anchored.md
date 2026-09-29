# Anchored record walk (loop19 leg 1 + leg 2 + leg 3)

## presidio

anchors 25 (6 unplaced) | reconstructed edges 57 | nodes 72

closed 7 (3 by branch resolution) | failed 0 | open 19 (1 ambiguous branches)

recon_anchored: 337/10,648 ft (3.2%)

closed misclosure ft: median 0.008, max 0.014

| start | end | courses | length ft | misclosure ft | resolved |
|---|---|---|---|---|---|
| CO1 | CO2 | 4 | 419.29 | 0.007 |  |
| CO18 | CO4 | 4 | 407.53 | 0.005 | Y |
| CO18 | CO4 | 3 | 360.8 | 0.014 | Y |
| CO2 | T-5 | 2 | 356.07 | 0.008 | Y |
| CO7 | T-1 | 2 | 286.07 | 0.011 |  |

ambiguous branches (2+ continuations close, left open):

| start | courses so far | candidate ends |
|---|---|---|
| CO4 | 1 | CO18 |
recon_closure: 0/0 fills accepted, +0.0 ft (net, folded into recon_anchored above)


## r10434_1

anchors 10 (1 unplaced) | reconstructed edges 32 | nodes 48

closed 1 (0 by branch resolution) | failed 0 | open 12 (0 ambiguous branches)

recon_anchored: 322/9,079 ft (3.5%)

closed misclosure ft: median 0.010, max 0.010

| start | end | courses | length ft | misclosure ft | resolved |
|---|---|---|---|---|---|
| CO9 | CO11 | 4 | 558.09 | 0.01 |  |
recon_closure: 0/1 fills accepted, +0.0 ft (net, folded into recon_anchored above)


closure fills -- leg 3, a fill counts only when a second landing checks it:

| A->B | course | missing | computed | vs. drawing | status | reason | ft added |
|---|---|---|---|---|---|---|---|
| CO13->CO8 | 176.33' | bearing | 178.3795 deg | 178.377 deg (+0.002 deg) | refused | unchecked (no third anchor reached) | 0.0 |

## r10434_3

anchors 31 (15 unplaced) | reconstructed edges 50 | nodes 84

closed 0 (0 by branch resolution) | failed 0 | open 19 (0 ambiguous branches)

recon_anchored: 0/17,271 ft (0.0%)

recon_closure: 0/3 fills accepted, +0.0 ft (net, folded into recon_anchored above)


closure fills -- leg 3, a fill counts only when a second landing checks it:

| A->B | course | missing | computed | vs. drawing | status | reason | ft added |
|---|---|---|---|---|---|---|---|
| T-3->T-2 | L=181.54' | chord direction | 104.7782 deg | 104.78 deg (-0.002 deg) | refused | unchecked (no third anchor reached) | 0.0 |
| T-4->T-3 | N35°15'31"W | distance | 198.231 ft | 183.05 ft (+15.181 ft) | refused | unchecked (no third anchor reached) | 0.0 |
| T-18->T-16 | S87°48'20"E | distance | 973.14 ft | 114.29 ft (+858.850 ft) | refused | unchecked (no third anchor reached) | 0.0 |

## cross-sheet (south set: presidio + r10434_1 + r10434_3)

anchors pooled 66 | edges pooled 139 (0 matchline pairs collapsed) | anchor pairs matched 0 (0 disagree > 0.1 ft)


new (cross-sheet-join-only) closed 0 | failed 0


ponytail: leg 3's closure_fills() (half-recorded row completed by a third anchor) is NOT run on the cross-sheet graph -- task 1 asks only for the walk + branch resolution (legs 1-2); a real run of this data showed why: pooling three sheets' anchors widens the half-recorded row's own third-anchor search enough that BEARING_TOL_DEG (1 deg, fine within one sheet's small local pool) let a spurious ~4,700 ft distance solve through as "accepted" on a coincidental bearing match, not a record-verified course.


## set

recon_closure_ft (sum over sheets with anchors -- ponytail: not deduped across matchlines the way recon_set.py's own set numbers are, negligible at 0 accepted fills): 0 accepted, +0.0 ft
