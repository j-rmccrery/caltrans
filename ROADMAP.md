# SWYFT Record Twin: revised plan and roadmap

## Context

The original scope (`caltrans/Caltrans_Demo_Scope.pdf`, 2026-09-21) planned two spikes, then Track A
(record extraction) and Track B (LiDAR fusion) for the 2026-10-05 Caltrans Vendor Pitch Day. Two weeks
of spikes are done (9 commits on `caltrans-spike`). What was learned changes the plan:

- Reading vector CAD sheets is solved enough (92% on table values). **Association** — which drawn line a
  label describes, which face a parcel label names — is the wall, and heuristics on rotated labels do
  not generalise (distances 17/88, bearings 11/38 on the Presidio sheet, every fail an association).
- Georeferencing is solved and verified for 8 of 11 CAD sheets, but Caltrans already ships a
  georeferenced package (~1 ft) for most maps. Georeferencing is a means, not the product.
- The authoritative record is the **numbers** (line table L1–L21, curve tables C1–C23, coordinate
  callouts, parcel table), read at 96%+. Reconstructing geometry from them (a traverse) gives parcels,
  closure and the checks without label-to-line heuristics. That is literally "AI proposes, geodesy
  disposes" and it was in the submission; it was not in the spike plan.
- Most of the archive, including recent filings, is scanned. Hand lettering defeats both local readers
  (agree on 1–2 of 87 boxes). Two chance georeferencing fits with 0.3 ft residuals were caught only by
  independent control. The scan is a QA story for the demo, not a solved input.
- Airborne LiDAR supports deterministic surface and footprint extraction (pavement, viaduct deck,
  buildings) and record-against-ground; it cannot give curbs, signs or monuments. No mobile LiDAR exists.
- There is no UI. QGIS over GeoJSON/GeoTIFF is the screen.

End goals, in order: (1) 2026-10-05: a live 25-minute demo that earns an invitation to scope a pilot;
(2) a 3–6 month pilot on one district or corridor with a measured baseline; (3) the product as submitted.

Consults: gpt-oss:20b and Qwen3 27B (local, via Ollama) were briefed with the state above and asked
for critique, ranking and roadmaps (both ran out of output budget before finishing; their partial answers
are in the session task log). Points that changed the plan are marked **[consult]**:
- Freeze scope to one sheet set and make the run one command, reproducible, offline (both).
- Treat label-to-line association as an assignment problem with uniqueness: ambiguous → queue, never
  guess; leader-aware; curves parametrised from the curve tables and fitted to the strokes (both).
- For scans, grid ticks are the primary anchor and text is validation; require two independent anchor
  classes; publish an uncertainty, not just residuals (Qwen).
- Do not claim sub-foot agreement with Caltrans' packages (raster-limited); claim records-research
  grade until the pilot sets a tolerance (Qwen).
- The champion's KPI is surveyor hours, not accuracy; liability and sign-off must be explicit; a
  reviewer must be able to inspect an object's provenance in seconds (Qwen).
- The submission's "pilot-ready in one month" is a Q&A liability; answer "one month to start, three to
  validate" (Qwen).
- Rejected: "fake a point cloud" for mobile LiDAR (gpt-oss). We show airborne as airborne.

## What exists (reuse, do not rebuild)

| Capability | Where | State |
|---|---|---|
| Text blocks from vector strokes, OCR, survey-notation parser | `spike/blocks.py`, `spike/ocr.py`, `spike/gt.py` | 92% table values; ~1 min/sheet |
| Georeferencing: callouts, monument notes, grid ticks, one consensus solver, per-axis redundancy, vs Caltrans package | `spike/georef.py`, `spike/georef_ticks.py`, `spike/solve.py`, `spike/batch.py` | 8/11 credible, 1 weak, 2 refused |
| Sheet linework and parcels on the ground, epoch shift | `spike/overlay.py`, `spike/parcels.py`, `spike/lidar/htdp.json` | linework good; parcels 6/27 named |
| Deterministic checks and exception queue | `spike/checks.py` | exact where associated; association weak |
| Scan front end | `spike/scan_read.py`, `spike/scan_georef.py` | detects; refuses fits correctly |
| LiDAR: date, control, epoch, flightline QA, extraction, encroachment | `spike/lidar/q1..q5`, `extract.py`, `spike/encroach.py` | done; corridor faces imperfect |
| Screen | `spike/export_rasters.py`, `spike/out/QGIS_LAYERS.md` | layers ready; QGIS project not built |

