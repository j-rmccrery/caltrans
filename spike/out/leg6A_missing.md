# Loop6 legA: the 12 largest-printed-L standalone MISS labels, south sheets

12 crops (4/sheet, largest printed `L=`/`(T)` among the 25 south "MISS" items from loop5 legB:
standalone `L=`/`(T)` with no drawn piece matching within reach at all -- not the separate 8-item
"leader found a candidate, wrong length" class legB already named). Red box = the label; blue = every
curved piece in `checks.build_pool`'s own arc pool within 8 glyph heights, each tagged with its own
drawn length. Crops: `spike/out/leg6A_tiles/*.png` (12 tiles, referenced below); stitched grid
`spike/out/leg6A_missing.png`.

## Per crop

| # | sheet | printed | arc the label describes (traced by eye) | pool pieces on it | cause |
|---|---|---|---|---|---|
| 1 | presidio | L=573.93'(T) | ROUTE/PRESIDIO PKWY compound curve, R=1470' Δ=22°22'12", the outer corridor edge past C12-C19 | 501.10, 410.29, 100.01x2, 60.43, 52.22, 48.12, 26.50, 20.63 (many circle-bounded slivers) | (a) fillet split into slivers -- **FIXED**: 52.22+20.63+501.10=573.95 |
| 2 | presidio | L=289.24' | small ramp fillet, R=245.00' Δ=67°38'33", near RAMP LINE 2 / MATCHLINE | 274.87, 231.91, 45.93, 10.80 (all straight RAMP LINE 2 distance-label segments, not curved) | (b) curve not in the candidate pool at all -- the small quarter-circle icon beside R=245' never becomes an `arcs_on_sheet`/`lines_on_sheet` candidate (likely filtered by colour/weight or too short); the search lands on the neighbouring straight ramp edges instead |
| 3 | presidio | L=232.07'(T) | same ROUTE/PRESIDIO PKWY corridor as #1, R=1520' Δ=8°44'52" sub-run | seed's own parent run: 90.27, 199.99, 32.15, 67.83, 100.03, 99.97, 200.01, 100.01, 100.01, 41.85, 58.14, 139.99 -- no contiguous window sums to 232.07 even at 500pt/20 seeds | (a)-family, unresolved: `lines_on_sheet`'s generous 20&deg; turn tolerance chains this busy interchange's several named curves into one over-long parent; split_at's own cuts inside it don't land on this sub-curve's true record boundary |
| 4 | presidio | L=206.36' | same interchange corridor as #1/#3 | 530.45+60.43 pair, or the same 12-piece merged-parent run as #3 -- no window matches | same interchange-merge cause as #3 |
| 5 | r10434_1 | L=1334.12' | RAMP LINE 1/ROUTE loop near "61806-1 AT GRADE" | 800.03, 599.72, 491.90, 248.99, 99.98, 78.02, 43.51x2 -- no window matches | (a)-family interchange-merge, unresolved (same mechanism as #3/#4) |
| 6 | r10434_1 | L=869.14' | MAIN LINE 1/2 compound curve, R=3670' Δ=13°34'08", running toward "SEE DETAIL E FOR CONTINUATION" at the sheet's MATCHLINE | 46.28, 16.48, 83.52, 200.02, 99.96, 100.01, 800.03 (the 800.03 piece is a different road's chain merged in) -- no window matches | (c) cut by the matchline: the curve's own printed run continues past the MATCHLINE into the "DETAIL E" continuation box; not fully drawn at record precision on this sheet alone |
| 7 | r10434_1 | L=869.14' (2nd instance, inside DETAIL "E") | the same physical curve, redrawn inside the DETAIL "E" inset at its own printed "SCALE: 1"=100'" | 82.35, 99.97, 16.54, 183.47, 16.53, 83.49, 99.99, 175.69 -- no window matches even ignoring scale | (c)/(b) hybrid: a scaled detail inset is real geometry, not not-to-scale, but `checks.py` measures every candidate through the ONE sheet-wide ft/pt scale; a detail box drawn at its own explicit scale needs its own factor, which nothing in the pipeline currently supplies |
| 8 | r10434_1 | L=357.21' | MAIN LINE 1/2 compound curve, R=7381' Δ=2°46'22", the first (near) record segment of the same run as #6 | 9.12, 399.99, 31.77, 0.03, 0.01, 168.19, 300.01, 100.01, 346.14, 0.79, 253.08, 86.77, 13.21, 100.01, 100.01, 167.62, 0.12, 6.95 (18-piece merged-interchange parent) -- no window matches | same matchline/DETAIL-E cause as #6 |
| 9 | r10434_3 | L=757.83' | RICHARDSON AVE / Palace of Fine Arts compound curve, many small named sub-curves (R=437.62', R=475.00', R=1765.00', R=611.95' x3, R=544.81', ...) sharing one drawn run | 1663.52 (whole-path candidate) plus 384.40, 198.23, 181.53, 177.38, 171.37, 169.40, ... (14 pieces) -- no window matches | (a)-family, unresolved: dense compound-curve cluster, this specific sub-total's record boundary doesn't align with any of split_at's own cuts |
| 10 | r10434_3 | L=577.57' | MAIN LINE 2 curve near TUNNEL-MAIN POST, R=2075' Δ=15°56'53" | 481.01 alone (off -96.56); 96.58 piece across a stationing tick ("60" tie mark) | (a) fillet split at a stationing tick -- **FIXED**: 481.01+96.58=577.59 |
| 11 | r10434_3 | L=537.96' | same RICHARDSON AVE cluster as #9, R=611.95' Δ=50°22'05" sub-arc | seed run of 2: 198.23, 177.39ish -- sum 375.62, no window matches | (a)-family, unresolved: same dense-cluster cause as #9 |
| 12 | r10434_3 | L=406.62' | GIRARD RD/GORGAS AVE alignment cluster, many small joined R=/Δ=/L= blocks | 1277.17 (whole path) plus 145.60, 102.01, 93.88, 93.18, 57.65, 46.44, 34.08 -- no window matches within the safe 160pt seed reach. **A wider 500pt/15-seed search DID find a "unique" sum (114.19+192.91+2.57+96.18+0.87=406.71) -- crop-checked and rejected: the matched run sits ~180pt away on GIRARD RD/HALLECK ST, a visibly different curve than the one beside the label.** Reverted; reach capped at 160pt in the shipped rule | (a)-family, unresolved (the widened search's "match" was a false positive, not a real fifth cause -- see Rule below) |

