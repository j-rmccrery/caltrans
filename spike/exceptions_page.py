"""Exception queue page: one offline HTML file, every queued item with a crop of the sheet, the reason,
the printed and drawn values, a citation (sheet + region in PDF points) and a resolution a surveyor
fills in (kept in the browser, exported as JSON). Grouped by cause. The scan's queue is on the same
page: a sheet that did not georeference and its control pairs.

Inputs: spike/out/exceptions.json (checks.py), spike/out/tags_queue.json (tables.py),
        spike/out/<scan>/georef.json + read_rapid.json (scan_georef.py)
Output: spike/out/exceptions.html
usage: python spike/exceptions_page.py
"""
import base64
import html
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, ROOT  # noqa: E402

SCAN = next(iter((ROOT / "Sample Data").rglob("r_00065_002_1969-09-01_sn-02048.pdf")), None)
Z = 2          # render scale (px per pt)
PAD = (70, 40)  # pt around the region

GROUPS = [  # (title, what a surveyor does with it)
    ("Printed value does not match the line beside it", "A dimension or bearing disagrees with the line the reader measured (blue) by a small amount. Decide which is the record."),
    ("Label with no line beside it", "The reader found the text but no line runs beside it to check against. Point to the line, or mark it as a note."),
    ("Runs to the sheet edge", "The line leaves this sheet at a matchline; the check needs the adjoining sheet."),
    ("Segment tag partly unread", "A table tag (L8, C16) on the drawing has a character the reader could not settle. Read it by eye."),
    ("Segment tag: no single line to check", "The tag's leader points at nothing, or two lines sit beside it. Point to the line."),
    ("Segment tag: drawn segment disagrees with the table", "The line the tag's leader points at differs from the table row."),
    ("Scan: not georeferenced", "The 1969 scan's coordinate callouts did not agree well enough for a fit. Each control pair below needs a reading by eye."),
    ("Reader measured a different line", "The disagreement is far too large for a drafting error: the line the reader picked (blue) is not the one the label describes. Point to the right line; the value itself is not in question yet."),
]
SMALL = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0}  # ft, ft, arcmin: beyond this it is the wrong line, not the wrong number


