#!/usr/bin/env python3
"""Deterministic helpers for grid puzzles (Round 3 G8 "The Message Between", G9 "The Tunnels", and lookalikes).

  grid.py read IMAGE [--out DIR]
      Find every grid of same-size tiles in a screenshot. For each grid: rows × cols, exact cell boxes (fractions of the
      image, ready for <step at=…>), highlighted cells (glow/colour, e.g. the start tile or marked tiles), the text in
      each cell (native OCR), and for symbol tiles (arrows, runes, icons) a class letter per cell. Tiles with the same
      symbol share a letter, so you only identify each CLASS once (classes.png shows one sample per class) instead of
      reading every tile. Writes DIR/grid.json for the other commands.

  grid.py route --json DIR/grid.json [--grid N] --key "A=UP,B=DOWN,C=LEFT,D=RIGHT" [--start R,C] [--exit top]
  grid.py route --cells "DLUDDL/DDULDD/..." --key "U=UP,D=DOWN,L=LEFT,R=RIGHT" --start 6,3
      G9: follow the symbols from the start (1-based row,col; default: the highlighted cell) until the route leaves
      through the exit edge. Reports loops / wrong exits, prints the route and ready-to-paste click <step>s.

  grid.py message --seats "STA/Y_C/ALM" --rows "3,1,2" --cols "STORM,FIRE,WAVE" --want-rows "1,2,3"
                  --want-cols "FIRE,WAVE,STORM" --coords "1:FIRE 1:WAVE 1:STORM 2:FIRE ..."
      G8: letters sit FIXED in their seats while the row/column markers move. Prints the transmission text for the target
      arrangement (_ = the blank seat = a space), the marker moves (as swaps) to get from the current to the target
      order, and what the coordinates would read WITHOUT rearranging (the trap).
"""
import argparse
import collections, json
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR = os.path.join(ROOT, "tools", "ocr", "ocr")


