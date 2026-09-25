"""Loop 7 leg A: one hand, one alphabet -- for the scan.

Segment every detected box on R-65.2 into glyph images (connected components on a levelled,
binarised crop), normalise each to a 24x24 bitmap the same way alphabet.py's vector bitmap()
does (scale to a fixed cap height, centre, blur -- tags.PX=24/tags.CAP=18, reused verbatim as
constants; the rendering itself is reimplemented for raster since there are no strokes to draw,
only a pixel mask to resize), then cluster by bitmap distance so one label per cluster can read
the sheet (leg B).

usage: python spike/scan_alphabet.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

sys.path.insert(0, str(Path(__file__).parent))
from gt_scan import TRUTH  # noqa: E402
from scan_readers import OUT, PDF  # noqa: E402

PX, CAP = 24, 18.0       # same canvas as tags.bitmap(): glyph height -> CAP px, centred in PX x PX
SMALL_FRAC = 0.5         # a component under this * the box's tallest component is a small mark
MIN_AREA = 30            # px^2 in the 2x-upscaled crop; below this a component is grain / a hachure sliver
FRAME_FRAC = 0.85        # a component this wide or tall relative to the crop is a bubble border / table rule, not a glyph
EDGE_PX = 2              # a component touching the crop edge is a clipped frame arc or a bled-in neighbour, not a glyph
CAP_THRESH = 6.0         # agglomerative cut, cap-height glyphs (picked here: purity holds at 88/gate 70, cuts cluster count vs 5.5)
SMALL_THRESH = 4.0        # agglomerative cut, small marks (picked here: purity 84 vs gate 70, cuts cluster count vs 3.0)


# ---------- render + crop ----------

def page_img():
    cache = OUT / "page300.png"
    if cache.exists():
        return cv2.imread(str(cache), cv2.IMREAD_GRAYSCALE)
    page = pymupdf.open(PDF)[0]
    z = 300 / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16)).apply(img)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(cache), img)
    return img


def crop_level(img, b, upscale=2):
    """Rotate the box upright about its centre and crop with a margin -- same ratios as
    scan_readers.crop_of ("tight: the neighbouring line must not come along"; a looser margin
    was tried first and pulled in the row above/below on this densely-stacked coordinate table),
    tracking the transform so glyph bboxes can be mapped back to page px."""
    q = np.array(b["px"], np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(q)
    if w < h:
        w, h, ang = h, w, ang + 90
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)
    ow, oh = int(w * 1.1) + 16, int(h * 1.15) + 8
    crop = cv2.getRectSubPix(rot, (ow, oh), (cx, cy))
    crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return crop, cv2.invertAffineTransform(M), (cx, cy), (ow, oh), upscale


def to_page(x, y, M_inv, c, half, up):
    rx, ry = c[0] - half[0] + x / up, c[1] - half[1] + y / up
    return M_inv[0, 0] * rx + M_inv[0, 1] * ry + M_inv[0, 2], M_inv[1, 0] * rx + M_inv[1, 1] * ry + M_inv[1, 2]


def bbox_to_page(g, M_inv, c, size, up):
    ow, oh = size
    corners = [to_page(x, y, M_inv, c, (ow / 2, oh / 2), up) for x, y in
               [(g["x"], g["y"]), (g["x1"], g["y"]), (g["x"], g["y1"]), (g["x1"], g["y1"])]]
    xs, ys = zip(*corners)
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


# ---------- segmentation ----------

def segment(crop):
    """Binarise (Otsu) and split into glyphs. Cap-height components merge when they overlap in x
    (a stroke broken by a pen skip); small marks (ring, ticks, dot) never merge into anything and
    keep their own place, tagged by vertical position in the box's cap band."""
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, lbl, stats, cent = cv2.connectedComponentsWithStats(bw, connectivity=8)
    ch, cw = crop.shape
    comps = [{"lbl": i, "x": int(stats[i][0]), "y": int(stats[i][1]), "w": int(stats[i][2]), "h": int(stats[i][3]),
              "cx": cent[i][0], "cy": cent[i][1]}
             for i in range(1, n) if stats[i][4] >= MIN_AREA
             and stats[i][2] < FRAME_FRAC * cw and stats[i][3] < FRAME_FRAC * ch  # drop a bubble border / table rule
             and stats[i][0] > EDGE_PX and stats[i][1] > EDGE_PX
             and stats[i][0] + stats[i][2] < cw - EDGE_PX and stats[i][1] + stats[i][3] < ch - EDGE_PX]  # drop a clipped frame arc / bled-in neighbour
    if not comps:
        return [], lbl
    cap_h = max(c["h"] for c in comps)
    for c in comps:
        c["cap"] = c["h"] >= SMALL_FRAC * cap_h
    caps = [c for c in comps if c["cap"]] or comps
    y_top, y_bot = min(c["y"] for c in caps), max(c["y"] + c["h"] for c in caps)
    band = max(y_bot - y_top, 1)
    for c in comps:
        rel = (c["cy"] - y_top) / band
        c["vpos"] = "top" if rel < 0.35 else ("baseline" if rel > 0.75 else "mid")
    comps.sort(key=lambda c: c["cx"])
    glyphs = []
    for c in comps:
        c["x1"], c["y1"] = c["x"] + c["w"], c["y"] + c["h"]
        if c["cap"] and glyphs and glyphs[-1]["cap"] and c["x"] < glyphs[-1]["x1"] - 0.15 * cap_h:
            g = glyphs[-1]
            x0, y0 = min(g["x"], c["x"]), min(g["y"], c["y"])
            x1, y1 = max(g["x1"], c["x1"]), max(g["y1"], c["y1"])
            g.update(x=x0, y=y0, x1=x1, y1=y1, lbls=g["lbls"] + [c["lbl"]])
        else:
            c["lbls"] = [c["lbl"]]
            glyphs.append(c)
    glyphs.sort(key=lambda g: g["cx"])
    return glyphs, lbl


