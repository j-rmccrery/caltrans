# probe_draw_order.py -- Loop17 leg E

## presidio
- gold pass (label:N, distinct-line proximity match ok): 79 / 98 (5 annot no-match, 13 true-line no-match, 1 labels.json index past current file end -- live pipeline drift)
- true line's own annot-order-key offset: median 1654, IQR [1552, 1738]
- ranks 2-5 candidate offset: median 1545 (n=310)
- true line is rank-1 by raw distance from label anchor: 56/79
- Q2: 532 OC-tagged BDC groups, 0 other BDC, 0 form XObjects, 0/880 annots carry /OC, tick-mark re-merge touch rate 0.07
- Q3 rule vs naive top-1 (leave-one-out per how-bucket, scored n=79): rule 38/79, naive 56/79
- wrong-line fails probed: 7 -> presidio_q3_wrong.json

## r10434_1
- gold pass (label:N, distinct-line proximity match ok): 51 / 60 (3 annot no-match, 0 true-line no-match, 6 labels.json index past current file end -- live pipeline drift)
- true line's own annot-order-key offset: median 2329, IQR [2274, 2384]
- ranks 2-5 candidate offset: median 605 (n=197)
- true line is rank-1 by raw distance from label anchor: 16/51
- Q2: 494 OC-tagged BDC groups, 0 other BDC, 0 form XObjects, 0/750 annots carry /OC, tick-mark re-merge touch rate 0.09
- Q3 rule vs naive top-1 (leave-one-out per how-bucket, scored n=51): rule 14/51, naive 16/51
- wrong-line fails probed: 8 -> r10434_1_q3_wrong.json

## r10434_3
- gold pass (label:N, distinct-line proximity match ok): 87 / 109 (3 annot no-match, 10 true-line no-match, 9 labels.json index past current file end -- live pipeline drift)
- true line's own annot-order-key offset: median 2543, IQR [2406, 2690]
- ranks 2-5 candidate offset: median 800 (n=321)
- true line is rank-1 by raw distance from label anchor: 31/87
- Q2: 832 OC-tagged BDC groups, 0 other BDC, 0 form XObjects, 0/1449 annots carry /OC, tick-mark re-merge touch rate 0.074
- Q3 rule vs naive top-1 (leave-one-out per how-bucket, scored n=87): rule 27/87, naive 31/87
- wrong-line fails probed: 18 -> r10434_3_q3_wrong.json
