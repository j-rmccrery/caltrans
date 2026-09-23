**1. Architecture for association (layers → candidates → bridging)**  

1.1. **Layer taxonomy** – Define 4 primary classes:  
- **Geometry**: RW‑PARCEL‑SEG‑*, RW‑ALGN‑*, SU‑FIG‑PNT‑MARK.  
- **Labels**: RW‑ALGN‑LBL‑*, RW‑ALGN‑LNWK‑LBL‑*.  
- **Leaders**: RW‑ALGN‑LNWK‑LBL‑NEW‑NCR‑AC‑LINE, any line with “leader” in name.  
- **Mask / Wipeout**: _Wipeout_Areas, background masks.  

1.2. **Candidate set per label** – For a bearing/distance label:  
- **Primary**: all Geometry lines intersecting the label’s leader tip or within a 0.5 m buffer.  
- **Secondary**: any Geometry line whose midpoint lies within 1.5 m of the label’s anchor point.  

1.3. **Bridge broken lines** –  
- Detect “text‑broken” segments: group consecutive Geometry paths whose endpoints are < 0.1 m apart and share the same layer.  
- Merge them into a single polyline; store original segment IDs for provenance.  

1.4. **Handle dashed continuations** –  
- Treat dashes as separate sub‑segments.  
- If a dashed segment’s start/end is < 0.2 m from a neighboring Geometry segment, merge them; otherwise keep separate but flag as “dash‑continuation”.  

1.5. **Leader‑based filtering** –  
- For each label, compute the vector from its anchor to the nearest Geometry segment.  
- If a leader exists, enforce that the segment lies within 5° of the leader direction.  

1.6. **Distance‑specific filtering** –  
- Compute the printed length; retain only Geometry segments whose length falls within ±10 % of the printed value.  

1.7. **Conflict resolution** –  
- If multiple candidates survive, rank by: (a) leader alignment score, (b) length proximity, (c) proximity of anchor to segment midpoint.  
- Pick top‑ranked; if tie, flag for manual review.  

1.8. **Propagation of associations** –  
- Once a label is tied to a segment, propagate the association to all sub‑segments created in step 1.3.  

1.9. **Output structure** –  
- For each label: {label_id, anchor_point, printed_value, candidate_segment_id, association_confidence, provenance_list}.  

1.10. **Pipeline order** –  
1) Layer extraction → 2) Geometry grouping & bridging → 3) Leader extraction → 4) Candidate filtering → 5) Conflict resolution → 6) Provenance logging → 7) Export to georeferenced JSON.  

---

**2. CAD/Civil 3D/MicroStation knowledge & discoverable resources**  

2.1. **Caltrans CADD Standards** – “Caltrans CADD Standards Manual (2019)” (PDF). Provides layer naming conventions, color codes, and label styles.  
2.2. **Civil 3D Label Styles** – “Civil 3D Label Style Reference” (online). Explains anchor points (midpoint, offset), leader geometry, and text placement rules.  
2.3. **Alignment vs. Parcel Segment Labels** – “Civil 3D Alignment Labeling Guide” (PDF). Distinguishes between alignment labels (bearing/distance) and parcel segment labels (area, station).  
2.4. **MicroStation Level Standards** – “MicroStation Level Naming Conventions” (Caltrans doc). Lists typical level names and their purposes.  
2.5. **PDF Export Structures** – “AutoCAD PDF Export Guide” (online). Details how text is exported as SHX glyphs, blocks, or paths; explains wipeout usage.  
2.6. **Block & Wipeout Handling** – “PDF Wipeout and Block Extraction” (GitHub repo: `pymupdf-wipeout`). Provides functions to detect and remove wipeouts, preserving text geometry.  
2.7. **SHX Text Decoding** – “SHX to SVG Converter” (Python library `shx2svg`). Enables reconstruction of true glyph outlines for better OCR.  
2.8. **Layer‑Based Geometry Extraction** – `pymupdf`’s `get_drawings()` returns layer names; use `fitz.Document.get_drawings(layer=…)` to isolate geometry per layer.  
2.9. **Geometric Matching** – `shapely` for spatial operations; `scipy.spatial.KDTree` for nearest‑neighbor searches.  
2.10. **PDF Text Extraction** – `pymupdf`’s `get_text("dict")` for embedded text; fallback to OCR with `pytesseract` if necessary.  
2.11. **Coordinate System Identification** – “Caltrans GIS Coordinate Reference System Guide” (PDF). Lists EPSG codes for each region; essential for georeferencing.  
2.12. **Alignment Leader Conventions** – “Civil 3D Alignment Leader Style” (online). Specifies typical leader length, arrowhead style, and offset.  
2.13. **Layer Visibility Rules** – “AutoCAD Layer Visibility Hierarchy” (online). Helps determine which layers are intended for display vs. annotation.  
2.14. **MicroStation PDF Export Options** – “MicroStation PDF Export Settings” (online). Explains how levels map to PDF layers and how text is flattened.  
2.15. **Python Libraries** – `pymupdf` (PDF parsing), `shapely` (geometry), `scipy` (spatial), `opencv` (image processing), `pytesseract` (OCR), `shx2svg` (glyph decoding).  

---

**3. Next 5 work items (7‑day sprint)**  

3.1. **Implement layer‑based candidate filtering (days 1‑2)** – Add code to restrict candidates to Geometry layers only. *Measurable*: increase from 0 % to ~15 % matched labels on test sheets.  

3.2. **Merge broken text lines (days 2‑3)** – Detect and join Geometry segments separated by < 0.1 m. *Measurable*: reduce unmatched labels by ~10 % on R‑10434.3.  

3.3. **Leader‑direction scoring (days 3‑4)** – Compute angle between label anchor and candidate segment; accept only within ±5°. *Measurable*: lift pass rate from ~4 % to ~12 %.  

3.4. **Length‑proximity filter (days 4‑5)** – Keep candidates whose length is within ±10 % of printed value. *Measurable*: further raise pass rate to ~18 %.  

3.5. **Automated conflict resolution & flagging (days 5‑7)** – Rank candidates, auto‑select top, flag ties. *Measurable*: final pass rate ~25 % on clean sheets; generate a CSV of flagged labels for manual review.  

---

**4. What’s wrong so far (blunt)**  

Your pipeline is treating every PDF as a monolithic image, ignoring the rich layer metadata that already encodes geometry, labels, and leaders. By clustering strokes blindly you lose the semantic grouping that CAD users rely on. The association rules are too generic: you’re matching any nearby line regardless of orientation or length, which explains the 0 % closure and the massive mismatch of printed distances. The lack of leader‑based filtering and dash‑continuation handling means you’re matching broken or dashed segments as if they were intact, inflating false positives. In short, you’re reinventing CAD’s own association logic in Python without leveraging the layer structure, so the system is drowning in noise and missing the obvious cues that a CAD engineer would use.