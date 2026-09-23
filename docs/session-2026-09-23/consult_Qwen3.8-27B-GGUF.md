1. **Architecture for Association**

   **Layer Class Definitions:**
   *   **Geometry Layers:** `RW-PARCEL-SEG-*`, `RW-ALGN-LNWK-*`, `32 New RW L`, `33 New RW A`. These contain the physical lines.
   *   **Label Layers:** `RW-ALGN-LBL-*`, `SU-FIG-PNT-MARK`, `49 Points-Plot`. These contain the text and leader lines.
   *   **Context Layers:** `1 Control`, `110_Sheet_Format`. Ignore for geometry association; use only for sheet boundary cropping.
   *   **Wipeout/Mask Layers:** `_Wipeout_Areas`. Critical for bridging.

   **Order of Operations:**

   1.  **Ingest & Classify:** Parse PDF. Extract all paths. Map each path to its layer name. Separate into `GeoPaths` (polyline/line primitives on Geometry Layers) and `LblPaths` (text/leaders on Label Layers).
   2.  **Reconstruct Geometry (Bridging):**
       *   **Wipeout Bridging:** Wipeouts are rectangles or polygons on `_Wipeout_Areas` that obscure lines to allow text placement. Do not treat them as gaps. Instead, for any two `GeoPath` endpoints on the same logical chain (determined by proximity and angle continuity) that are separated by a Wipeout polygon, assume a straight-line connection.
       *   **Dashed Continuation:** Dashed lines are sequences of short segments. Merge segments on the same layer if the gap is less than a threshold (e.g., 2x line width) and the angle deviation is < 5 degrees. This reconstructs the full "virtual" line.
       *   **Result:** A set of `ReconstructedChains`. Each chain is a list of vertices. Store the original layer ID for each segment.
   3.  **Label Parsing & Anchoring:**
       *   Extract text blocks from `LblPaths`.
       *   Identify leader lines (short paths on Label Layers connecting text to geometry).
       *   If a leader exists, the target is the endpoint of the leader.
       *   If no leader, the target is the centroid of the text block.
   4.  **Candidate Generation (Layer-Filtered):**
       *   For each label, find all `ReconstructedChains` on Geometry Layers.
       *   **Filter 1 (Proximity):** Distance from label anchor to chain < 50 units (adjustable).
       *   **Filter 2 (Layer Semantics):**
           *   If label is "Parcel Segment" (detected via nearby table tag or layer context), prioritize `RW-PARCEL-SEG-*`.
           *   If label is "Alignment" (bearing/distance format), prioritize `RW-ALGN-LNWK-*`.
           *   *Crucial:* Do not hardcode. Use the layer name prefix to weight candidates.
   5.  **Assignment (Hungarian Algorithm):**
       *   Create a cost matrix: Rows = Labels, Cols = Candidate Chains.
       *   Cost = Geometric Distance + Layer Mismatch Penalty + Length Mismatch Penalty.
       *   Solve for minimum cost assignment. This ensures 1-to-1 mapping and resolves ambiguity better than greedy nearest-neighbor.
   6.  **Validation & Queue:**
       *   Compare printed distance/bearing to calculated chain properties.
       *   If mismatch > tolerance, flag for surveyor queue.
       *   If match, record provenance: `Label_ID -> Chain_ID -> Original_PDF_Path_IDs`.

