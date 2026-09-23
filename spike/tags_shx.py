"""Drawing tags (L8, C16, L14(T)) straight from their SHX annotations, no glyph matching needed:
the annotation text is already the tag. Same format tags.py writes ([{tag, cx, cy, angle, score}]),
score is a constant (ground-truth text, not a bitmap match margin). Not wired into tables.py.
Output: spike/out[/<sheet>]/tags_shx.json.
usage: [SHEET=<pdf>] python spike/tags_shx.py   (after read_shx.py)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT  # noqa: E402
from overlay import FURNITURE, MAP_AREA  # noqa: E402
from tags import TAG  # noqa: E402

blocks = json.loads((OUT / "read_shx.json").read_text(encoding="utf-8"))
furniture = list(FURNITURE) + (json.loads((OUT / "tables.json").read_text(encoding="utf-8")).get("_regions", []) if (OUT / "tables.json").exists() else [])
mx0, my0, mx1, my1 = MAP_AREA
tags = []
for b in blocks:
    t = (b.get("text") or "").strip()
    if not TAG.match(t) or not (mx0 < b["cx"] < mx1 and my0 < b["cy"] < my1):
        continue
    if any(fx0 <= b["cx"] <= fx1 and fy0 <= b["cy"] <= fy1 for fx0, fy0, fx1, fy1 in furniture):
        continue  # inside a table: the record, not a tag on the drawing
    tags.append({"tag": t, "cx": b["cx"], "cy": b["cy"], "angle": b["angle"], "score": 9.9})
tags.sort(key=lambda x: (x["tag"][0], int(re.sub(r"\D", "", x["tag"]) or 0)))
(OUT / "tags_shx.json").write_text(json.dumps(tags, indent=1, ensure_ascii=False), encoding="utf-8")
old = json.loads((OUT / "tags.json").read_text(encoding="utf-8")) if (OUT / "tags.json").exists() else []
print(f"tags from annotations {len(tags)} vs tags.json {len(old)}")