## The demo (2026-10-05): smallest thing that convinces a Land Surveys champion

Story: *the record goes on the ground, deterministically, and the system says when it cannot prove
something.* Four live segments on the Presidio sheets, one slide segment for the scan.

1. Sheet in → objects out: tables and callouts read, residuals of the georeferencing fit, linework on
   the LiDAR intensity image. (exists)
2. The record checks itself: line/curve tables reconstructed as a traverse, closure per figure, drawn
   geometry vs printed numbers, exception queue with source crops. (**build: table traverse**)
3. Record against ground: parcels on LiDAR, pavement/deck/building extraction, what lies outside the
   drawn right of way, epoch shift shown before/after. (exists; needs parcels from item 2)
4. QA that catches its own mistakes: the two chance fits on the scan, refused because scale disagreed
   with the grid labels; flightline QA on someone else's point cloud. (exists; needs a page)
5. The scan, honestly: 273 boxes detected, half the coordinates readable, readers disagree, fit refused,
   the queue a surveyor would work. Slide, not live. (exists)

Cut from the demo: scan georeferencing, per-drafter generalisation beyond the Presidio set, any custom
UI, imagery, edge inference, MicroStation output.

## 13-day roadmap (2026-09-23 → 2026-10-05)

| Days | Deliverable | Proof it is done |
|---|---|---|
| 1–2 | `demo.py`: one command runs the Presidio pipeline end to end from cached artifacts (blocks → ocr → solve → overlay → parcels → checks → extract → encroach → rasters), under 3 min, offline. **Object record** `objects.geojson`: every published object (control point, line, curve, parcel, extracted feature) carries sheet, source region, printed values, check results, residuals, rule. **[consult]** QGIS project `demo.qgz` built and saved. | timed run; project opens with all layers; clicking any object in QGIS shows its provenance |
| 3–6 | **Table traverse**: parse line/curve tables (existing reads) into segments; associate the short tags (`L8`, `C16`) on the drawing to chains (short, axis-aligned tags are easy); walk each parcel boundary by tag sequence; closure per figure. Association is an assignment with uniqueness: a tag with two candidates goes to the queue **[consult]**. Curves parametrised from R/Δ/L and fitted to the strokes. Replaces heuristic association in `checks.py` for tagged segments; parcels from traverse where tags close, else from linework. | ≥ 90% of tagged segments associated or queued, none guessed; closure reported for tunnel easements 61985-1..4; their areas within 1% of the parcel table |
| 7–8 | Exception queue page: static HTML from `exceptions.json` with a rendered crop per item (reuse `checks_debug.py` rendering), grouped by cause, with a resolution field a surveyor would fill **[consult]**; the scan's queue on the same page. | page opens offline; every item has a crop and a reason; a reviewer reaches any object's citation in under a minute |
| 9–10 | LiDAR polish with the new parcels: encroachment and tunnel tie rerun, record-vs-ground numbers refreshed, one figure per segment; HTDP before/after figure. | numbers in the slides come from the run, not memory |
| 11 | Slides for the non-demo minutes (Sam), Q&A sheet (below), recorded fallback of a full run. | recording exists; run of show timed under 20 min |
| 12–13 | Two rehearsals with Sam; freeze. | second rehearsal inside 25 min with Q&A |