2. **Missing Domain Knowledge & Resources**

   *   **Caltrans CADD Standards (CADD Manual):**
       *   *Document:* Caltrans CADD Standards Manual (latest version, e.g., 2024).
       *   *Value:* Defines exact layer naming conventions (e.g., `RW-ALGN-LNWK-NEW-NR` means Right-of-Way, Alignment, Line-Work, New, No Reference). It defines which layers contain "true" geometry vs. "plot" geometry. It specifies that **Parcel Segments** are distinct from **Alignment Segments**. Parcel segments are legal boundaries; alignment segments are design curves. They often overlap but are different objects.
       *   *Action:* Download the PDF. Extract the layer dictionary. Map your observed layer names to their semantic definitions.
   *   **Civil 3D Label Styles & Anchor Points:**
       *   *Knowledge:* Civil 3D labels are not just text; they are dynamic objects. A "Bearing/Distance" label on an alignment segment is anchored to the **midpoint** of the segment by default, but can be offset. The leader line (if present) points to the **midpoint** or a **specific offset**.
       *   *Implication:* Your "nearest parallel line" heuristic is weak. The label is geometrically tied to the *midpoint* of the specific segment. If you reconstruct the chain, calculate the midpoint of each sub-segment. The label should be near the midpoint of the *entire* chain if it's a single segment, or near the junction if it's a compound.
       *   *Resource:* Autodesk Civil 3D Documentation -> "Label Styles".
   *   **MicroStation Levels vs. CAD Layers:**
       *   *Knowledge:* MicroStation uses "Levels". In older versions, levels are global; in newer, they are per-element. The PDF export flattens this into "Layers" or "Groups".
       *   *Implication:* The layer names in MicroStation PDFs might be less semantic than Civil 3D. "Level 32" might be "New Right of Way Line" in one sheet and "Existing Utility" in another. You must rely on **visual inspection** of a few sheets to build a local dictionary for MicroStation sheets.
   *   **PDF Export Structure (SHX/TrueType):**
       *   *Knowledge:* AutoCAD exports SHX (shape) fonts as vector paths (strokes). TrueType fonts are often embedded as Type 3 or Type 1.
       *   *Implication:* Your glyph matching is correct for SHX. For TrueType, `pymupdf` can extract text directly if the font is embedded. Check `page.get_text("dict")` for `chars` with `font` info. If `font` is "Times New Roman" or similar, use OCR or direct text extraction. If it's a custom SHX, use your glyph matcher.
   *   **Wipeout Semantics:**
       *   *Knowledge:* Wipeouts are *not* geometry. They are rendering instructions to hide background.
       *   *Implication:* Your current pipeline likely treats wipeout boundaries as line breaks. This is the primary cause of "broken chains." You must explicitly bridge across wipeouts.
   *   **Tools/Libraries:**
       *   `pymupdf`: Already using. Use `page.get_drawings()` for paths/layers.
       *   `shapely`: For spatial indexing (STRtree) to speed up candidate search.
       *   `scipy.optimize`: For Hungarian algorithm (`linear_sum_assignment`).
       *   `opencv`: For image-based fallback if vector data is corrupted.
       *   *New:* `ezdxf` (if you ever get DWG, but you don't). `pdfplumber` (alternative to pymupdf, sometimes better at text).

3. **Ranked Work Items (Next 7 Days)**

   1.  **Implement Wipeout Bridging & Dashed Line Merging.**
       *   *Task:* Modify geometry reconstruction to treat `_Wipeout_Areas` as transparent and merge dashed segments.
       *   *Measurable:* % of `ReconstructedChains` that are continuous (no gaps > 10 units). Target: >95% of visible lines.
       *   *Expected Effect:* +15-20% distance pass rate. This fixes the "broken line" issue directly.
   2.  **Implement Layer-Filtered Candidate Generation.**
       *   *Task:* Use layer names to filter candidate chains. Create a mapping: `RW-PARCEL-SEG-*` -> Parcel Labels, `RW-ALGN-LNWK-*` -> Alignment Labels.
       *   *Measurable:* Reduction in false positives (labels matched to wrong layer). Target: <5% cross-layer matches.
       *   *Expected Effect:* +5-10% accuracy. Reduces noise in assignment.
   3.  **Switch to Hungarian Algorithm for Assignment.**
       *   *Task:* Replace greedy nearest-neighbor with `scipy.optimize.linear_sum_assignment`. Cost function: `dist(label, chain_midpoint) + layer_penalty + length_penalty`.
       *   *Measurable:* Improvement in "1-to-1" matching. Target: 0 labels matched to same chain.
       *   *Expected Effect:* +5% pass rate. Resolves ambiguity where two labels are close.
   4.  **Refine Label Parsing for Stationing vs. Distance.**
       *   *Task:* Add regex to distinguish `65+48.80` (station) from `498.58` (distance). Station labels should not be matched to line lengths.
       *   *Measurable:* % of station labels correctly excluded from distance checks. Target: 100%.
       *   *Expected Effect:* +3-5% pass rate. Removes false failures.
   5.  **Build MicroStation Layer Dictionary.**
       *   *Task:* Manually inspect 3 MicroStation sheets. Map "Level 32", "Level 33", etc., to semantic types (Parcel, Alignment, Existing).
       *   *Measurable:* Coverage of MicroStation sheets with correct layer mapping. Target: 100% of 17 sheets.
       *   *Expected Effect:* +5% pass rate on MicroStation sheets. Enables layer filtering for these sheets.

4. **What is Wrong**

   You are treating the PDF as a flat vector drawing instead of a structured CAD export. The core failure is **ignoring the layer hierarchy** and **misinterpreting wipeouts as geometry breaks**. By not bridging wipeouts, you fragment continuous lines, causing the "no drawn chain of printed length" error. By not using layer semantics, you allow labels to match irrelevant geometry (e.g., a parcel label matching an alignment line). Your "nearest parallel line" heuristic is too weak for dense drawings. The solution is not better OCR or better glyph matching; it is **better geometric reconstruction** (bridging gaps) and **semantic filtering** (using layers to constrain candidates). You are solving a computer vision problem when you should be solving a CAD data interpretation problem.