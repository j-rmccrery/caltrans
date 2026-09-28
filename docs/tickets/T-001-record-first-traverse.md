# T-001: Rebuild the traverse from the record first, compare to the drawing last

Status: parked (JR, 2026-09-28: "leave that out for now, write a ticket to come back to it later")
Raised in: loop 17, after leg C showed the R-10741 labels are read correctly and the losses are label-to-line association.

## Idea
Today traverse.py builds edges from drawn pieces and hangs record values on them; every lost foot of reconstructable
boundary traces back to that label-to-line step (spike/out_recon/attribution.md). A surveyor works the other way:
chain the printed courses end to end (bearing + distance, curve R/delta/L, table rows), close the figure from the record,
and only then compare the result to the drawing. Association would only be needed to put courses in order, not to
supply values.

## Why parked
Largest change in the pipeline (a second traverse builder), and course ORDER still has to come from the sheet. Cheaper
levers first: loop 17 legs D (attach read bearings), E (PDF draw-order / grouping probe), F (inverse label-style
placement).

## Come back when
- Loop 17 E/F are measured and association losses still dominate attribution.md, or
- the native DGN/DWG files arrive (then record order comes with the objects and this becomes cheap).

## Done means
A record-only chain per figure (no drawn values in it), its own closure, and recon.py counting a figure only when the
record chain closes and lands on the drawn boundary within tolerance; bench columns and gold wrong-pass unchanged.
