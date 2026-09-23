You are consulted as a senior engineer with land-surveying, CAD (AutoCAD Civil 3D, MicroStation) and document-engineering experience. Answer tersely, numbered, no preamble. Budget: about 1200 words. Rank, do not survey.

## Project
Caltrans right-of-way record maps (PDF, one sheet each) + airborne LiDAR -> a georeferenced object record with provenance, where every printed value is checked against the drawing and unproven items go to a surveyor's queue. Demo on 2026-10-05. Python only (pymupdf, numpy, scipy, shapely, opencv). No CAD software available. No DWG/DGN source files, only the PDFs.

## Pipeline today
1. Text: vector sheets have stroked CAD glyphs (each character is small paths). We cluster strokes into text blocks, learn the sheet's own alphabet from its line/curve tables (NO. column L1,L2,... is known), read every block by glyph matching. Some sheets have real PDF text (MicroStation, Times). 101/101 table cells exact on the main sheet.
2. Georeference: coordinate callouts (N/E with leaders), grid tick labels, monument notes -> one similarity solve. 7 of 17 vector sheets credible; the 10 refused are other drafters' fonts the alphabet does not read.
3. Association: each bearing/distance label must find the drawn line it describes. Rule today: leader arrowhead if present, else nearest parallel line beside the label; a straight run is cut at circles/junctions/crossings and the printed distance picks a span of pieces.
4. Checks: printed vs drawn (bearing, distance, L=R*delta). Traverse: edges chain by shared endpoints; closure where a chain returns. 0 figures close.
5. LiDAR: pavement/deck/building extraction by rule; record vs ground. Fine; blocked on parcels from (3).

## Measured (four sheets: Presidio R-10434.2 Civil 3D; sibling R-10434.3; R-105.14 and R-17x.1 MicroStation with real text)
- Distance label checks pass: 17/39, 26/95, 37/62, 40/73. Bearings: 16/31, 15/43, 46/62, 21/38.
- We tried: (1) printed bearing filters candidate lines: +1..2 bearings, 0 distances. (2) uniqueness/assignment: headroom 1-2 labels per sheet. (3) table-order adjacency for tags: 0. (4) closure feedback: 0 figures close, no headroom. Combined ceiling: +2..6 passes per sheet (4-10 % relative).
- Attribution of the unmatched labels: 27-29 per clean sheet (84 on R-10434.3) have NO drawn chain of the printed length near the label at all. Causes seen in crops: line broken for on-line text (station numbers, labels written on the line); solid line continues as dashes to the vertex (486.82 ft solid + dashes = 498.58 printed); stationing ticks and crossings cut runs into pieces where several spans match; tokens that are not distances (stationing 65+48.80, R=60.00).
- Tags (L8, C16 on drawing -> table row): using the row's own bearing/length/radius to pick among ambiguous candidate lines raised associated 18 -> 22 of 40, all passes.

## Just discovered (not used anywhere yet)
13 of 17 vector PDFs carry optional content groups = CAD layers, and every path in the PDF carries its layer name (pymupdf get_drawings()[i]["layer"]). Civil 3D sheets: RW-PARCEL-SEG-Directors_Deeds, RW-PARCEL-SEG-REACQUISITION, rw_EASE_EXIST_align, RW-ALGN-LNWK-EXIST-XA, RW-ALGN-LBL-NEW-NR (labels), RW-ALGN-LNWK-LBL-NEW-NCR-AC-Line (label leader lines), SU-FIG-PNT-MARK (point marks), _Wipeout_Areas (text background masks), 110_Sheet_Format (border/title), RW-SHEET-TBL (tables). MicroStation sheets: levels named '1 Control', '32 New RW L', '33 New RW A', '44 Relinquishmt', '49 Points-Plot', 'Level 31', 'Level 60'. Two sheets: no layers (flattened or Distiller).

## Questions
1. Given the layers, what is the right architecture for association? Concretely: which layer classes should define the candidate set for a label, how to bridge lines broken for text/wipeouts, and how to treat dashed continuations. Give the order of operations.
2. What CAD / Civil 3D / MicroStation domain knowledge or conventions are we missing that a CAD person would know and that are discoverable online: Caltrans CADD standards (layer/level naming), Civil 3D label styles (how a bearing/distance label anchors to its segment: midpoint, offset, leader), Civil 3D parcel segment labels vs alignment labels, MicroStation level standards, how AutoCAD/MicroStation PDF export structures paths (blocks, wipeouts, SHX text), anything else. Name specific documents, tools, libraries (Python preferred) and what each would give us.
3. Rank the next 5 work items for the next 7 days with an expected effect on the distance pass rate. Be specific about what is measurable.
4. What is wrong with the approach so far. One paragraph, blunt.