## Cause counts (this 12-crop sample)

| cause | count | of which fixed |
|---|---|---|
| (a) fillet/compound-curve split into slivers whose sum equals L | 8 (#1,3,4,5,9,10,11,12) | 2 (#1, #10) |
| (b) curve missing from the candidate pool (or search lands on an unrelated nearby chain) | 1 (#2) | 0 |
| (c) cut by a matchline / continues in a scaled DETAIL inset | 3 (#6,7,8) | 0 |
| (d) label describes an arc drawn elsewhere (detail) | 0 | -- |
| (e) piece exists at the right length but past reach | 0 (folded into b/c above where seen) | -- |

Dominant cause: (a), the same fillet-oversplit pattern loop5 legB already named for the R=/L= joined-block
class, generalised here to lone `L=`/`(T)` labels with no printed R of their own. Two mechanisms drive it in
this sample: an ordinary vertex-circle/tick cut (#1, #10 -- both fixed) and a busy-interchange `lines_on_sheet`
merge that chains several NAMED curves into one over-long parent whose internal cuts don't land on any single
sub-curve's true record boundary (#3-5, 9, 11-12 -- structurally the same fillet-splitting problem, but the
fix's contiguous-window search (bounded to a safe 160pt seed reach, verified against a real false positive at
wider reach -- see #12) can't recover a window that was never cut at the right place to begin with). The
6 items outside this 12-crop sample that the shipped rule ALSO fixed (`L=60.39'`, `L=184.70'(T)` on presidio;
`L=129.96'`, `L=124.05'` on r10434_3) are all cause (a), ordinary vertex-circle slivers, same as #1/#10.