def crop(page, region, line=None):
    """Sheet around the region (red box); the drawn line or arc the check measured in blue, if any."""
    x0, y0, x1, y1 = region
    if line:  # widen so the measured line is in view (capped: a 1500 ft line does not fit)
        lx, ly = zip(*line)
        x0, y0, x1, y1 = max(x0 - 120, min(lx)), max(y0 - 70, min(ly)), min(x1 + 120, max(lx)), min(y1 + 70, max(ly))
        x0, y0, x1, y1 = min(x0, region[0]), min(y0, region[1]), max(x1, region[2]), max(y1, region[3])
    R = pymupdf.Rect(x0 - PAD[0], y0 - PAD[1], x1 + PAD[0], y1 + PAD[1]) & page.rect
    z = min(Z, 900 / max(R.width, 1))  # a whole-sheet overview stays under 900 px wide
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    if line:
        cv2.polylines(im, [np.array([f(x, y) for x, y in line], np.int32)], False, (0, 90, 220), 3)
    cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (220, 0, 0), 2)
    ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(im, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(jpg.tobytes()).decode()


def sheet_items():
    page = pymupdf.open(PDF)[0]
    items = []
    for e in json.loads((OUT / "exceptions.json").read_text(encoding="utf-8")):
        issue = e.get("issue", "")
        off = abs(e.get("off_ft", e.get("off_arcmin", 0)))
        if "sheet edge" in issue:
            g = 2
        elif "no line" in issue:
            g = 1
        elif off > SMALL.get(e["kind"], 1e9):
            g = 7
        else:
            g = 0
        drawn = e.get("drawn") or (f"{e['drawn_ft']:.2f} ft" if "drawn_ft" in e else "") or (f"L = R·Δ = {e['calc_L']:.2f}" if "calc_L" in e else "")
        diff = (f"{e['off_ft']:+.2f} ft" if "off_ft" in e else "") or (f"{e['off_arcmin']:+.1f}′" if "off_arcmin" in e else "")
        items.append({"group": g, "kind": e["kind"], "printed": e["text"], "drawn": drawn, "diff": diff, "reason": issue or f"{e['kind']}: off by {diff}",
                      "sheet": PDF.stem, "region": e["region"], "png": crop(page, e["region"], e.get("line"))})
    for q in json.loads((OUT / "tags_queue.json").read_text(encoding="utf-8")):
        g = 3 if "unread" in q["issue"] else 5 if " vs table " in q["issue"] or "off by" in q["issue"] else 4
        items.append({"group": g, "kind": "tag " + q["tag"], "printed": q["tag"], "drawn": "", "diff": "", "reason": q["issue"],
                      "sheet": PDF.stem, "region": q["region"], "png": crop(page, q["region"], q.get("line"))})
    return items


def scan_items():
    if SCAN is None:
        return []
    out = OUT / SCAN.stem
    if not (out / "georef.json").exists():
        return []
    g = json.loads((out / "georef.json").read_text(encoding="utf-8"))
    if g.get("credible"):
        return []
    page = pymupdf.open(SCAN)[0]
    reads = json.loads((out / "read_rapid.json").read_text(encoding="utf-8"))
    items = [{"group": 6, "kind": "sheet", "printed": "", "drawn": f"scale {g['scale_ft_per_pt']:.3f} ft/pt, rotation {g['rotation_deg']:.2f}°",
              "diff": "", "reason": f"fit not credible: {sum(c['used'] for c in g['control'])} agreeing pairs of {len(g['control'])}; scale must also match the grid labels",
              "sheet": SCAN.stem, "region": [int(page.rect.width * 0.3), int(page.rect.height * 0.3), int(page.rect.width * 0.7), int(page.rect.height * 0.7)],
              "png": crop(page, [int(page.rect.width * 0.3), int(page.rect.height * 0.3), int(page.rect.width * 0.7), int(page.rect.height * 0.7)])}]
    for c in g["control"]:
        # the callout's own text blocks give the region: the label is "N... / E..." from two reads
        parts = [p.strip() for p in c["label"].split("/")]
        hits = [b for b in reads if any(p and p in b["text"] for p in parts)]
        if hits:
            xs = [b["cx"] for b in hits]; ys = [b["cy"] for b in hits]
            region = [int(min(xs) - 30), int(min(ys) - 12), int(max(xs) + 30), int(max(ys) + 12)]
        else:
            region = [0, 0, 60, 30]
        items.append({"group": 6, "kind": "control pair", "printed": c["label"], "drawn": f"N {c['N']:,.2f}  E {c['E']:,.2f}",
                      "diff": f"residual {c['residual_ft']:.2f} ft", "reason": "used in the fit" if c["used"] else "rejected: residual over tolerance",
                      "sheet": SCAN.stem, "region": region, "png": crop(page, region)})
    return items


def render(items):
    esc = html.escape
    parts = []
    for gi, (title, what) in enumerate(GROUPS):
        rows = [it for it in items if it["group"] == gi]
        if not rows:
            continue
        cards = []
        for k, it in enumerate(rows):
            iid = f"g{gi}-{k}"
            vals = " · ".join(esc(v) for v in (f"printed {it['printed']}" if it["printed"] else "", f"drawn {it['drawn']}" if it["drawn"] else "", it["diff"]) if v)
            cards.append(f"""
<div class="card" id="{iid}">
  <img src="data:image/jpeg;base64,{it['png']}" alt="crop">
  <div class="body">
    <div class="kind">{esc(it['kind'])}</div>
    <div class="reason">{esc(it['reason'])}</div>
    <div class="vals">{vals}</div>
    <div class="cite">{esc(it['sheet'])} · region {', '.join(str(v) for v in it['region'])} pt</div>
    <div class="res">
      <select data-id="{iid}"><option value="">— resolution —</option><option>drawing is right</option><option>record is right</option><option>needs field check</option><option>not an error (note, total, off-sheet)</option><option>drafting error, report</option></select>
      <input data-id="{iid}" placeholder="initials / note">
    </div>
  </div>
</div>""")
        parts.append(f"<details open><summary>{esc(title)} <span class='n'>{len(rows)}</span><div class='what'>{esc(what)}</div></summary><div class='grid'>{''.join(cards)}</div></details>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Exception queue</title>
<style>
body{{font:14px/1.4 system-ui,sans-serif;margin:0;background:#f6f6f4;color:#222}}
header{{background:#1d2a3a;color:#fff;padding:14px 20px;display:flex;gap:24px;align-items:baseline}}
header h1{{font-size:18px;margin:0}} header button{{margin-left:auto;background:#fff;border:0;padding:6px 12px;border-radius:4px;cursor:pointer}}
details{{margin:12px 20px;background:#fff;border:1px solid #ddd;border-radius:6px}} summary{{padding:10px 14px;font-weight:600;cursor:pointer}}
.n{{background:#c33;color:#fff;border-radius:10px;padding:0 8px;font-size:12px;margin-left:6px}} .what{{font-weight:400;color:#555;font-size:13px;margin-top:2px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:12px;padding:0 14px 14px}}
.card{{border:1px solid #e3e3e3;border-radius:6px;overflow:hidden;background:#fafafa}} .card.done{{background:#eef7ee}}
.card img{{width:100%;display:block;border-bottom:1px solid #e3e3e3}} .body{{padding:8px 10px}}
.kind{{font-weight:600}} .reason{{color:#a22}} .vals{{color:#333;font-family:ui-monospace,monospace;font-size:13px}} .cite{{color:#777;font-size:12px}}
.res{{display:flex;gap:6px;margin-top:6px}} .res select{{flex:1}} .res input{{flex:1}}
</style></head><body>
<header><h1>Exception queue</h1><span>{len(items)} items · {sum(1 for i in items if i['sheet'] == PDF.stem)} on {esc(PDF.stem)}</span><button onclick="exportRes()">Export resolutions</button></header>
{''.join(parts)}
<script>
const K='exceptions-'+document.title;let R=JSON.parse(localStorage.getItem(K)||'{{}}');
document.querySelectorAll('[data-id]').forEach(el=>{{const id=el.dataset.id,f=el.tagName==='SELECT'?'r':'note';if(R[id]&&R[id][f])el.value=R[id][f];
 el.addEventListener('change',()=>{{R[id]=R[id]||{{}};R[id][f]=el.value;localStorage.setItem(K,JSON.stringify(R));document.getElementById(id).classList.toggle('done',!!(R[id].r));}});
 if(R[id]&&R[id].r)document.getElementById(id).classList.add('done');}});
function exportRes(){{const a=document.createElement('a');a.href='data:application/json,'+encodeURIComponent(JSON.stringify(R,null,1));a.download='resolutions.json';a.click();}}
</script></body></html>"""


def main():
    items = sheet_items() + scan_items()
    (OUT / "exceptions.html").write_text(render(items), encoding="utf-8")
    counts = {GROUPS[g][0]: sum(1 for i in items if i["group"] == g) for g in range(len(GROUPS))}
    print(f"exceptions.html: {len(items)} items, {(OUT / 'exceptions.html').stat().st_size / 1e6:.1f} MB")
    for k, v in counts.items():
        if v:
            print(f"  {v:4}  {k}")
    assert all(i["png"] and i["reason"] for i in items), "an item without a crop or a reason"


if __name__ == "__main__":
    main()