def bitmap(lblimg, g):
    """Same normalisation as tags.bitmap(): scale the glyph to CAP px tall, centre in a PX x PX
    canvas, mild blur. Reimplemented for raster (resize a pixel mask, not draw vector strokes)."""
    sub = lblimg[g["y"]:g["y1"], g["x"]:g["x1"]]
    mask = (np.isin(sub, g["lbls"]) * 255).astype(np.uint8)
    h, w = mask.shape
    if h == 0 or w == 0:
        return np.zeros(PX * PX, np.float32)
    s = CAP / h
    nw, nh = min(max(1, round(w * s)), PX), min(max(1, round(h * s)), PX)
    small = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((PX, PX), np.uint8)
    oy, ox = (PX - nh) // 2, (PX - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = small
    return cv2.GaussianBlur(canvas, (3, 3), 0).astype(np.float32).ravel() / 255


def zoning(canvas):
    """Second descriptor: 4x4-cell histogram of Sobel gradient direction (4 bins, undirected)."""
    img = canvas.reshape(PX, PX)
    gx, gy = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = np.hypot(gx, gy), (np.arctan2(gy, gx) + np.pi) % np.pi
    bins = np.clip((ang / np.pi * 4).astype(int), 0, 3)
    cell = PX // 4
    hist = np.zeros((4, 4, 4), np.float32)
    for i in range(4):
        for j in range(4):
            m, b = mag[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell], bins[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell]
            for k in range(4):
                hist[i, j, k] = m[b == k].sum()
    v = hist.ravel()
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


# ---------- clustering ----------

def cluster(X, thresh):
    if len(X) == 0:
        return np.array([], int)
    if len(X) == 1:
        return np.array([1])
    Z = linkage(X, method="average", metric="euclidean")
    return fcluster(Z, t=thresh, criterion="distance")


def score(recs, truth, cluster_key, class_want):
    """Align each keyed box's FULL glyph sequence (cap + small together, left to right) to its
    truth string 1:1 where the counts match; boxes that don't match are skipped and counted.
    Aligned glyphs of class_want vote their cluster for the truth character there; purity =
    aligned votes whose cluster's majority is right."""
    by_box = {}
    for i, r in enumerate(recs):
        by_box.setdefault(r["box"], []).append((r["index"], i))
    votes = {}  # cluster id -> {char: count}
    aligned = skipped = 0
    for box, text in truth.items():
        seq = sorted(by_box.get(box, []))
        chars = list(text)
        if len(seq) != len(chars):
            skipped += 1
            continue
        aligned += 1
        for (idx, gi), ch in zip(seq, chars):
            r = recs[gi]
            if r["class"] != class_want or cluster_key not in r:
                continue
            votes.setdefault(r[cluster_key], {}).setdefault(ch, 0)
            votes[r[cluster_key]][ch] += 1
    majority = {cl: max(d, key=d.get) for cl, d in votes.items()}
    hit = tot = 0
    confusion = {}
    for cl, d in votes.items():
        maj = majority[cl]
        for ch, n in d.items():
            tot += n
            if ch == maj:
                hit += n
            else:
                key = tuple(sorted((ch, maj)))
                confusion[key] = confusion.get(key, 0) + n
    return {"aligned_boxes": aligned, "skipped_boxes": skipped, "hit": hit, "total": tot,
            "purity": hit / tot if tot else 0.0, "clusters_covered": len(votes), "majority": majority,
            "confusion": sorted(confusion.items(), key=lambda kv: -kv[1])}


