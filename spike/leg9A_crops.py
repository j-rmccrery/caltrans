"""Loop9 leg A gate evidence: spike/out/leg9A_runs.png, three panels on Presidio --
  C21: the stitched parent (rule 1) in blue, the window matched against the printed L in a thicker blue.
  C20: the dash-dot train (rule 2) that resolved to C20's tag, in blue.
  C15: the consecutive-row run (rule 3, C15+C16+C18) in blue.
Tags in red, drawn/printed sums in each panel's caption. Ad hoc, not part of the pipeline.
usage: python spike/leg9A_crops.py -> spike/out/leg9A_runs.png
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import checks  # noqa: E402
from checks import parent_window, poly_dist, tag_leaders  # noqa: E402
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402
from tables import row_run, table_rows  # noqa: E402

Z = 300 / 72
PAD = 90


def tag_pos(tags, tag):
    t = next(x for x in tags if x["tag"] == tag)
    return t, np.array([t["cx"], t["cy"]])


def render_panel(page, region, blue_pieces, thick_pieces, tag_box, caption, out_path):
    xs = [region[0], region[2]] + [p[0] for pc in blue_pieces for p in pc]
    ys = [region[1], region[3]] + [p[1] for pc in blue_pieces for p in pc]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 1300 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for pc in blue_pieces:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pc], np.int32)], False, (200, 130, 60), 3)
    for pc in thick_pieces:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pc], np.int32)], False, (0, 60, 230), 6)
    x0, y0, x1, y1 = tag_box
    cv2.rectangle(im, f(x0, y0), f(x1, y1), (0, 0, 220), 3)
    im = cv2.copyMakeBorder(im, 0, 46, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, caption, (10, im.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    return im


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    checks.set_decimals(blocks)
    pool = checks.build_pool(page, blocks)
    arcs, paths = pool["arcs"], pool["paths"]
    rows = table_rows()
    tags = json.loads((OUT / "tags.json").read_text(encoding="utf-8"))
    tips = tag_leaders(tags, paths)
    out_dir = OUT
    panels = []

    # tag_by_num: every curve tag's own nearest-piece resolution (main()'s simple case: no ambiguity for
    # any tag in this region, verified against tables.py's own leg8A/leg9A run) -- shared by all three
    # panels below and by row_run(), so a crop never drifts from what tables.py itself measured.
    import re as _re
    tag_by_num = {}
    for i, x in enumerate(tags):
        m = _re.match(r"([LC])(\d+)$", x["tag"])
        if not m or m[1] != "C" or x["tag"].replace("(T)", "") not in rows:
            continue
        tip = tips[i][0] if i in tips else np.array([x["cx"], x["cy"]])
        seg = min((a for a in arcs if "seq" in a), key=lambda a: poly_dist(tip, a["pts"]))
        tag_by_num[int(m[2])] = (x, rows[x["tag"]], seg, "leader", None)

    # --- C21: stitched parent (rule 1) ---
    t21, p21 = tag_pos(tags, "C21")
    seed21 = tag_by_num[21][2]
    parent21 = seed21["parent"]
    sibs21 = sorted((x for x in arcs if x.get("parent") == parent21 and "seq" in x), key=lambda x: x["seq"])
    row21 = rows["C21"]
    window21 = parent_window(arcs, seed21, row21["L"], scale)
    region21 = [t21["cx"] - 2 * t21["gh"], t21["cy"] - t21["gh"], t21["cx"] + 2 * t21["gh"], t21["cy"] + t21["gh"]]
    n_paths_str = f"{len(sibs21)} piece(s) on this one stitched parent" if window21 is None else f"window of {len(window21)}"
    if window21 is not None:
        drawn = sum(x["len_pt"] for x in window21) * scale
        verdict = "pass" if abs(drawn - row21['L']) <= checks.DIST_TOL + 0.0005 * row21['L'] else "FAIL"
        cap = f"C21: R={row21['R']}' L={row21['L']}' -- {n_paths_str} sums {drawn:.2f} ({verdict}): blue is the record curve"
        thick = [window21[0]["pts"]] if len(window21) == 1 else [np.concatenate([x["pts"] for x in window21])]
    else:
        drawn = sum(x["len_pt"] for x in sibs21) * scale
        cap = f"C21: R={row21['R']}' L={row21['L']}' -- no window sums to L; whole stitched parent ({len(sibs21)} pieces) = {drawn:.2f} ft: still short -- blue is A record curve here, not the full one"
        thick = [seed21["pts"]]
    panels.append(("C21_stitched_parent", region21, [x["pts"] for x in sibs21], thick, cap))

    # --- C20: dash-dot train (rule 2) ---
    t20, p20 = tag_pos(tags, "C20")
    seed20 = tag_by_num[20][2]
    parent20 = seed20["parent"]
    sibs20 = sorted((x for x in arcs if x.get("parent") == parent20 and "seq" in x), key=lambda x: x["seq"])
    row20 = rows["C20"]
    drawn20 = seed20["len_pt"] * scale
    region20 = [t20["cx"] - 2 * t20["gh"], t20["cy"] - t20["gh"], t20["cx"] + 2 * t20["gh"], t20["cy"] + t20["gh"]]
    cap20 = f"C20: R={row20['R']}' L={row20['L']}' -- dash-dot train piece resolved = {drawn20:.2f} ft (FAIL, wrong piece of the alignment pattern): blue is NOT the record curve here"
    panels.append(("C20_dashdot_train", region20, [x["pts"] for x in sibs20], [seed20["pts"]], cap20))

    # --- C15: consecutive-row run (rule 3) -- the real row_run(), same call main() makes ---
    t15, p15 = tag_pos(tags, "C15")
    seed15 = tag_by_num[15][2]
    parent15 = seed15["parent"]
    rr = row_run("C15", seed15, rows, tag_by_num, arcs, scale)
    keys, untagged, drawn15, Ls, total15, by_sum15, span = rr
    verdict15 = "pass" if by_sum15 else "FAIL"
    region15 = [t15["cx"] - 2 * t15["gh"], t15["cy"] - t15["gh"], t15["cx"] + 2 * t15["gh"], t15["cy"] + t15["gh"]]
    cap15 = f"C15: run of {', '.join(keys)} ({', '.join(untagged)} untagged) = {drawn15:.2f} vs {total15:.2f} ({verdict15}): blue is the record run, boundary not drawn"
    sibs15 = sorted((x for x in arcs if x.get("parent") == parent15 and "seq" in x), key=lambda x: x["seq"])
    panels.append(("C15_row_run", region15, [x["pts"] for x in sibs15], [x["pts"] for x in span], cap15))

    ims = []
    for name, region, blue, thick, cap in panels:
        im = render_panel(page, region, blue, thick, region, cap, out_dir / f"leg9A_{name}.png")
        ims.append(im)
        print(cap)
    h = max(im.shape[0] for im in ims)
    ims = [cv2.copyMakeBorder(im, 0, h - im.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for im in ims]
    combined = np.concatenate(ims, axis=1)
    cv2.imwrite(str(out_dir / "leg9A_runs.png"), cv2.cvtColor(combined, cv2.COLOR_RGB2BGR))
    print("wrote", out_dir / "leg9A_runs.png")


if __name__ == "__main__":
    main()
