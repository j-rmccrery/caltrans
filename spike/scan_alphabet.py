"""Loop 7: one hand, one alphabet -- for the scan.

Leg A: segment every detected box on R-65.2 into glyph images (connected components on a
levelled, binarised crop), normalise each to a 24x24 bitmap the same way alphabet.py's vector
bitmap() does (tags.PX=24/tags.CAP=18, reused verbatim; rendering reimplemented for raster),
then cluster by bitmap distance so one label per cluster can read the sheet.

Leg B: the segmentation limit from leg A (197/273 boxes fuse touching digits into one cap
blob) is attacked directly -- split fused blobs at their deepest vertical-projection valleys,
re-cluster the pieces against leg A's existing centroids. Clusters are then named from two
sources: (a) the two readers' agreed digits (read_scan.json), aligned to each box's glyph
sequence position by position; (b) structure -- a box shaped like a coordinate/bearing/distance
has known digit slots, and minutes/seconds are always < 60, both of which filter noisy votes
rather than invent new ones. Every box is read glyph by glyph (majority name with a margin),
assembled with marks, and passed through scan_consensus's own dropped-leading-digit repair.
Scored three ways on the keyed 32: template alone, template + consensus, and the untouched old
consensus (must reproduce 16/1/15).

usage: python spike/scan_alphabet.py
"""
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

sys.path.insert(0, str(Path(__file__).parent))
from gt_scan import TRUTH  # noqa: E402
from scan_readers import OUT, PDF  # noqa: E402
from scan_consensus import kind, grid_range, consensus, render, digits  # noqa: E402

PX, CAP = 24, 18.0       # same canvas as tags.bitmap(): glyph height -> CAP px, centred in PX x PX
SMALL_FRAC = 0.5         # a component under this * the box's tallest component is a small mark
MIN_AREA = 30            # px^2 in the 2x-upscaled crop; below this a component is grain / a hachure sliver
FRAME_FRAC = 0.85        # a component this wide or tall relative to the crop is a bubble border / table rule, not a glyph
EDGE_PX = 2              # a component touching the crop edge is a clipped frame arc or a bled-in neighbour, not a glyph
CAP_THRESH = 6.0         # agglomerative cut, cap-height glyphs (picked here: purity holds at 88/gate 70, cuts cluster count vs 5.5)
SMALL_THRESH = 4.0       # agglomerative cut, small marks (picked here: purity 84 vs gate 70, cuts cluster count vs 3.0)

SPLIT_RATIO = 1.6        # a cap blob wider than this * the single-glyph width is fused digits
CLEAN_MIN = 6            # a cap cluster with at least this many members recurs sheet-wide -> it's one character, not a one-off fusion
MARGIN = 1.15            # nearest/second-nearest centroid distance ratio required to trust an assignment or a read

NW_GAP, NW_MATCH, NW_MISMATCH = -1.0, 2.0, -100.0  # gapped alignment: moderate gap, class match/mismatch (mismatch effectively forbidden)
VLM_MIN_MEMBERS = 4      # a cap cluster needs at least this many glyphs before its contact strip is worth asking the model about
VLM_MAX_CALLS = 80       # largest-first cap; more than this and leg B stops being cheap
VLM_MODEL = "qwen2.5vl:7b"
VLM_PROMPT = ("Every image on this strip is the same handwritten character from one 1969 survey map. "
              "Answer with that single character only (a digit 0-9, a letter, or one of . ' \" ° R = N E S W). "
              "If the strip mixes characters, answer ?")
VALID_CHARS = set("0123456789") | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") | set(".'\"°=")


# ---------- render + crop (unchanged from leg A) ----------

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


# ---------- segmentation (unchanged) ----------

def segment(crop):
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, lbl, stats, cent = cv2.connectedComponentsWithStats(bw, connectivity=8)
    ch, cw = crop.shape
    comps = [{"lbl": i, "x": int(stats[i][0]), "y": int(stats[i][1]), "w": int(stats[i][2]), "h": int(stats[i][3]),
              "cx": cent[i][0], "cy": cent[i][1]}
             for i in range(1, n) if stats[i][4] >= MIN_AREA
             and stats[i][2] < FRAME_FRAC * cw and stats[i][3] < FRAME_FRAC * ch
             and stats[i][0] > EDGE_PX and stats[i][1] > EDGE_PX
             and stats[i][0] + stats[i][2] < cw - EDGE_PX and stats[i][1] + stats[i][3] < ch - EDGE_PX]
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


