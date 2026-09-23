# Session artifacts, 2026-09-23

Kept from the session that found the CAD structure in the PDFs and ran the overnight Presidio loop
(`spike/LOOP.md`, `spike/out/loop_report.md`).

- `consult_brief.md`, `consult_gpt-oss.md`, `consult_Qwen3.8-27B-GGUF.md`: the brief given to the two local
  models (Ollama) and their answers; notes on what was used are in `spike/LOOP.md`.
- `diag.py`, `attrib.py`, `crops.py`: the association diagnostics that measured the four ideas (candidate
  existence, attribution of unmatched labels to noise / cut / angle / none, crop rendering). They import from
  `spike/` and take the `SHEET` env like the pipeline.
- `crops_presidio.png`, `crops_r105.png`: unmatched distance labels with their candidate lines, before the loop.
- `scans_0..3.png`: one ink-dense crop of each of the 48 scans, the by-eye lettering census
  (hand ~22, Leroy ~10, CAD plots ~11, unjudged ~5).