# ---------- main ----------

def main():
    boxes = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    img = page_img()
    recs, cap_bm, cap_zn, small_bm = [], [], [], []
    fail_under = fail_over = 0  # proxy for touching (under-segmented) vs broken/pen-skip (over-segmented)
    for b in boxes:
        crop, M_inv, c, size, up = crop_level(img, b)
        glyphs, lblimg = segment(crop)
        n_cap = sum(g["cap"] for g in glyphs)
        expected = b.get("glyphs", n_cap)
        if n_cap < expected:
            fail_under += 1
        elif n_cap > expected:
            fail_over += 1
        for idx, g in enumerate(glyphs):
            bm = bitmap(lblimg, g)
            rec = {"box": b["id"], "index": idx, "bbox": bbox_to_page(g, M_inv, c, size, up),
                   "class": "cap" if g["cap"] else "small", "vpos": None if g["cap"] else g["vpos"]}
            recs.append(rec)
            if g["cap"]:
                cap_bm.append(bm); cap_zn.append(zoning(bm))
            else:
                small_bm.append(bm)
    cap_bm, small_bm = np.array(cap_bm), np.array(small_bm)
    cap_zn = np.array(cap_zn)
    n_cap_g, n_small_g = len(cap_bm), len(small_bm)
    print(f"boxes {len(boxes)} | glyphs {len(recs)} = cap {n_cap_g} + small {n_small_g}")
    print(f"segmentation vs OCR glyph-count proxy: under-segmented (touching) {fail_under} boxes, "
          f"over-segmented (broken stroke / pen skip) {fail_over} boxes, matched {len(boxes) - fail_under - fail_over}")

    cap_labels = cluster(cap_bm, CAP_THRESH)
    small_labels = cluster(small_bm, SMALL_THRESH)
    zn_labels = cluster(cap_zn, np.median(pdist(cap_zn)) * 0.5) if len(cap_zn) > 1 else np.array([])

    cap_i = small_i = 0
    for r in recs:
        if r["class"] == "cap":
            r["cluster"] = f"cap{int(cap_labels[cap_i])}"
            if len(zn_labels):
                r["cluster_zn"] = f"zn{int(zn_labels[cap_i])}"
            cap_i += 1
        else:
            r["cluster"] = f"small{int(small_labels[small_i])}"; small_i += 1

    pur_pixel = score(recs, TRUTH, "cluster", "cap")
    pur_small = score(recs, TRUTH, "cluster", "small")
    pur_zoning = score(recs, TRUTH, "cluster_zn", "cap") if len(zn_labels) else None

    print(f"cap clusters: {len(set(cap_labels))} (threshold {CAP_THRESH}); small clusters: {len(set(small_labels))} (threshold {SMALL_THRESH})")
    sizes = sorted(np.bincount(cap_labels)[1:], reverse=True) if len(cap_labels) else []
    print(f"cap cluster sizes, 30 largest: {sizes[:30]}")
    print(f"cap singletons: {sum(1 for s in sizes if s == 1)}")

    print(f"\nPURITY (pixel-Euclidean descriptor), cap glyphs: {pur_pixel['hit']}/{pur_pixel['total']} = {pur_pixel['purity']:.1%} "
          f"| aligned {pur_pixel['aligned_boxes']}/{len(TRUTH)} boxes, skipped {pur_pixel['skipped_boxes']} | clusters covered {pur_pixel['clusters_covered']}")
    if pur_zoning:
        print(f"PURITY (zoning descriptor), cap glyphs: {pur_zoning['hit']}/{pur_zoning['total']} = {pur_zoning['purity']:.1%} -- "
              f"{'zoning separates better' if pur_zoning['purity'] > pur_pixel['purity'] else 'pixel-Euclidean separates better'}")
    print(f"PURITY, small marks: {pur_small['hit']}/{pur_small['total']} = {pur_small['purity']:.1%} | aligned {pur_small['aligned_boxes']}/{len(TRUTH)}")
    print("confusion pairs (cap):", pur_pixel["confusion"][:10])
    print("confusion pairs (small):", pur_small["confusion"][:10])

    # ---------- outputs ----------
    for r in recs:
        r.pop("cluster_zn", None)  # internal, only used to compare descriptors above
    (OUT / "scan_glyphs.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")
    cap_centroids, cap_counts = [], []
    for cl in sorted(set(cap_labels)):
        m = cap_labels == cl
        cap_centroids.append(cap_bm[m].mean(0).reshape(PX, PX)); cap_counts.append(int(m.sum()))
    small_centroids, small_counts = [], []
    for cl in sorted(set(small_labels)):
        m = small_labels == cl
        small_centroids.append(small_bm[m].mean(0).reshape(PX, PX)); small_counts.append(int(m.sum()))
    np.savez(OUT / "scan_clusters.npz",
              cap_centroids=np.array(cap_centroids), cap_counts=np.array(cap_counts),
              small_centroids=np.array(small_centroids), small_counts=np.array(small_counts))

    # contact sheet: 40 largest clusters (cap first, then small), rows of up to 20 thumbnails
    all_bm = list(cap_bm) + list(small_bm)
    all_cl = [f"cap{c}" for c in cap_labels] + [f"small{c}" for c in small_labels]
    order = sorted(set(all_cl), key=lambda cl: -all_cl.count(cl))[:40]
    row_h, thumb = 30, 26
    sheet = np.full((len(order) * row_h, 20 * thumb + 90, 3), 255, np.uint8)
    maj_cap, maj_small = pur_pixel["majority"], pur_small["majority"]
    for row, cl in enumerate(order):
        idxs = [i for i, c in enumerate(all_cl) if c == cl][:20]
        maj = (maj_cap if cl.startswith("cap") else maj_small).get(cl, "?")
        label = f"{cl} n={all_cl.count(cl)} maj={maj}"
        cv2.putText(sheet, label, (2, row * row_h + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
        for col, i in enumerate(idxs):
            th = (all_bm[i].reshape(PX, PX) * 255).astype(np.uint8)
            th = cv2.resize(th, (thumb - 2, thumb - 2))
            x0 = 90 + col * thumb
            sheet[row * row_h + 1:row * row_h + 1 + thumb - 2, x0:x0 + thumb - 2] = cv2.cvtColor(255 - th, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(OUT / "scan_clusters.png"), sheet)

    # sample: 12 keyed boxes with glyph bboxes drawn + cluster id under each glyph
    keyed = list(TRUTH)[:12]
    by_box = {}
    for r in recs:
        by_box.setdefault(r["box"], []).append(r)
    tiles = []
    for box in keyed:
        b = next(bb for bb in boxes if bb["id"] == box)
        q = np.array(b["px"], np.int32)
        x0, y0 = q[:, 0].min() - 20, q[:, 1].min() - 20
        x1, y1 = q[:, 0].max() + 20, q[:, 1].max() + 20
        tile = cv2.cvtColor(img[max(0, y0):y1, max(0, x0):x1].copy(), cv2.COLOR_GRAY2BGR)
        for r in sorted(by_box.get(box, []), key=lambda r: r["index"]):
            gx0, gy0, gx1, gy1 = [v - (x0 if i % 2 == 0 else y0) for i, v in enumerate(r["bbox"])]
            cv2.rectangle(tile, (int(gx0), int(gy0)), (int(gx1), int(gy1)), (0, 0, 255), 1)
            cv2.putText(tile, r["cluster"].replace("cap", "c").replace("small", "s"), (int(gx0), int(gy1) + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(tile, f"box {box} truth {TRUTH[box]}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 128, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    w = max(t.shape[1] for t in tiles)
    h = sum(t.shape[0] for t in tiles) + 4 * len(tiles)
    canvas = np.full((h, w, 3), 255, np.uint8)
    y = 0
    for t in tiles:
        canvas[y:y + t.shape[0], 0:t.shape[1]] = t
        y += t.shape[0] + 4
    cv2.imwrite(str(OUT / "scan_glyphs_sample.png"), canvas)
    print(f"\nwrote {OUT/'scan_glyphs.json'}, {OUT/'scan_clusters.npz'}, {OUT/'scan_clusters.png'}, {OUT/'scan_glyphs_sample.png'}")


if __name__ == "__main__":
    main()
