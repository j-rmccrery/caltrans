"""Loop18 leg 5, lever 2 gate evidence: crop every curve edge that attach_nearby_curve_R() completes --
the candidate arc (blue) and the printed R=/delta stack it took R/delta from (red X + text), same sheet.
usage: SHEET=<pdf> python spike/leg185_lever2_crops.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from leg4_crops import tile  # noqa: E402
import traverse as tv  # noqa: E402
from recon import OUT_RECON  # noqa: E402


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    scale = g["scale_ft_per_pt"]

    def ground(p):
        sx, sy = p[0], -p[1]
        return np.array([a * sx - b * sy + tx, b * sx + a * sy + ty])

    edges = tv.build_edges()
    curve_data = tv.load_curve_data()
    n = tv.attach_nearby_curve_R(edges, curve_data, scale)
    print(f"{n} curve edge(s) completed by attach_nearby_curve_R")

    def ground_to_pt(gp):
        # invert ground(): gp = a*sx - b*sy + tx, b*sx + a*sy + ty ; solve for sx,sy then flip y
        det = a * a + b * b
        ex, ny = gp[0] - tx, gp[1] - ty
        sx = (a * ex + b * ny) / det
        sy = (-b * ex + a * ny) / det
        return np.array([sx, -sy])

    OUT_RECON.mkdir(parents=True, exist_ok=True)
    stem = PDF.stem
    for e in edges:
        if e["kind"] != "arc" or "R_source" not in e or "nearby curve-data stack" not in e["R_source"]:
            continue
        cx0, cy0 = e["p0"]; cx1, cy1 = e["p1"]
        region = [min(cx0, cx1) - 10, min(cy0, cy1) - 10, max(cx0, cx1) + 10, max(cy0, cy1) + 10]
        stack = next(s for s in curve_data if e["R_source"].startswith(f"nearby curve-data stack R={s['R']}'"))
        stack_pt = np.array([stack["cx"], stack["cy"]])
        widen = [min(region[0], stack_pt[0] - 10), min(region[1], stack_pt[1] - 10),
                 max(region[2], stack_pt[0] + 10), max(region[3], stack_pt[1] + 10)]
        im = tile(page, region, [e["p0"].tolist(), e["p1"].tolist()])
        # re-render at the widened region directly (tile()'s own line-widen caps at 90/60 pt, plenty here)
        R = pymupdf.Rect(widen[0] - 20, widen[1] - 20, widen[2] + 20, widen[3] + 20) & page.rect
        z = min(3, 500 / max(R.width, R.height, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
        im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
        cv2.polylines(im, [np.array([f(x, y) for x, y in e["pts"]], np.int32)], False, (0, 90, 220), 3)
        sx, sy = f(*stack_pt)
        cv2.drawMarker(im, (sx, sy), (220, 0, 0), cv2.MARKER_TILTED_CROSS, 24, 3)
        drawn_chord = float(np.hypot(*(e["p1"] - e["p0"]))) * scale
        import math
        delta_check = math.degrees(e["L"] / stack["R"])
        chord_check = 2 * stack["R"] * math.sin(math.radians(delta_check) / 2)
        delta_stack_txt = f"{stack['delta']:.4f}" if stack.get("delta") is not None else "none printed/legible"
        label = f"L={e['L']:.2f}' -> R={stack['R']}' delta_stack={delta_stack_txt} delta_calc={delta_check:.4f} chord_calc={chord_check:.2f} drawn_chord={drawn_chord:.2f}"
        cv2.putText(im, label, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        safe = e["src"].replace("'", "").replace(" ", "_").replace("=", "").replace(".", "_")[:40]
        out_path = OUT_RECON / f"l18_5_lever2_{stem}_{safe}.png"
        cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
        print("wrote", out_path)


if __name__ == "__main__":
    main()