def bitmap_from_mask(mask):
    """Same normalisation as tags.bitmap(): scale to CAP px tall, centre in PX x PX, mild blur."""
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


def bitmap(lblimg, g):
    sub = lblimg[g["y"]:g["y1"], g["x"]:g["x1"]]
    mask = (np.isin(sub, g["lbls"]) * 255).astype(np.uint8)
    return bitmap_from_mask(mask)


def zoning(canvas):
    """Second descriptor: 4x4-cell histogram of Sobel gradient direction (4 bins, undirected).
    Leg A found this separates cap glyphs better (98.6% vs 88.4% pixel-Euclidean) -- it's the
    descriptor used for every nearest-centroid decision in leg B."""
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


# ---------- clustering (unchanged) ----------

def cluster(X, thresh):
    if len(X) == 0:
        return np.array([], int)
    if len(X) == 1:
        return np.array([1])
    Z = linkage(X, method="average", metric="euclidean")
    return fcluster(Z, t=thresh, criterion="distance")


def score(recs, truth, cluster_key, class_want):
    by_box = {}
    for i, r in enumerate(recs):
        by_box.setdefault(r["box"], []).append((r["index"], i))
    votes = {}
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


# ---------- leg B: split fused blobs ----------

def split_blob(lblimg, g, single_w):
    """Split a cap blob at k-1 deepest vertical-projection valleys, k = round(blob_w/single_w)
    clamped to [2,4] -- that's the k whose ideal piece width (blob_w/k) lands closest to
    single_w, so no search over candidate k values is needed. Each valley is the column of
    least ink within a window around its ideal (equal-share) position."""
    sub = lblimg[g["y"]:g["y1"], g["x"]:g["x1"]]
    mask = np.isin(sub, g["lbls"]).astype(np.uint8)
    h, w = mask.shape
    k = max(2, min(4, round(w / single_w)))
    profile = mask.sum(axis=0).astype(np.float64)
    bounds = [0]
    for i in range(1, k):
        ideal = i * w / k
        lo = max(bounds[-1] + 1, int(ideal - 0.4 * single_w))
        hi = min(w - 1, int(ideal + 0.4 * single_w))
        if lo >= hi:
            return None
        bounds.append(lo + int(np.argmin(profile[lo:hi])))
    bounds.append(w)
    pieces = []
    for i in range(k):
        x0, x1 = bounds[i], bounds[i + 1]
        if x1 - x0 < 2:
            return None
        pm = mask[:, x0:x1]
        ys = np.where(pm.any(axis=1))[0]
        if len(ys) == 0:
            return None
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        pbm = bitmap_from_mask((pm[y0:y1, :] * 255).astype(np.uint8))
        pieces.append({"x": g["x"] + x0, "y": g["y"] + y0, "x1": g["x"] + x1, "y1": g["y"] + y0 + (y1 - y0),
                        "cap": True, "vpos": None, "w_crop": x1 - x0, "bm": pbm, "zn": zoning(pbm)})
    return pieces


def nearest(bm, centroids):
    """centroids: {name: vec}. Returns (best_name, best_dist, ratio = 2nd_dist/best_dist)."""
    ds = sorted((float(np.linalg.norm(bm - v)), n) for n, v in centroids.items())
    if not ds:
        return None, float("inf"), 0.0
    if len(ds) == 1:
        return ds[0][1], ds[0][0], float("inf")
    return ds[0][1], ds[0][0], (ds[1][0] / ds[0][0] if ds[0][0] > 0 else float("inf"))


# ---------- leg B attempt 2: gapped alignment + VLM cluster naming ----------