# ----------------------------------------------------------------------------------------------------------- read
def square_boxes(img):
    """Candidate tiles: roughly square contours, several edge thresholds, de-duplicated."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    out = []
    for lo, hi, close in ((30, 90, 0), (15, 50, 0), (50, 150, 0), (20, 60, 5)):
        e = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), lo, hi)
        e = cv2.dilate(e, np.ones((2, 2), np.uint8))
        if close:  # dashed outlines (answer boxes): bridge the gaps between dashes
            e = cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
        cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            x, y, w, h = cv2.boundingRect(c)
            if w < 18 or h < 18 or w > W * 0.3 or h > H * 0.3 or not 0.8 < w / h < 1.25:
                continue
            area = cv2.contourArea(c)
            if area < 0.6 * w * h:  # must be a filled-looking rectangle outline
                continue
            out.append((x, y, w, h))
    # merge near-duplicates (same tile found by several thresholds / inner+outer borders): keep the larger
    out.sort(key=lambda b: -b[2] * b[3])
    keep = []
    for b in out:
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        if any(abs(cx - (k[0] + k[2] / 2)) < k[2] * 0.35 and abs(cy - (k[1] + k[3] / 2)) < k[3] * 0.35 for k in keep):
            continue
        keep.append(b)
    return keep


def cluster_1d(vals, tol):
    vals = sorted(vals)
    groups = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [float(np.mean(g)) for g in groups]


def even_lattice(vals, size):
    """Keep the evenly spaced run of positions (drop stray rows/cols far from the lattice)."""
    if len(vals) < 3:
        return vals
    d = np.diff(vals)
    step = float(np.median(d))
    keep = [v for i, v in enumerate(vals) if min([abs(v - w) for j, w in enumerate(vals) if j != i]) <= max(step, size) * 1.25]
    return keep if len(keep) >= 2 else vals


def grids_from_boxes(boxes):
    """Group same-size tiles, then snap them to rows/columns. Returns [{rows, cols, size, xs, ys}]."""
    boxes = sorted(boxes, key=lambda b: b[2])
    groups = []
    for b in boxes:
        for g in groups:
            if abs(b[2] - g["size"]) <= 0.12 * g["size"]:
                g["boxes"].append(b)
                g["size"] = float(np.median([x[2] for x in g["boxes"]]))
                break
        else:
            groups.append({"size": float(b[2]), "boxes": [b]})
    grids = []
    for g in groups:
        if len(g["boxes"]) < 4:
            continue
        s = g["size"]
        xs = even_lattice(cluster_1d([b[0] + b[2] / 2 for b in g["boxes"]], s * 0.4), s)
        ys = even_lattice(cluster_1d([b[1] + b[3] / 2 for b in g["boxes"]], s * 0.4), s)
        # split into connected blocks: a grid's rows/cols are evenly spaced; drop stray far-away singletons
        filled = {}
        for b in g["boxes"]:
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            c = int(np.argmin([abs(cx - x) for x in xs])); r = int(np.argmin([abs(cy - y) for y in ys]))
            if abs(cx - xs[c]) > s * 0.6 or abs(cy - ys[r]) > s * 0.6:
                continue  # not on the lattice
            filled[(r, c)] = b
        # drop sparse rows/columns (stray shapes near the grid), then re-check density
        for _ in range(2):
            rowfill = lambda r: sum(1 for (rr, cc) in filled if rr == r)
            colfill = lambda c: sum(1 for (rr, cc) in filled if cc == c)
            # dense rows/cols stay; a partial LAST row with ≥2 tiles stays too (wrapped layouts, e.g. answer boxes)
            rc = [r for r in range(len(ys)) if rowfill(r) >= 0.5 * len(xs) or (r == len(ys) - 1 and rowfill(r) >= 1 and len(ys) >= 2)]
            cc_ = [c for c in range(len(xs)) if colfill(c) >= 0.5 * len(ys) or colfill(c) >= 2 and any(rr == len(ys) - 1 for (rr, cc) in filled if cc == c) and colfill(c) >= 1]
            if len(rc) == len(ys) and len(cc_) == len(xs):
                break
            ys2 = [ys[r] for r in rc]; xs2 = [xs[c] for c in cc_]
            filled = {(rc.index(r), cc_.index(c)): b for (r, c), b in filled.items() if r in rc and c in cc_}
            ys, xs = ys2, xs2
        if not xs or not ys or len(filled) < max(4, 0.5 * len(xs) * len(ys)):
            continue
        grids.append({"size": s, "xs": xs, "ys": ys, "filled": filled})
    grids.sort(key=lambda g: -len(g["filled"]))
    return grids


def ocr_lines(path):
    if not os.path.exists(OCR):
        return []
    try:
        out = subprocess.run([OCR, path], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        try:
            coords, text = line.split("\t", 1)
            x0, y0, x1, y1 = map(float, coords.split())
            res.append((x0, y0, x1, y1, text.strip()))
        except ValueError:
            continue
    return res


def reread(img, boxes):
    """Second OCR pass for cells the full-screen OCR missed: upscale each crop, lay them out on ONE line with wide
    gaps, OCR once, and split the reading back per cell (only when the count matches)."""
    if not boxes or not os.path.exists(OCR):
        return [""] * len(boxes)
    tiles = []
    for (x, y, w, h) in boxes:
        m = int(min(w, h) * 0.1)
        c = cv2.resize(img[y + m:y + h - m, x + m:x + w - m], (120, 120), interpolation=cv2.INTER_CUBIC)
        bg = [int(v) for v in np.median(c.reshape(-1, 3), axis=0)]
        tiles.append(cv2.copyMakeBorder(c, 30, 30, 50, 50, cv2.BORDER_CONSTANT, value=bg))
    line = np.hstack(tiles)
    tmp = "/tmp/_grid_reread.png"; cv2.imwrite(tmp, line)
    got = [(x0, t) for (x0, y0, x1, y1, t) in ocr_lines(tmp)]
    chars = [ch for _, t in sorted(got) for ch in t.replace(" ", "")]
    return chars if len(chars) == len(boxes) else [""] * len(boxes)


_ALPHA = None


def _prep(f):
    f = cv2.GaussianBlur(f, (0, 0), 1.5); f = f - f.mean(); return f / (np.linalg.norm(f) + 1e-6)


def alphabet_templates():
    """A–Z rendered in a few common fonts, as centred glyph features (fallback for letters OCR can't read alone)."""
    global _ALPHA
    if _ALPHA is None:
        from PIL import Image, ImageDraw, ImageFont
        _ALPHA = []
        for fp in ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
            try:
                font = ImageFont.truetype(fp, 64)
            except OSError:
                continue
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                im = Image.new("L", (100, 100), 0); ImageDraw.Draw(im).text((18, 8), ch, fill=255, font=font)
                f, _ = glyph(cv2.cvtColor(np.array(im), cv2.COLOR_GRAY2BGR), (0, 0, 100, 100), margin=0.0)
                _ALPHA.append((ch, _prep(f)))
    return _ALPHA


def match_letter(f, known):
    """Letter for glyph feature f: first against letters already read in this grid (same font), then A–Z templates."""
    pf = _prep(f)
    best = max(((float((pf * _prep(kf)).sum()), ch) for ch, kf in known), default=(0, ""))
    if best[0] >= 0.85:
        return best[1]
    scores = {}
    for ch, t in alphabet_templates():
        scores[ch] = max(scores.get(ch, -1), float((pf * t).sum()))
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked and ranked[0][1] >= 0.6 and (len(ranked) < 2 or ranked[0][1] - ranked[1][1] >= 0.05):
        return ranked[0][0]
    return ""  # too close to call (O/Q, C/G…): leave it for the eye


def glyph(img, box, margin=0.18):
    x, y, w, h = box
    m = int(w * margin)
    crop = img[y + m:y + h - m, x + m:x + w - m]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if b.mean() > 127:  # make the glyph the "on" colour
        b = 255 - b
    # drop small off-centre specks (a corner index letter, a badge) so they don't change the glyph class
    n, lab, st, cen = cv2.connectedComponentsWithStats(b, 8)
    if n > 2:
        hh, ww = b.shape
        big = st[1:, cv2.CC_STAT_AREA].max()
        for i in range(1, n):
            cx, cy = cen[i]
            off = max(abs(cx - ww / 2) / ww, abs(cy - hh / 2) / hh)
            if st[i, cv2.CC_STAT_AREA] < 0.35 * big and off > 0.3:
                b[lab == i] = 0
    # centre and scale on the ink itself, so small differences in where each tile was detected don't matter
    ys, xs = np.nonzero(b > 0)
    if len(xs) > 8:
        b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        h, w = b.shape; side = max(h, w) + 4
        pad = np.zeros((side, side), np.uint8); pad[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = b
        b = pad
    return cv2.resize(b, (24, 24), interpolation=cv2.INTER_AREA).astype(np.float32) / 255, crop


def glyph_hr(img, box, res=40, margin=0.12):
    """Higher-resolution glyph for telling near misses apart (a stroke missing): speckles removed, ink centred."""
    x, y, w, h = box
    m = int(w * margin)
    crop = img[y + m:y + h - m, x + m:x + w - m]
    if crop.size == 0:
        return np.zeros((res, res), np.float32)
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if b.mean() > 127:
        b = 255 - b
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    big = st[1:, cv2.CC_STAT_AREA].max() if n > 1 else 0
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < max(12, 0.02 * big):
            b[lab == i] = 0
    ys, xs = np.nonzero(b)
    if len(xs) > 8:
        b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(b.shape) + 2
    pad = np.zeros((side, side), np.uint8)
    pad[(side - b.shape[0]) // 2:(side - b.shape[0]) // 2 + b.shape[0], (side - b.shape[1]) // 2:(side - b.shape[1]) // 2 + b.shape[1]] = b
    return cv2.resize(pad, (res, res), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def _prep(f):
    f = cv2.GaussianBlur(f, (0, 0), 1.5); f = f - f.mean(); return f / (np.linalg.norm(f) + 1e-6)


def _rot(f, a):
    M = cv2.getRotationMatrix2D((f.shape[1] / 2, f.shape[0] / 2), a, 1.0)
    return cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)


def stroke_gap(f, ref):
    """Largest local ink difference between two hi-res glyphs after the best small rotation and 1-px shift:
    ~0.2-0.5 for the same fragment drawn at another tilt/scale, ~0.8+ when a stroke is missing or added."""
    pr = _prep(ref)
    ang = max(range(-12, 13, 2), key=lambda a_: float((_prep(_rot(f, a_)) * pr).sum()))
    rf = _rot(f, ang)
    return min(float(cv2.GaussianBlur(np.abs(np.roll(np.roll(rf, dy, 0), dx, 1) - ref), (0, 0), 1.5).max())
               for dx in (-1, 0, 1) for dy in (-1, 0, 1))


MOVE_WORDS = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT", "north": "UP", "south": "DOWN", "west": "LEFT",
              "east": "RIGHT", "↑": "UP", "↓": "DOWN", "←": "LEFT", "→": "RIGHT"}


def key_card(img, lines, grid_box, classes, feats_hr, cells, R, C):
    """A visible key card: move words (up/down/left/right) with a glyph drawn above each. Match every board glyph
    class to the key glyphs. Returns ({class: MOVE}, [classes with no key glyph], report) or None."""
    H, W = img.shape[:2]
    gx0, gy0, gx1, gy1 = grid_box
    labs = []
    for (x0, y0, x1, y1, t) in lines:
        w_ = t.strip().lower()
        cx, cy = (x0 + x1) / 2 * W, (y0 + y1) / 2 * H
        if w_ in MOVE_WORDS and not (gx0 <= cx <= gx1 and gy0 <= cy <= gy1):
            labs.append((cx, y0 * H, (y1 - y0) * H, MOVE_WORDS[w_]))
    if len(labs) < 2 or len({l[3] for l in labs}) < 2:
        return None
    xs = sorted(l[0] for l in labs)
    gap = min(b - a for a, b in zip(xs, xs[1:])) if len(xs) > 1 else labs[0][2] * 6
    size = max(12, min(gap * 0.72, labs[0][2] * 7))
    keys = []
    ty_row = float(np.median([l[1] for l in labs])); th_row = float(np.median([l[2] for l in labs]))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for (cx, ty, th, mv) in labs:
        ty = ty_row if abs(ty - ty_row) < th_row else ty  # labels in one row share a baseline
        bx = [int(cx - size * 0.65), int(ty - th_row * 0.4 - size * 1.25), int(size * 1.3), int(size * 1.25)]
        if bx[0] < 0 or bx[1] < 0:
            continue
        # the glyph usually sits on its own little card: snap to that card if there is one
        sub = gray[bx[1]:bx[1] + bx[3], bx[0]:bx[0] + bx[2]]
        _, bw = cv2.threshold(sub, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        n_, lab_, st_, _ = cv2.connectedComponentsWithStats(bw, 8)
        if n_ > 1:
            i_ = 1 + int(np.argmax(st_[1:, cv2.CC_STAT_AREA]))
            x_, y_, w_, h_, a_ = st_[i_]
            if a_ > 0.25 * size * size and 0.6 < w_ / max(1, h_) < 1.6:
                bx = [bx[0] + x_, bx[1] + y_, w_, h_]
        keys.append((mv, glyph_hr(img, tuple(bx), margin=0.06)))
    if len(keys) < 2:
        return None
    by_cls = {}
    for k, cl in classes.items():
        if cl not in "_" and k in feats_hr:
            by_cls.setdefault(cl, []).append(feats_hr[k])
    mapping, none_, rep = {}, [], []
    for cl, fs in sorted(by_cls.items()):
        sample = fs[:5]
        scores = sorted(((float(np.median([stroke_gap(f, kg) for f in sample])), mv) for mv, kg in keys))
        best, second = scores[0], (scores[1] if len(scores) > 1 else (9, ""))
        if best[0] < 0.62 and second[0] - best[0] > 0.12:
            mapping[cl] = best[1]
        else:
            none_.append(cl)
        rep.append(f"{cl}:{best[1].lower()}({best[0]:.2f})")
    return mapping, none_, " ".join(rep)


def input_fields(img, lines_ocr):
    """Text-entry fields: wide bordered rectangles that are empty or hold only placeholder text. Returns px boxes."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    e = cv2.dilate(cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 20, 60), np.ones((2, 2), np.uint8))
    cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        if not (22 <= h <= 90 and w >= 3 * h and w >= 110 and w <= W * 0.7):
            continue
        if cv2.contourArea(c) < 0.55 * w * h:
            continue
        inner = g[y + 4:y + h - 4, x + 6:x + w - 6]
        if inner.size == 0:
            continue
        txt = [t for (x0, y0, x1, y1, t) in lines_ocr if x < (x0 + x1) / 2 * W < x + w and y < (y0 + y1) / 2 * H < y + h]
        busy = (np.abs(cv2.Sobel(inner.astype(np.float32), cv2.CV_32F, 1, 0)) > 60).mean()
        if busy > 0.08 and not txt:
            continue  # textured: probably a picture or a button with an icon, not an input
        found.append((x, y, w, h, " ".join(txt)))
    found.sort(key=lambda b: -b[2] * b[3])
    keep = []
    for b in found:  # nested outlines of the same field
        if not any(abs(b[0] - k[0]) < 10 and abs(b[1] - k[1]) < 10 for k in keep):
            keep.append(b)
    return sorted(keep, key=lambda b: (b[1], b[0]))


def tile_lines(boxes, used):
    """Same-size tiles in a straight line (axis markers / headers): [{orient, boxes}]."""
    rest = [b for b in boxes if b not in used]
    out = []
    for orient in ("h", "v"):
        key = (lambda b: b[1] + b[3] / 2) if orient == "h" else (lambda b: b[0] + b[2] / 2)
        pos = (lambda b: b[0]) if orient == "h" else (lambda b: b[1])
        groups = {}
        for b in rest:
            k = None
            for g in groups:
                if abs(key(b) - g[0]) < b[3] * 0.3 and abs(b[2] - g[1]) < b[2] * 0.15:
                    k = g; break
            groups.setdefault(k or (key(b), b[2]), []).append(b)
        for g, bs in groups.items():
            if len(bs) >= 2:
                out.append({"orient": orient, "boxes": sorted(bs, key=pos)})
    return out


def cmd_read(a):
    img = cv2.imread(a.image)
    if img is None:
        sys.exit("cannot read image")
    H, W = img.shape[:2]
    out = a.out or os.path.splitext(a.image)[0] + "_grid"
    os.makedirs(out, exist_ok=True)
    grids = grids_from_boxes(square_boxes(img))
    lines = ocr_lines(a.image)
    result = []
    for gi, g in enumerate(grids[:4], 1):
        R, C, s = len(g["ys"]), len(g["xs"]), g["size"]
        cells, feats, crops = {}, [], []
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        feats_hr = {}
        for r in range(R):
            for c in range(C):
                b = g["filled"].get((r, c))
                inferred = b is None
                if b is None:  # infer the box from the lattice
                    b = (int(g["xs"][c] - s / 2), int(g["ys"][r] - s / 2), int(s), int(s))
                x, y, w, h = b
                ring = hsv[max(0, y - 4):y + h + 4, max(0, x - 4):x + w + 4]
                bw = max(2, int(w * 0.14))
                band = np.concatenate([hsv[y:y + bw, x:x + w].reshape(-1, 3), hsv[y + h - bw:y + h, x:x + w].reshape(-1, 3),
                                       hsv[y:y + h, x:x + bw].reshape(-1, 3), hsv[y:y + h, x + w - bw:x + w].reshape(-1, 3)])
                inner = hsv[y + bw:y + h - bw, x + bw:x + w - bw].reshape(-1, 3)
                bright = inner[inner[:, 2] > np.percentile(inner[:, 2], 85)] if len(inner) else inner  # glyph pixels
                txt = [t for (x0, y0, x1, y1, t) in lines if x <= (x0 + x1) / 2 * W <= x + w and y <= (y0 + y1) / 2 * H <= y + h]
                f, crop = glyph(img, b)
                cells[(r, c)] = {"box": [round(x / W, 4), round(y / H, 4), round((x + w) / W, 4), round((y + h) / H, 4)],
                                 "text": " ".join(txt), "sat": float(ring[..., 1].mean()), "val": float(ring[..., 2].mean()),
                                 "hue": float(np.median(ring[..., 0])), "empty": bool(f.mean() < 0.02),
                                 "feat": [float(band[:, 1].mean()), float(band[:, 2].mean()), float(bright[:, 1].mean()) if len(bright) else 0.0,
                                          float(ring[..., 1].mean()), float(ring[..., 2].mean())],
                                 "hue_band": float(np.median(band[band[:, 1] > 60][:, 0])) if (band[:, 1] > 60).sum() > 5 else -1.0,
                                 "satfrac": float(((band[:, 1] > 60) & (band[:, 2] > 80)).mean()),
                                 "inferred": inferred}
                feats.append(((r, c), f)); crops.append(((r, c), crop)); feats_hr[(r, c)] = glyph_hr(img, b)
        # symbol classes: hierarchical clustering of centred glyphs (ink-overlap distance), cut at the largest jump
        # between merge distances, so the number of classes adapts to the symbol set
        classes, reps = {}, []
        ink = [(k, f) for k, f in feats if not cells[k]["empty"]]
        for k, f in feats:
            if cells[k]["empty"]:
                classes[k] = "_"
        if len(ink) >= 2:
            from scipy.cluster.hierarchy import fcluster, linkage
            from scipy.spatial.distance import squareform
            # distance = 1 - correlation of lightly blurred glyphs (tolerant to 1-px shifts and stroke width)
            def prep(f):
                f = cv2.GaussianBlur(f, (0, 0), 1.5); f = f - f.mean(); return f / (np.linalg.norm(f) + 1e-6)
            P = [prep(f) for _, f in ink]
            n = len(ink); D = np.zeros((n, n))
            for i in range(n):
                for j in range(i + 1, n):
                    D[i, j] = D[j, i] = max(0.0, 1 - float((P[i] * P[j]).sum()))
            # a finer, tilt-tolerant distance (40 px, speckles removed, best of small rotations) used only to split
            # near misses out of a class below
            def rot(f, a):
                M = cv2.getRotationMatrix2D((f.shape[1] / 2, f.shape[0] / 2), a, 1.0)
                return cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
            PR = np.stack([np.stack([prep(rot(feats_hr[k], a)).ravel() for k, _ in ink]) for a in (-8, -6, -4, -2, 0, 2, 4, 6, 8)])
            C_ = np.einsum("rnd,md->rnm", PR, PR[4]).max(axis=0)
            C_ = np.maximum(C_, C_.T)
            DH = np.clip(1 - C_, 0, None); np.fill_diagonal(DH, 0)
            Z = linkage(squareform(D), "average")
            def silhouette(lab):
                sc = []
                for i in range(n):
                    same = D[i, lab == lab[i]]
                    if (lab == lab[i]).sum() < 2:
                        sc.append(0.0); continue
                    a_ = same.sum() / (len(same) - 1)
                    b_ = min(D[i, lab == o].mean() for o in set(lab) if o != lab[i]) if len(set(lab)) > 1 else 0
                    sc.append((b_ - a_) / max(a_, b_, 1e-6))
                return float(np.mean(sc))
            best = None
            for kk in range(2, min(12, n) + 1):
                lab = fcluster(Z, kk, "maxclust")
                if len(set(lab)) < kk:
                    continue
                sil = silhouette(lab)
                if best is None or sil > best[0] + 0.01:
                    best = (sil, lab)
            labels = best[1] if best and best[0] > 0.25 else np.ones(n, int)  # weak structure: one class
            # near misses (a fragment with one stroke missing) hide inside a class: split a class in two when the
            # two halves are separated by a clear gap (every cross pair farther apart than any pair within a half)
            labels = np.array(labels)
            for lab_ in sorted(set(labels)):
                idx = np.nonzero(labels == lab_)[0]
                if len(idx) < 3:
                    continue
                sub_d = DH[np.ix_(idx, idx)]
                med = idx[int(np.argmin(sub_d.sum(axis=1)))]  # medoid = the typical member
                mm = feats_hr[ink[med][0]]
                pm = prep(mm)

                def stroke_gap(f):
                    """Largest local ink difference after the best small rotation and 1-px shift: ~0.2-0.5 for the same
                    fragment drawn at another tilt, ~0.8+ when a stroke is missing or added."""
                    ang = max(range(-12, 13, 2), key=lambda a_: float((prep(rot(f, a_)) * pm).sum()))
                    rf = rot(f, ang)
                    return min(float(cv2.GaussianBlur(np.abs(np.roll(np.roll(rf, dy, 0), dx, 1) - mm), (0, 0), 1.5).max())
                               for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                outl = [i for i in idx if i != med and stroke_gap(feats_hr[ink[i][0]]) > 0.72]
                if outl and len(outl) <= 0.6 * len(idx):
                    labels[np.array(outl)] = labels.max() + 1
            order = {}
            for (k, f), lab in zip(ink, labels):
                if lab not in order:
                    order[lab] = len(order); reps.append((f, k))
                classes[k] = chr(65 + order[lab])
        elif ink:
            classes[ink[0][0]] = "A"; reps.append((ink[0][1], ink[0][0]))
        # highlighted cells: ring colour far from the grid's typical ring
        F = np.array([cells[k]["feat"] for k in cells])
        med = np.median(F, axis=0); mad = np.median(np.abs(F - med), axis=0) * 1.4826 + 6.0
        score = (np.abs(F - med) / mad).max(axis=1)
        # a coloured rim on pale tiles (a cyan start ring on cream cards) is a small mean shift but a clear share of
        # saturated, bright rim pixels
        sf = np.array([cells[k]["satfrac"] for k in cells]); sf_med = float(np.median(sf))
        for (k, sc), f_ in zip(zip(cells, score), sf):
            cells[k]["highlight"] = bool(sc > 5.0 or (f_ > 0.12 and f_ > sf_med + 0.10))
        # group highlighted cells by colour: a lone odd-coloured cell is the marked start, a same-coloured run is "lit"
        hk = [k for k in cells if cells[k]["highlight"]]
        parent = {k: k for k in hk}
        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]; k = parent[k]
            return k
        def hue_close(a, b):
            ha, hb = cells[a]["hue_band"], cells[b]["hue_band"]
            if ha < 0 or hb < 0:
                return ha < 0 and hb < 0
            d = abs(ha - hb); return min(d, 180 - d) <= 20
        for i, a in enumerate(hk):  # same colour AND nearby (lit paths are runs of neighbouring tiles)
            for b in hk[i + 1:]:
                if hue_close(a, b) and (abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 2 or ((a[0] == b[0] or a[1] == b[1]) and abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 4)):
                    parent[find(a)] = find(b)
        groups = {}
        for k in hk:
            groups.setdefault(find(k), []).append(k)
        for k in cells:
            cells[k]["mark"] = ""
        for ks in groups.values():
            for k in ks:
                cells[k]["mark"] = "start?" if len(ks) == 1 else "lit"
        # several lone highlights: the route escapes through the top, so the start is the one nearest the bottom;
        # the others are single lit tiles (a lit decoy can be one tile long)
        lone = sorted([k for k in cells if cells[k]["mark"] == "start?"], key=lambda k: (-k[0], k[1]))
        for k in lone[1:]:
            cells[k]["mark"] = "lit"
        # HEADERED grid (G8 style): empty/odd corner, a styled first row (column labels) and first column (row labels)
        header = False
        if R >= 3 and C >= 3:
            # compare the first row + first column directly against the interior (don't rely on outlier flags: in a
            # small grid the headers are too large a share of cells to be outliers)
            Hs = np.array([cells[(0, c)]["feat"] for c in range(1, C)] + [cells[(r, 0)]["feat"] for r in range(1, R)])
            Is = np.array([cells[(r, c)]["feat"] for r in range(1, R) for c in range(1, C)])
            sep = np.abs(Hs.mean(axis=0) - Is.mean(axis=0)) / (np.sqrt((Hs.std(axis=0) ** 2 + Is.std(axis=0) ** 2) / 2) + 4.0)
            corner_blank = cells[(0, 0)]["inferred"] or cells[(0, 0)]["empty"]
            if corner_blank and sep.max() > 2.5:
                header = True
                for k in cells:
                    cells[k]["mark"] = "header" if (k[0] == 0 or k[1] == 0) else ""
        # sample sheet: one exemplar per class
        if reps:
            tiles = []
            for li, (_, key) in enumerate(reps):
                cr = dict(crops)[key]
                t = cv2.resize(cr, (72, 72)); t = cv2.copyMakeBorder(t, 18, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
                cv2.putText(t, f"{chr(65 + li)}  r{key[0] + 1}c{key[1] + 1}", (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
                tiles.append(t)
            cv2.imwrite(os.path.join(out, f"classes{gi}.png"), np.hstack(tiles))
        # second pass for text cells OCR missed (single letters are often skipped by full-screen OCR)
        missing = [k for k in cells if not cells[k]["text"].strip() and not cells[k]["empty"]]
        read_ = [cells[k]["text"].strip() for k in cells if cells[k]["text"].strip()]
        letterish = [t for t in read_ if len(t) == 1 and t.isalpha()]
        # only for LETTER grids (mostly single letters, varied): symbol sets OCR half-reads (II, IV, Σ→E) must stay symbols
        if missing and len(read_) >= 0.4 * len(cells) and len(letterish) >= 0.8 * len(read_) and len(set(letterish)) >= 5:
            W_, H_ = W, H
            bxs = [(int(cells[k]["box"][0] * W_), int(cells[k]["box"][1] * H_), int((cells[k]["box"][2] - cells[k]["box"][0]) * W_), int((cells[k]["box"][3] - cells[k]["box"][1]) * H_)) for k in missing]
            for k, ch in zip(missing, reread(img, bxs)):
                if ch:
                    cells[k]["text"] = ch
            known = [(cells[k]["text"].strip(), dict(feats)[k]) for k in cells if len(cells[k]["text"].strip()) == 1 and cells[k]["text"].strip().isalpha()]
            order_ = [(r, c) for r in range(R) for c in range(C)]
            seq_ = [cells[k]["text"].strip().upper() for k in order_]
            alphabetical = sum(1 for i, t in enumerate(seq_) if len(t) == 1 and i < 26 and t == chr(65 + i)) >= 5
            for k in ([] if alphabetical else missing):  # trays: the A-B-C inference below fills them instead
                if not cells[k]["text"].strip():
                    ch = match_letter(dict(feats)[k], known)
                    if ch:
                        cells[k]["text"] = ch + "~"  # ~ = matched by shape, not read
        texts = [cells[k]["text"].strip() for k in cells if cells[k]["text"].strip()]
        # text grid = varied readings (letters, words). A few repeating one-character readings are symbols that OCR
        # happens to recognise (Σ → "E", arrows…): keep classifying those as symbols.
        has_text = len(texts) >= 0.5 * len(cells) and len(set(texts)) > 6
        if header:
            has_text = True
        # keyboards/trays: if most single letters follow A, B, C… in reading order, fill the unread keys from the sequence
        order = [(r, c) for r in range(R) for c in range(C)]
        seq = [cells[k]["text"].strip().upper() for k in order]
        hits = sum(1 for i, t in enumerate(seq) if len(t) == 1 and i < 26 and t == chr(65 + i))
        if has_text and hits >= 0.5 * sum(1 for t in seq if len(t) == 1) and hits >= 5:
            for i, k in enumerate(order):
                if i < 26 and not cells[k]["text"]:
                    cells[k]["text"] = chr(65 + i) + "~"  # ~ = inferred, not read
        print(f"GRID {gi}: {R} rows × {C} cols, tile ≈ {s / W:.3f} of width · {'text' if has_text else 'symbols'}")
        for r in range(R):
            row = []
            for c in range(C):
                k = (r, c); t = cells[k]["text"] if has_text else classes[k]
                t = t or ("_" if cells[k]["empty"] else "?")
                row.append(t + ("*" if cells[k]["highlight"] else ""))
            print("   " + " ".join(f"{x:>3}" for x in row))
        if header:
            lab = lambda k: (cells[k]["text"].strip() or f"icon@r{k[0] + 1}c{k[1] + 1}")
            col_labels = [lab((0, c)) for c in range(1, C)]
            row_labels = [lab((r, 0)) for r in range(1, R)]
            seats = "/".join("".join((cells[(r, c)]["text"].strip()[:1] or ("_" if cells[(r, c)]["empty"] else "?")) for c in range(1, C)) for r in range(1, R))
            print(f"   HEADERED GRID (labels + fixed letter seats; G8 style): column labels (current order): {', '.join(col_labels)}")
            print(f"   row labels (current order, top→bottom): {', '.join(row_labels)}")
            print(f"   seats: {seats}   (_ = blank = space, ? = unread: check by eye)")
            print(f'   → python3 tools/grid.py message --seats "{seats}" --rows "{",".join(row_labels)}" --cols "{",".join(col_labels)}" --want-rows "…" --want-cols "…" --coords "…"')
        single = [f"r{k[0] + 1}c{k[1] + 1}" for k in cells if cells[k]["mark"] == "start?"]
        lit = [f"r{k[0] + 1}c{k[1] + 1}" for k in cells if cells[k]["mark"] == "lit"]
        if single:
            print(f"   * highlighted: {', '.join(single)}" + ("  (a lone marked tile: usually the START)" if len(single) == 1 else ""))
        if lit:
            print(f"   * lit group ({len(lit)} same-coloured tiles): {', '.join(lit)}  (a lit/suggested path; may be a trap)")
        if reps and not has_text:
            print(f"   symbol classes: {len(reps)} → identify each once in {os.path.join(out, f'classes{gi}.png')}")
            hints = {}
            for k in cells:
                t = cells[k]["text"].strip()
                if t and classes[k] not in "_":
                    hints.setdefault(classes[k], {}).setdefault(t, 0); hints[classes[k]][t] += 1
            if hints:
                print("   OCR reads the classes as: " + ", ".join(f"{c}={max(m, key=m.get)!r}" for c, m in sorted(hints.items())) + "  (a hint: trust the samples)")
        print(f"   cell centre x (cols): {', '.join(f'{x / W:.3f}' for x in g['xs'])}")
        print(f"   cell centre y (rows): {', '.join(f'{y / H:.3f}' for y in g['ys'])}")
        result.append({"rows": R, "cols": C, "text": has_text, "headered": header,
                       "cells": [[{**{kk: vv for kk, vv in cells[(r, c)].items() if kk not in ("feat", "hue_band")}, "class": classes[(r, c)]} for c in range(C)] for r in range(R)]})
        if not header and all(classes.get(k) for k in cells):
            try:
                bxs = [cells[k]["box"] for k in cells]
                gb = (min(b[0] for b in bxs) * W, min(b[1] for b in bxs) * H, max(b[2] for b in bxs) * W, max(b[3] for b in bxs) * H)
                km = key_card(img, lines, gb, classes, feats_hr, cells, R, C)
            except Exception as e:  # never let the key matcher break the read
                km = None
            if km and km[0]:
                mapping, none_, rep = km
                print(f"   KEY CARD matched: {', '.join(f'{c}={m}' for c, m in sorted(mapping.items()))}"
                      + (f"; no key glyph (near misses, encode nothing): {', '.join(none_)}" if none_ else "") + f"   [{rep}]")
                result[-1]["key"] = mapping
                st_ = [k for k in cells if cells[k].get("mark") == "start?"]
                if len(st_) == 1:
                    import types
                    ns = types.SimpleNamespace(relative=False, pipes=False, heading="UP", exit="top")
                    gridc = [[classes[(r, c)] for c in range(C)] for r in range(R)]  # by glyph class, also on letter-like tiles
                    route, outc = walk(gridc, mapping, st_[0][0], st_[0][1], ns)
                    if outc.startswith("EXIT top"):
                        lit_on = [k for k in route if cells[k].get("mark") == "lit"]
                        print(f"   KEY ROUTE → top exit r{route[-1][0] + 1}c{route[-1][1] + 1} ({len(route)} cells, 1-based row,col): "
                              + " → ".join(f"({r + 1},{c + 1})" for r, c in route)
                              + (f"   WARNING: uses {len(lit_on)} lit tile(s)" if lit_on else ""))
                        for (r, c) in route:
                            b = cells[(r, c)]["box"]
                            print(f'   <step do="click" at="{b[0]:.3f},{b[1]:.3f},{b[2]:.3f},{b[3]:.3f}">Mark row {r + 1}, col {c + 1}</step>')
                    else:
                        print(f"   KEY ROUTE: following the matched key from the start: {outc} (re-check the key)")
    # text-entry fields (answer boxes that OCR can't see because they're empty)
    fields = [f for f in input_fields(img, lines) if not any(w in f[4].upper() for w in ("CONTINUE", "BACK TO", "OPEN THE", "CLOSE THE", "SUBMIT", "CHECK"))]
    if fields:
        print("INPUT FIELDS (click here, then type): " + "; ".join(
            f"{i + 1}: {x / W:.3f},{y / H:.3f},{(x + w) / W:.3f},{(y + h) / H:.3f}" + (f" [{t}]" if t else "") for i, (x, y, w, h, t) in enumerate(fields)))
        result.append({"inputs": [[round(x / W, 4), round(y / H, 4), round((x + w) / W, 4), round((y + h) / H, 4), t] for (x, y, w, h, t) in fields]})
    # lines of marker tiles (G8 row markers / column headers): exact boxes for drag steps
    used = [b for g in grids[:4] for b in g["filled"].values()]
    for ln in tile_lines(square_boxes(img), used):
        bs = ln["boxes"]
        txt = [" ".join(t for (x0, y0, x1, y1, t) in lines if b[0] <= (x0 + x1) / 2 * W <= b[0] + b[2] and b[1] <= (y0 + y1) / 2 * H <= b[1] + b[3]) for b in bs]
        feats = [glyph(img, b) for b in bs]
        kind = "row of" if ln["orient"] == "h" else "column of"
        labels = [t if t else f"icon{i + 1}" for i, t in enumerate(txt)]
        print(f"MARKERS: {kind} {len(bs)} tiles: " + " | ".join(labels) + "   boxes: " +
              "; ".join(f"{b[0] / W:.3f},{b[1] / H:.3f},{(b[0] + b[2]) / W:.3f},{(b[1] + b[3]) / H:.3f}" for b in bs))
        if any(not t for t in txt):
            sheet = np.hstack([cv2.resize(f[1], (64, 64)) for f in feats])
            fn = os.path.join(out, f"markers_{ln['orient']}_{len(bs)}.png"); cv2.imwrite(fn, sheet)
            print(f"   icons (left→right / top→bottom): {fn}")
        result.append({"markers": ln["orient"], "labels": labels, "boxes": [[round(b[0] / W, 4), round(b[1] / H, 4), round((b[0] + b[2]) / W, 4), round((b[1] + b[3]) / H, 4)] for b in bs]})
    json.dump(result, open(os.path.join(out, "grid.json"), "w"), indent=1)
    print(f"\nJSON (for route/message): {os.path.join(out, 'grid.json')}")


# ---------------------------------------------------------------------------------------------------------- route
DIRS = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1), "U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1),
        "N": (-1, 0), "S": (1, 0), "W": (0, -1), "E": (0, 1),
        "UPLEFT": (-1, -1), "UPRIGHT": (-1, 1), "DOWNLEFT": (1, -1), "DOWNRIGHT": (1, 1),
        "UL": (-1, -1), "UR": (-1, 1), "DL": (1, -1), "DR": (1, 1), "NW": (-1, -1), "NE": (-1, 1), "SW": (1, -1), "SE": (1, 1)}
TURNS = {"STRAIGHT": 0, "FORWARD": 0, "AHEAD": 0, "F": 0, "S": 0, "LEFT": -1, "L": -1, "RIGHT": 1, "R": 1, "BACK": 2, "B": 2,
         "UTURN": 2}
HEAD = [(-1, 0), (0, 1), (1, 0), (0, -1)]  # clockwise from UP
# pipe tiles: which sides are open (U, R, D, L)
PIPES = {"┃": "UD", "│": "UD", "║": "UD", "━": "LR", "─": "LR", "═": "LR", "┏": "RD", "┌": "RD", "╔": "RD",
         "┓": "LD", "┐": "LD", "╗": "LD", "┗": "UR", "└": "UR", "╚": "UR", "┛": "UL", "┘": "UL", "╝": "UL",
         "╋": "UDLR", "┼": "UDLR", "╬": "UDLR", "┣": "UDR", "├": "UDR", "┫": "UDL", "┤": "UDL", "┳": "LRD", "┬": "LRD",
         "┻": "LRU", "┴": "LRU"}
SIDE = {"U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1)}
OPP = {"U": "D", "D": "U", "L": "R", "R": "L"}


def parse_move(v):
    import re
    """'UP' | 'UP2' | '2UP' | 'UR' | 'LEFT' (relative) -> (name, count)."""
    v = v.upper().replace(" ", "").replace("-", "")
    m = re.match(r"^(\d*)([A-Z]+)(\d*)$", v)
    if not m:
        return v, 1
    return m.group(2), int(m.group(1) or m.group(3) or 1)


def walk(grid, key, r, c, a, entry=None):
    """Follow one route. Returns (route, outcome) where outcome is 'EXIT <edge> from rXcY', 'LOOP', or an error."""
    R, C = len(grid), len(grid[0])
    heading = HEAD.index(DIRS[a.heading.upper()]) if a.relative else None
    came = entry  # pipes: side we entered from
    route, seen = [], set()
    while True:
        state = (r, c, heading if a.relative else None, came if a.pipes else None)
        if state in seen:
            return route, f"LOOP at r{r + 1}c{c + 1}"
        seen.add(state); route.append((r, c))
        sym = grid[r][c]
        if a.pipes:
            opens = PIPES.get(sym) or key.get(sym, "")
            if not opens:
                return route, f"r{r + 1}c{c + 1}: {sym!r} is not a pipe"
            if came and came not in opens:
                return route, f"DEAD END: r{r + 1}c{c + 1} {sym!r} has no opening on side {came}"
            outs = [x for x in opens if x != came]
            if came and OPP[came] in outs:
                go = OPP[came]  # crossings: go straight through
            elif len(outs) == 1 or not came:
                go = outs[0] if came else ("U" if "U" in opens else outs[0])
            else:
                return route, f"FORK at r{r + 1}c{c + 1} {sym!r}: exits {outs}"
            dr, dc = SIDE[go]; n = 1; came = OPP[go]
        else:
            v = key.get(sym) or key.get(sym.upper()) or key.get(sym.lower())
            if v is None:
                return route, f"r{r + 1}c{c + 1}: symbol {sym!r} is not in the key"
            name, n = parse_move(v)
            if a.relative and name in TURNS:
                heading = (heading + TURNS[name]) % 4
                dr, dc = HEAD[heading]
            elif name in DIRS:
                dr, dc = DIRS[name]
                if a.relative and (dr, dc) in HEAD:
                    heading = HEAD.index((dr, dc))
            else:
                return route, f"r{r + 1}c{c + 1}: move {v!r} not understood"
        nr, nc = r + dr * n, c + dc * n
        if not (0 <= nr < R and 0 <= nc < C):
            edge = "top" if nr < 0 else "bottom" if nr >= R else "left" if nc < 0 else "right"
            return route, f"EXIT {edge} from r{r + 1}c{c + 1}"
        r, c = nr, nc


def cmd_route(a):
    key = {}
    for kv in a.key.replace(";", ",").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            key[k.strip()] = v.strip().upper()
    boxes, letters = None, None
    if a.json:
        G = json.load(open(a.json))
        g = G[a.grid - 1]
        grid = [[(c["text"] if g["text"] else c["class"]) for c in row] for row in g["cells"]]
        if g["text"] and all(c.get("class") for row in g["cells"] for c in row):
            # letter-like symbols (Roman numerals, runes): OCR per tile is noisy (stray corner letters, 1 for I, blanks),
            # but the glyph classes are clean -> give each class its majority OCR reading
            def norm(t):
                toks = [x for x in t.replace("|", "I").split() if x]
                t = max(toks, key=len) if toks else ""
                return t.replace("1", "I").replace("l", "I").upper() if not t.isdigit() or len(t) == 1 else t
            votes = collections.defaultdict(collections.Counter)
            for row in g["cells"]:
                for c in row:
                    if c["text"].strip():
                        votes[c["class"]][norm(c["text"])] += 1
            cls_text = {k: v.most_common(1)[0][0] for k, v in votes.items()}
            keyed = lambda t: t in key or t.upper() in key
            if cls_text and sum(keyed(t) for t in cls_text.values()) >= len(cls_text) / 2:
                grid = [[cls_text.get(c["class"], c["text"]) for c in row] for row in g["cells"]]
        boxes = [[c["box"] for c in row] for row in g["cells"]]
        hl = [(r, c) for r, row in enumerate(g["cells"]) for c, cell in enumerate(row) if cell.get("mark") == "start?"] or \
             [(r, c) for r, row in enumerate(g["cells"]) for c, cell in enumerate(row) if cell.get("highlight")]
    else:
        grid = [list(row.strip()) if " " not in row.strip() else row.split() for row in a.cells.split("/")]
        hl = []
    if a.letters:
        letters = [list(row.strip()) if " " not in row.strip() else row.split() for row in a.letters.split("/")]
    R, C = len(grid), len(grid[0])
    if a.start and a.start not in ("bottom", "edges", "all"):
        starts = [tuple(int(x) - 1 for x in st.split(",")) for st in a.start.replace(" ", "").split(";") if st]
    elif a.start == "bottom":
        starts = [(R - 1, c) for c in range(C)]
    elif a.start == "edges":
        starts = sorted({(r, c) for r in range(R) for c in range(C) if r in (0, R - 1) or c in (0, C - 1)})
    elif a.start == "all":
        starts = [(r, c) for r in range(R) for c in range(C)]
    elif hl:
        starts = hl if len(hl) <= 6 else [hl[0]]  # several marked candidates: try each
        if a.json:  # marked tiles on the same edge as the start are candidate starts too (only one should escape)
            (sr, sc) = starts[0]
            same = [(r, c) for r, row in enumerate(g["cells"]) for c, cell in enumerate(row) if cell.get("highlight") and (r, c) != (sr, sc)
                    and ((r == sr and sr in (0, R - 1)) or (c == sc and sc in (0, C - 1)))]
            if 0 < len(same) <= 5:
                starts = [(sr, sc)] + same
    else:
        sys.exit("no --start and no highlighted cell (try --start bottom)")
    good = []
    for (r, c) in starts:
        entry = None
        if a.pipes:  # enter from the edge opposite the exit
            entry = {"top": "D", "bottom": "U", "left": "R", "right": "L"}.get(a.exit)
        route, out = walk(grid, key, r, c, a, entry)
        ok = out.startswith("EXIT") and (a.exit == "any" or out.split()[1] == a.exit)
        if len(starts) > 1:
            print(f"start r{r + 1}c{c + 1}: {out} after {len(route)} cells{'   <-- ESCAPES' if ok else ''}")
        if ok or len(starts) == 1:
            good.append((route, out, ok))
    if len(starts) > 1:
        print(f"{sum(1 for g in good if g[2])} start(s) escape through the {a.exit} edge")
    for route, out, ok in good[:3]:
        if len(starts) == 1:
            print(("EXITS " if ok else f"{out.upper()} (expected {a.exit}) ") + (out[5:] if ok else ""))
        print(f"ROUTE ({len(route)} cells, 1-based row,col): " + " → ".join(f"({r + 1},{c + 1})" for r, c in route))
        if letters:
            print("SPELLS: " + "".join(letters[r][c] for r, c in route if letters[r][c] not in "._"))
        elif a.json and not G[a.grid - 1]["text"] and any(gg.get("text") and gg.get("rows") == R and gg.get("cols") == C for gg in G):
            tg = next(gg for gg in G if gg.get("text") and gg.get("rows") == R and gg.get("cols") == C)
            print("SPELLS (text grid of the same size): " + "".join(tg["cells"][r][c]["text"] for r, c in route))
        if boxes:
            print("STEPS (the start is usually pre-marked; skip it if so):")
            for i, (r, c) in enumerate(route):
                b = boxes[r][c]
                print(f'<step do="click" at="{b[0]:.3f},{b[1]:.3f},{b[2]:.3f},{b[3]:.3f}">Mark row {r + 1}, col {c + 1}</step>')


# -------------------------------------------------------------------------------------------------------- message
def cmd_message(a):
    seats = [list(r) for r in a.seats.split("/")]
    rows = [x.strip() for x in a.rows.split(",")]
    cols = [x.strip() for x in a.cols.split(",")]
    wr = [x.strip() for x in a.want_rows.split(",")]
    wc = [x.strip() for x in a.want_cols.split(",")]
    coords = [tuple(x.split(":")) for x in a.coords.split()]
    def read(order_r, order_c):
        out = ""
        for rl, cl in coords:
            ch = seats[order_r.index(rl)][order_c.index(cl)]
            out += " " if ch in "_ ." else ch
        return out
    if a.move == "carry":  # seats were read in the CURRENT order and travel with their labels
        print(f"TRANSMISSION: {read(rows, cols)!r} (same in any arrangement)")
    else:
        print(f"TRANSMISSION (after arranging): {read(wr, wc)!r}")
        print(f"(reading WITHOUT rearranging gives {read(rows, cols)!r}: the trap)")
    if a.move == "carry":
        print("CARRY mode: letters move with their markers, so every arrangement reads the same text; arrange only for grading.")
    for name, cur, want in (("ROW", rows, wr), ("COLUMN", cols, wc)):
        cur = cur[:]; moves = []
        for i, lab in enumerate(want):
            j = cur.index(lab)
            if j != i:
                if a.move == "insert":  # drag lab from position j and drop it at position i (others shift)
                    x = cur.pop(j); cur.insert(i, x)
                    moves.append(f"drag {lab} (position {j + 1}) to position {i + 1} → order becomes {','.join(cur)}")
                else:
                    cur[i], cur[j] = cur[j], cur[i]
                    moves.append(f"{'swap' if a.move == 'swap' else 'swap (carry)'} {lab} (position {j + 1}) with the marker at position {i + 1} → order becomes {','.join(cur)}")
        print(f"{name} MOVES (current {','.join(rows if name == 'ROW' else cols)} → target {','.join(want)}):")
        print("   " + ("\n   ".join(moves) if moves else "none (already in order)"))
    print("Swaps are toggles: doing one twice undoes it. After moving markers, LOOK at the board and re-run this command")
    print("with the order you actually see; never re-issue a move you can't see is still needed. Some engines insert instead")
    print("of swapping on drop: the order on screen is what counts.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("read"); p.add_argument("image"); p.add_argument("--out"); p.set_defaults(fn=cmd_read)
    p = sp.add_parser("route"); p.add_argument("--json"); p.add_argument("--grid", type=int, default=1); p.add_argument("--cells")
    p.add_argument("--key", default="", help="SYM=MOVE,...  MOVE: UP/DOWN/LEFT/RIGHT, diagonals UL/UR/DL/DR, counts UP2, or with --relative LEFT/RIGHT/STRAIGHT/BACK")
    p.add_argument("--start", help="r,c (1-based) | 'r,c;r,c' candidates | bottom | edges | all  (default: the highlighted tile)")
    p.add_argument("--exit", default="top", help="top|bottom|left|right|any")
    p.add_argument("--relative", action="store_true", help="symbols are turns relative to the current heading")
    p.add_argument("--heading", default="UP", help="initial heading for --relative")
    p.add_argument("--pipes", action="store_true", help="tiles are pipe pieces (┃━┏┓┗┛╋…; or key SYM=UD/LR/RD/…)")
    p.add_argument("--letters", help="parallel letter grid 'ABC/DEF' to spell along the route")
    p.set_defaults(fn=cmd_route)
    p = sp.add_parser("message")
    for k in ("seats", "rows", "cols", "want-rows", "want-cols", "coords"):
        p.add_argument("--" + k, required=True)
    p.add_argument("--move", choices=["swap", "insert", "carry"], default="swap", help="what dropping a marker does on this engine")
    p.set_defaults(fn=cmd_message)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