Parallel, no code: Sam confirms live-demo format with Caltrans; attendee names sent; ask Caltrans or any
partner for a single mobile LiDAR tile (would change segment 3's claim).

## Q&A a surveyor will bring, and the answer to have ready

- "Your 0.04 ft residual is against numbers you read off the same sheet." — Yes; independent check is
  Caltrans' own georeferenced package (~1 ft, raster-limited) and the matchline agreement between
  independently fitted sheets; scale is derived, never assumed. We claim records-research grade, not a
  survey tolerance, until the pilot sets one **[consult]**.
- "Pilot-ready in a month?" — One month to start on a defined area; three to validate against a gold set
  and a measured baseline **[consult]**.
- "What does this save?" — Hours of licensed time per sheet; the pilot's first deliverable is the measured
  manual baseline, because we will not assert savings we have not measured **[consult]**.
- "Grid or ground?" — Grid; the sheet's combined factor 1.0000704 is carried as an attribute, never
  silently applied.
- "Epoch?" — 1991.35 to 2010.0 via NGS HTDP, 0.668 m N33°W, shown before/after.
- "What is the AI doing?" — Reading text and classifying returns. Every coordinate, closure and area is
  computation from printed numbers or geometry.
- "You cannot read our old sheets." — Correct today: detection works, recognition needs a recogniser
  tuned on the district's hand; the queue is how a surveyor works it meanwhile.
- "Where is the mobile LiDAR?" — None available to us; airborne shows surfaces and footprints and the
  QA; MTLS is the pilot's data.
- "Who signs?" — Nobody; decision support under a PLS's responsible charge; no boundary opinion.

## 3-month pilot roadmap (after an invitation)

| Month | Work | Metric |
|---|---|---|
| 1 | Pilot area agreed; gold set annotated with district staff (≈50 sheets, mix of CAD and scan vintages); manual baseline timed; per-drafter adapters for the area's callout/leader styles; deployment posture decided. | baseline hours/sheet measured; adapters cover ≥ 90% of the area's CAD sheets |
| 2 | Table-traverse parcels and checks across the area; scans: grid ticks as the primary anchor with two independent anchor classes required and an uncertainty published per sheet **[consult]**; recogniser fine-tuned on the district's hand (a few hundred labelled crops) with two-reader agreement and geometry-constrained decoding; exception queue worked by one surveyor. | scan coordinate read rate ≥ 85%; ≥ 80% of scanned sheets georeference with independent scale check; queue precision (items the surveyor agrees needed review) ≥ 70% |
| 3 | MTLS track on Caltrans data (edge of pavement, monuments where visible); publication to GIS/CAD; accuracy and residuals report; scaling assessment. | residuals vs control per class; hours/sheet vs baseline; sheets escalated to full manual < 20% |

## Not seeing until now

- Caltrans' georeferenced packages make our georeferencing a check, not a product; the product is the
  object record with provenance and the checks.
- The FY2015 FHWA AID R/W map georeferencing effort (named in the submission) may have delivered
  exactly those packages; find out before the pitch so the pitch extends it rather than repeats it.
- Sam's actual SWYFT stack is still unknown to this work; the demo must be described as prototype.
- Liability and sign-off are not in the demo yet: every published object needs a status (auto-verified,
  queued, adjudicated by whom) or a surveyor will not trust the record **[consult]**. Covered by the
  object record on days 1–2.
- Pilot scaling (Docker, a state-approved tenancy) is a pilot task, not a demo task **[consult]**.

## Verification

- `python spike/demo.py` runs clean offline on the Presidio set in under 3 minutes; QGIS opens `demo.qgz`.
- Table traverse: closure and area for 61985-1..4 printed and within 1% of the parcel table; `checks.py`
  pass rate on tagged segments ≥ 90%.
- Exception page: every `exceptions.json` item has a crop; scan items present.
- Recorded fallback exists; rehearsal timed.