def nw_align_votes(glyphs, text):
    """Needleman-Wunsch align a box's ordered glyphs to its accepted text by class (a cap glyph
    matches a digit/letter, a small mark matches . ' " deg), so a fused pair or a stray mark
    costs a gap instead of discarding the whole box. Returns (glyph, char) pairs for positions
    sitting inside a run of >= 2 consecutive matches -- an isolated match next to two gaps could
    be coincidence, a run of 2+ can't."""
    n, m = len(glyphs), len(text)
    if n == 0 or m == 0:
        return []
    classA = ["cap" if g["cap"] else "small" for g in glyphs]
    classB = ["cap" if c.isalnum() else "small" for c in text]
    dp = np.zeros((n + 1, m + 1))
    ptr = np.zeros((n + 1, m + 1), dtype=np.int8)  # 1=diag 2=gap-in-text(up) 3=gap-in-glyph(left)
    for i in range(1, n + 1):
        dp[i, 0] = dp[i - 1, 0] + NW_GAP; ptr[i, 0] = 2
    for j in range(1, m + 1):
        dp[0, j] = dp[0, j - 1] + NW_GAP; ptr[0, j] = 3
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = NW_MATCH if classA[i - 1] == classB[j - 1] else NW_MISMATCH
            diag, up, left = dp[i - 1, j - 1] + s, dp[i - 1, j] + NW_GAP, dp[i, j - 1] + NW_GAP
            best = max(diag, up, left)
            dp[i, j] = best
            ptr[i, j] = 1 if best == diag else (2 if best == up else 3)
    i, j, path = n, m, []
    while i > 0 or j > 0:
        p = ptr[i, j]
        if p == 1:
            path.append((i - 1, j - 1)); i -= 1; j -= 1
        elif p == 2:
            path.append((i - 1, None)); i -= 1
        else:
            path.append((None, j - 1)); j -= 1
    path.reverse()
    matched = [gi is not None and ti is not None for gi, ti in path]
    pairs, i = [], 0
    while i < len(path):
        if matched[i]:
            j = i
            while j < len(path) and matched[j]:
                j += 1
            if j - i >= 2:
                pairs.extend((glyphs[path[k][0]], text[path[k][1]]) for k in range(i, j))
            i = j
        else:
            i += 1
    return pairs


def vlm_ask(png_bytes, prompt):
    """Same call scan_readers.vlm/scan_vlm.py use (ollama /api/generate, qwen2.5vl:7b, temp 0);
    reimplemented locally so a different, example-free prompt can be sent for cluster naming."""
    req = {"model": VLM_MODEL, "stream": False, "options": {"temperature": 0}, "prompt": prompt,
           "images": [base64.b64encode(png_bytes).decode()]}
    r = urllib.request.urlopen(urllib.request.Request(
        "http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}), timeout=180)
    out = json.load(r)["response"].strip()
    return out.splitlines()[0] if out else ""


def render_strip(members, thumb=48, cols=12):
    sel = members[:cols]
    sheet = np.full((thumb, thumb * len(sel), 3), 255, np.uint8)
    for i, g in enumerate(sel):
        th = (g["bm"].reshape(PX, PX) * 255).astype(np.uint8)
        th = cv2.resize(255 - th, (thumb, thumb), interpolation=cv2.INTER_NEAREST)
        sheet[:, i * thumb:(i + 1) * thumb] = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)
    ok, buf = cv2.imencode(".png", sheet)
    return buf.tobytes()


# ---------- main ----------

def main():
    boxes = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    scan_by_id = {r["id"]: r for r in json.loads((OUT / "read_scan.json").read_text(encoding="utf-8"))}
    img = page_img()

    # ---- pass A: segment every box, cache crop+lblimg+glyphs, collect bitmaps for global clustering ----
    box_cache = []
    recs, cap_bm, cap_zn, small_bm = [], [], [], []
    fail_under = fail_over = 0
    for b in boxes:
        crop, M_inv, c, size, up = crop_level(img, b)
        glyphs, lblimg = segment(crop)
        n_cap = sum(g["cap"] for g in glyphs)
        expected = b.get("glyphs", n_cap)
        if n_cap < expected:
            fail_under += 1
        elif n_cap > expected:
            fail_over += 1
        for g in glyphs:
            g["bm"] = bitmap(lblimg, g)
            g["w_crop"] = g["x1"] - g["x"]
            (cap_bm if g["cap"] else small_bm).append(g["bm"])
            if g["cap"]:
                g["zn"] = zoning(g["bm"])
                cap_zn.append(g["zn"])
        box_cache.append({"box": b, "glyphs": glyphs, "lblimg": lblimg, "M_inv": M_inv, "c": c, "size": size, "up": up})
    cap_bm, small_bm, cap_zn = np.array(cap_bm), np.array(small_bm), np.array(cap_zn)
    n_cap_g, n_small_g = len(cap_bm), len(small_bm)
    print(f"boxes {len(boxes)} | glyphs {n_cap_g + n_small_g} = cap {n_cap_g} + small {n_small_g}")
    print(f"segmentation vs OCR glyph-count proxy: under-segmented (touching) {fail_under} boxes, "
          f"over-segmented (broken stroke / pen skip) {fail_over} boxes, matched {len(boxes) - fail_under - fail_over}")

    # zoning is the authoritative cap-glyph clustering (leg A: 98.6% purity vs 88.4% pixel-Euclidean) --
    # every downstream nearest-centroid decision (split-piece reassignment, final glyph read) uses it.
    # pixel-Euclidean clustering is kept only as an informational comparison print.
    pixel_labels = cluster(cap_bm, CAP_THRESH)
    cap_labels = cluster(cap_zn, np.median(pdist(cap_zn)) * 0.5) if len(cap_zn) > 1 else pixel_labels
    small_labels = cluster(small_bm, SMALL_THRESH)

    # stamp cluster names back onto the cached glyphs, in the same order they were appended above
    cap_i = small_i = 0
    for bc in box_cache:
        for g in bc["glyphs"]:
            if g["cap"]:
                g["cluster"] = f"cap{int(cap_labels[cap_i])}"
                g["cluster_px"] = f"px{int(pixel_labels[cap_i])}"
                cap_i += 1
            else:
                g["cluster"] = f"small{int(small_labels[small_i])}"; small_i += 1
        for i, g in enumerate(bc["glyphs"]):
            rec = {"box": bc["box"]["id"], "index": i,
                   "bbox": bbox_to_page(g, bc["M_inv"], bc["c"], bc["size"], bc["up"]),
                   "class": "cap" if g["cap"] else "small", "vpos": g["vpos"], "cluster": g["cluster"]}
            if g["cap"]:
                rec["cluster_px"] = g["cluster_px"]
            recs.append(rec)

    pur_zoning = score(recs, TRUTH, "cluster", "cap")       # authoritative
    pur_pixel = score(recs, TRUTH, "cluster_px", "cap")     # informational only
    pur_small = score(recs, TRUTH, "cluster", "small")
    print(f"cap clusters: {len(set(cap_labels))} zoning (authoritative) / {len(set(pixel_labels))} pixel (informational); "
          f"small clusters: {len(set(small_labels))} (threshold {SMALL_THRESH})")
    print(f"PURITY (zoning, authoritative) cap: {pur_zoning['hit']}/{pur_zoning['total']} = {pur_zoning['purity']:.1%} | aligned {pur_zoning['aligned_boxes']}/{len(TRUTH)}")
    print(f"PURITY (pixel, informational) cap: {pur_pixel['hit']}/{pur_pixel['total']} = {pur_pixel['purity']:.1%} | aligned {pur_pixel['aligned_boxes']}/{len(TRUTH)}")
    print(f"PURITY small: {pur_small['hit']}/{pur_small['total']} = {pur_small['purity']:.1%} | aligned {pur_small['aligned_boxes']}/{len(TRUTH)}")

    # centroids from leg A's own clusters -- "existing centroids" that both splitting and reading assign against.
    # cap centroids live in zoning-feature space (the authoritative descriptor); small centroids stay pixel-bitmap
    # (zoning was only shown better for cap glyphs).
    cap_centroid = {f"cap{cl}": cap_zn[cap_labels == cl].mean(0) for cl in sorted(set(cap_labels))}
    small_centroid = {f"small{cl}": small_bm[small_labels == cl].mean(0) for cl in sorted(set(small_labels))}

    # ---- step 1: split fused blobs ----
    # clean cluster = a cap cluster recurring >= CLEAN_MIN times sheet-wide (a fused pair/triple is near-unique, a
    # single glyph recurs); median width of those glyphs is the sheet's single-glyph width
    cap_cluster_count = {}
    for bc in box_cache:
        for g in bc["glyphs"]:
            if g["cap"]:
                cap_cluster_count[g["cluster"]] = cap_cluster_count.get(g["cluster"], 0) + 1
    clean_widths = [g["w_crop"] for bc in box_cache for g in bc["glyphs"]
                    if g["cap"] and cap_cluster_count[g["cluster"]] >= CLEAN_MIN]
    single_w = float(np.median(clean_widths)) if clean_widths else float(np.median([g["w_crop"] for bc in box_cache for g in bc["glyphs"] if g["cap"]]))
    print(f"\nsingle-glyph width (median over {len(clean_widths)} glyphs in clusters n>={CLEAN_MIN}): {single_w:.1f}px (crop space)")

    split_count = split_failed = 0
    for bc in box_cache:
        glyphs = bc["glyphs"]
        new_glyphs = []
        for g in glyphs:
            if g["cap"] and g["w_crop"] > SPLIT_RATIO * single_w:
                pieces = split_blob(bc["lblimg"], g, single_w)
                if pieces is None:
                    split_failed += 1
                    new_glyphs.append(g)
                    continue
                split_count += 1
                for p in pieces:
                    p["cx"] = (p["x"] + p["x1"]) / 2
                    name, d1, ratio = nearest(p["zn"], cap_centroid)
                    p["cluster"] = name if name else "cap_unassigned"
                    p["split_margin"] = ratio
                    new_glyphs.append(p)
            else:
                new_glyphs.append(g)
        new_glyphs.sort(key=lambda g: (g["x"] + g["x1"]) / 2 if "cx" not in g else g["cx"])
        bc["glyphs"] = new_glyphs
        for i, g in enumerate(bc["glyphs"]):
            g["idx"] = i

    total_glyphs_after = sum(len(bc["glyphs"]) for bc in box_cache)
    print(f"split {split_count} fused cap blobs ({split_failed} candidates couldn't find a clean valley and were left fused); "
          f"glyph total {n_cap_g + n_small_g} -> {total_glyphs_after}")

    aligned_after = sum(1 for bc in box_cache if bc["box"]["id"] in TRUTH and len(bc["glyphs"]) == len(TRUTH[bc["box"]["id"]]))
    print(f"box-count alignment against the 32 after splitting: {aligned_after}/{len(TRUTH)} (leg A: 11)")

    # ---- step 2: label the clusters ----
    # (a) seed votes: boxes where the two readers agree (or were repaired), Needleman-Wunsch
    # aligned by class to the accepted text (a fused pair or stray mark costs a gap instead of
    # dropping the box); only runs of >= 2 consecutive matches vote.
    votes = {}
    n_accepted = n_contrib = 0
    for bc in box_cache:
        row = scan_by_id.get(bc["box"]["id"])
        if not row or row["status"] == "queue":
            continue
        n_accepted += 1
        pairs = nw_align_votes(bc["glyphs"], row["text"])
        if not pairs:
            continue
        n_contrib += 1
        for g, ch in pairs:
            votes.setdefault(g["cluster"], {}).setdefault(ch, 0)
            votes[g["cluster"]][ch] += 1
    print(f"seed source (a), gapped alignment: {n_accepted} accepted boxes, {n_contrib} contribute >=1 vote "
          f"(exact-count alignment got 11), naming {len(votes)} clusters")

    # (b) structure: coordinate/radius boxes have a letter first cap, then all-digit slots;
    # angle/distance boxes are all-digit; minutes'/seconds" first digit (caps[-4], caps[-2] of an
    # angle box) must be 0-5. This only FILTERS votes from (a) -- it never invents a name alone.
    digit_ev, ms_ev, nondigit_ev = set(), set(), set()
    for bc in box_cache:
        row = scan_by_id.get(bc["box"]["id"], {})
        k = row.get("kind", "label")
        caps = [g for g in bc["glyphs"] if g["cap"]]
        if not caps:
            continue
        if k in ("coordinate", "radius"):
            prefix_letter = bool(re.match(r"^[NER]", (row.get("rapid", "") or row.get("vision", "")).strip().upper()))
            if prefix_letter:
                nondigit_ev.add(caps[0]["cluster"])
                digit_slots = caps[1:]
            else:
                digit_slots = caps
        elif k in ("angle", "distance"):
            digit_slots = caps
        else:
            continue
        for g in digit_slots:
            digit_ev.add(g["cluster"])
        if k == "angle" and len(caps) >= 4:
            ms_ev.add(caps[-4]["cluster"]); ms_ev.add(caps[-2]["cluster"])

    all_clusters = {g["cluster"] for bc in box_cache for g in bc["glyphs"]}
    cluster_name, raw_majority = {}, {}
    named_agree = named_struct = 0
    unnamed_clusters = []
    for cl in all_clusters:
        v = votes.get(cl, {})
        if not v:
            unnamed_clusters.append(cl)
            continue
        raw_ch = max(v, key=v.get)
        raw_majority[cl] = raw_ch
        cand = v
        if cl in ms_ev and cl not in nondigit_ev:
            f = {c: n for c, n in v.items() if c in "012345"}
            cand = f or v
        elif cl in digit_ev and cl not in nondigit_ev:
            f = {c: n for c, n in v.items() if c.isdigit()}
            cand = f or v
        ch = max(cand, key=cand.get)
        cluster_name[cl] = ch
        if ch == raw_ch:
            named_agree += 1
        else:
            named_struct += 1

    # (c) VLM: ask the local vision model to name the largest still-unnamed cap clusters, one
    # strip per cluster, cached so re-runs are free. Accepted only when the answer is one valid
    # character and, if the cluster carries agreement votes that got filtered to nothing by
    # structure, agrees with the raw vote majority.
    cap_members = {}
    for bc in box_cache:
        for g in bc["glyphs"]:
            if g["cap"]:
                cap_members.setdefault(g["cluster"], []).append(g)
    cache_path = OUT / "scan_cluster_names.json"
    vlm_cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    candidates = sorted((cl for cl in unnamed_clusters if len(cap_members.get(cl, [])) >= VLM_MIN_MEMBERS),
                         key=lambda cl: -len(cap_members[cl]))[:VLM_MAX_CALLS]
    vlm_calls = vlm_accepted = vlm_disagree = vlm_rejected = 0
    for cl in candidates:
        if cl in vlm_cache:
            ans = vlm_cache[cl]
        else:
            try:
                ans = vlm_ask(render_strip(cap_members[cl]), VLM_PROMPT)
            except Exception as e:
                ans = ""
            vlm_cache[cl] = ans
            vlm_calls += 1
        ans1 = ans.strip().upper()
        ans1 = ans1[:1] if len(ans1) == 1 and ans1 in VALID_CHARS else ""
        if not ans1:
            vlm_rejected += 1
            continue
        maj = raw_majority.get(cl)
        if maj is not None and ans1 != maj:
            vlm_disagree += 1
            continue
        cluster_name[cl] = ans1
        vlm_accepted += 1
    cache_path.write_text(json.dumps(vlm_cache, indent=1, ensure_ascii=False), encoding="utf-8")
    unnamed_final = len(unnamed_clusters) - vlm_accepted
    print(f"VLM naming: {len(candidates)} candidates (cap, n>={VLM_MIN_MEMBERS}, largest first, cap {VLM_MAX_CALLS}) -- "
          f"{vlm_calls} calls ({len(candidates) - vlm_calls} cache hits), {vlm_accepted} accepted, "
          f"{vlm_disagree} disagreed with vote, {vlm_rejected} not a single valid character")
    print(f"\ncluster naming: {len(all_clusters)} clusters total -- named by agreement {named_agree}, "
          f"named/corrected by structure {named_struct}, named by VLM {vlm_accepted}, unnamed (reads '?') {unnamed_final}")

    # ---- step 3: read all 273 boxes ----
    rapid_reads = boxes  # read_rapid.json, same list crop_level/segment already consumed
    grid = grid_range(rapid_reads)
    alpha_out = []
    template_raw = {}   # box id -> raw template text (pre-repair, with '?')
    final_status = {}   # box id -> agree/repaired/queue
    final_text = {}      # box id -> final rendered text
    for bc in box_cache:
        b = bc["box"]
        glyphs = bc["glyphs"]
        chars, glyph_reads = [], []
        n_read = 0
        for g in glyphs:
            centroids = cap_centroid if g["cap"] else small_centroid
            feat = g["zn"] if g["cap"] else g["bm"]  # zoning descriptor for caps (authoritative), pixel bitmap for marks
            own = g["cluster"]
            d_own = float(np.linalg.norm(feat - centroids[own])) if own in centroids else float("inf")
            d_other = min((float(np.linalg.norm(feat - v)) for n, v in centroids.items() if n != own), default=float("inf"))
            ratio = d_other / d_own if d_own > 0 else float("inf")
            name = cluster_name.get(own)
            if g["cap"]:
                ch = name if (name and ratio >= MARGIN) else "?"
            else:
                # marks: a voted cluster name wins, else fall back to the vpos default shape
                default = "." if g["vpos"] == "baseline" else ("°" if g["vpos"] == "mid" else "'")
                ch = name if name else default
            if ch != "?":
                n_read += 1
            chars.append(ch)
            glyph_reads.append({"index": g.get("idx", 0), "cluster": own, "char": ch})
        raw_text = "".join(chars)
        template_raw[b["id"]] = raw_text
        row = scan_by_id.get(b["id"], {})
        k = row.get("kind", kind(b.get("text", "")))
        rapid_text = row.get("rapid", b.get("text", ""))
        status, d = consensus(rapid_text, raw_text, k, grid)
        final_status[b["id"]] = status
        text_out = render(d, k, rapid_text, raw_text) if status != "queue" else raw_text
        final_text[b["id"]] = text_out
        conf = n_read / len(glyphs) if glyphs else 0.0
        alpha_out.append({"cx": b["cx"], "cy": b["cy"], "w": b["w"], "h": b["h"], "angle": b["angle"],
                          "text": text_out, "conf": round(conf, 3), "src": "alphabet", "id": b["id"], "glyph_reads": glyph_reads})
    (OUT / "read_alphabet.json").write_text(json.dumps(alpha_out, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---- step 4: score three ways on the keyed 32 ----
    def bucket(pred_text, truth_text, has_unknown):
        if has_unknown:
            return "queued"
        return "right" if digits(pred_text) == digits(truth_text) else "wrong"

    tmpl_right = tmpl_wrong = tmpl_queue = 0
    cons_right = cons_wrong = cons_queue = 0
    old_right = old_wrong = old_queue = 0
    causes = []
    for box, truth_text in TRUTH.items():
        raw = template_raw.get(box, "")
        b1 = bucket(raw, truth_text, "?" in raw or raw == "")
        if b1 == "right":
            tmpl_right += 1
        elif b1 == "wrong":
            tmpl_wrong += 1
        else:
            tmpl_queue += 1

        st = final_status.get(box, "queue")
        if st == "queue":
            cons_queue += 1
        elif digits(final_text.get(box, "")) == digits(truth_text):
            cons_right += 1
        else:
            cons_wrong += 1

        row = scan_by_id.get(box, {})
        if row.get("status") == "queue":
            old_queue += 1
        elif digits(row.get("text", "")) == digits(truth_text):
            old_right += 1
        else:
            old_wrong += 1

        if b1 != "right":
            bc = next(x for x in box_cache if x["box"]["id"] == box)
            n_glyph = len(bc["glyphs"])
            n_truth = len(truth_text)
            if abs(n_glyph - n_truth) > 2:
                cause = "box on the wrong text: unrecoverable here"
            elif any(g["cap"] and g["w_crop"] > SPLIT_RATIO * single_w for g in bc["glyphs"]):
                cause = "fused digits not split"
            elif "?" in raw:
                cause = "cluster unnamed"
            else:
                td, tt = digits(raw), digits(truth_text)
                confusable = {("3", "5"), ("0", "4"), ("3", "8")}
                pair_hit = len(td) == len(tt) and any(tuple(sorted((a, b))) in confusable for a, b in zip(td, tt) if a != b)
                cause = "look-alike confusion 3/5, 0/4, 3/8" if pair_hit else "hatch noise"
            causes.append((box, truth_text, raw, cause))

    print(f"\nSCORE template alone:        right {tmpl_right}  wrong {tmpl_wrong}  queued {tmpl_queue}  (of {len(TRUTH)})")
    print(f"SCORE template + consensus:  right {cons_right}  wrong {cons_wrong}  queued {cons_queue}  (of {len(TRUTH)})")
    print(f"SCORE old consensus:         right {old_right}  wrong {old_wrong}  queued {old_queue}  (of {len(TRUTH)}) (baseline 16/1/15)")
    gate2 = cons_right >= 20 and cons_wrong <= 1
    print(f"GATE attempt 2 (template+consensus): right {cons_right} wrong {cons_wrong} -- {'PASS' if gate2 else 'MISS'} (need right>=20, wrong<=1)")

    print("\ncause table (wrong/queued under template-alone):")
    for box, truth_text, raw, cause in causes:
        print(f"  {box:4} truth {truth_text!r:26} template {raw!r:26} -- {cause}")

    if not gate2:
        # per unnamed-or-wrong cluster among the 20 largest cap clusters, what its strip shows
        wrong_truth = {cl: ch for cl, ch in pur_pixel["majority"].items()}
        big20 = sorted(cap_members, key=lambda cl: -len(cap_members[cl]))[:20]
        print("\n20 largest cap clusters -- name, status, what the strip shows:")
        for cl in big20:
            named = cluster_name.get(cl)
            is_wrong = named is not None and cl in wrong_truth and wrong_truth[cl] != named
            if named is not None and not is_wrong:
                continue
            ans = vlm_cache.get(cl)
            if ans is None:
                try:
                    ans = vlm_ask(render_strip(cap_members[cl]), VLM_PROMPT)
                except Exception as e:
                    ans = f"<{type(e).__name__}>"
                vlm_cache[cl] = ans
                cache_path.write_text(json.dumps(vlm_cache, indent=1, ensure_ascii=False), encoding="utf-8")
            status = "wrong (named %r, keyed truth %r)" % (named, wrong_truth.get(cl)) if is_wrong else "unnamed"
            print(f"  {cl:10} n={len(cap_members[cl]):3} {status:32} strip shows: {ans!r}")

    # ---- gate render: 12 keyed boxes, 6 right + 6 queued/wrong, truth/template/consensus ----
    keyed = list(TRUTH)
    right_boxes = [box for box in keyed if bucket(template_raw.get(box, ""), TRUTH[box], "?" in template_raw.get(box, "")) == "right"][:6]
    other_boxes = [box for box in keyed if box not in right_boxes][:6]
    tiles = []
    for box in right_boxes + other_boxes:
        b = next(bb for bb in boxes if bb["id"] == box)
        q = np.array(b["px"], np.int32)
        x0, y0 = q[:, 0].min() - 20, q[:, 1].min() - 20
        x1, y1 = q[:, 0].max() + 20, q[:, 1].max() + 20
        tile = cv2.cvtColor(img[max(0, y0):y1, max(0, x0):x1].copy(), cv2.COLOR_GRAY2BGR)
        pad = np.full((54, tile.shape[1], 3), 255, np.uint8)
        tile = np.vstack([tile, pad])
        y = tile.shape[0] - 50
        cv2.putText(tile, f"truth: {TRUTH[box]}", (2, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 128, 0), 1, cv2.LINE_AA)
        cv2.putText(tile, f"template: {template_raw.get(box, '')}", (2, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 200), 1, cv2.LINE_AA)
        cv2.putText(tile, f"consensus: {scan_by_id.get(box, {}).get('text', '')}", (2, y + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 0, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    w = max(t.shape[1] for t in tiles)
    h = sum(t.shape[0] for t in tiles) + 4 * len(tiles)
    canvas = np.full((h, w, 3), 255, np.uint8)
    y = 0
    for t in tiles:
        canvas[y:y + t.shape[0], 0:t.shape[1]] = t
        y += t.shape[0] + 4
    cv2.imwrite(str(OUT / "scan_reads.png"), canvas)

    # ---- scan_cluster_names.png: 40 largest clusters (cap+small) with their final name ----
    all_members = {}
    for bc in box_cache:
        for g in bc["glyphs"]:
            all_members.setdefault(g["cluster"], []).append(g)
    order40 = sorted(all_members, key=lambda cl: -len(all_members[cl]))[:40]
    row_h, thumb = 30, 26
    sheet = np.full((len(order40) * row_h, 20 * thumb + 110, 3), 255, np.uint8)
    for row, cl in enumerate(order40):
        members = all_members[cl][:20]
        label = f"{cl} n={len(all_members[cl])} name={cluster_name.get(cl, '?')!r}"
        cv2.putText(sheet, label, (2, row * row_h + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
        for col, g in enumerate(members):
            th = (g["bm"].reshape(PX, PX) * 255).astype(np.uint8)
            th = cv2.resize(th, (thumb - 2, thumb - 2))
            x0 = 110 + col * thumb
            sheet[row * row_h + 1:row * row_h + 1 + thumb - 2, x0:x0 + thumb - 2] = cv2.cvtColor(255 - th, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(OUT / "scan_cluster_names.png"), sheet)
    print(f"\nwrote {OUT/'read_alphabet.json'} ({len(alpha_out)} boxes), {OUT/'scan_reads.png'}, {OUT/'scan_cluster_names.png'}")


if __name__ == "__main__":
    main()
