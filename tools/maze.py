#!/usr/bin/env python3
"""Maze / tunnel reader + solver: "walk the space between the walls".

Reads a screenshot of a grid maze, decides which sides of every cell are open (floor) or closed (wall/rock),
then finds the way from the start to the exit edge.

  maze.py IMG                         auto: tile grid via grid.py (tunnel tiles / cards) or a drawn maze (walls)
  maze.py IMG --rows 7 --cols 5       drawn maze: give the size (the bounding box is found automatically)
  maze.py IMG --box x0,y0,x1,y1       drawn maze: give the maze rectangle (pixels or 0-1 fractions)
  maze.py IMG --start 7,3             1-based row,col (default: the glowing tile)
  maze.py IMG --exit top|bottom|left|right|any
Prints the map it read (check it against the screen!), every reachable exit, the route, dead-end lit corridors,
and <step> click lines with exact boxes. Exactly one reachable exit = "one way out".
"""
import argparse, collections, json, os, subprocess, sys, tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIDES = {"U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1)}


def _unused_tile_grid(img_path):
    """Use grid.py's tile detector. Returns (cells[r][c] = (x0,y0,x1,y1) px, json-grid) or None."""
    out = tempfile.mkdtemp()
    subprocess.run([sys.executable, os.path.join(HERE, "grid.py"), "read", img_path, "--out", out], capture_output=True)
    try:
        G = json.load(open(os.path.join(out, "grid.json")))
    except Exception:
        return None
    G = [g for g in G if g.get("cells") and g.get("rows", 0) * g.get("cols", 0) >= 9]
    if not G:
        return None
    g = max(G, key=lambda g: g["rows"] * g["cols"])
    return g


def lab(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)


def board_box(img):
    """Bounding box of the board: the largest blob of dense edges (tiles, walls, corridors) after closing small gaps."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    e = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 12, 36)
    k = max(5, int(min(H, W) * 0.012))
    m = cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    m = cv2.dilate(m, np.ones((k, k), np.uint8))
    n, lab_, st, _ = cv2.connectedComponentsWithStats(m, 8)
    cand = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if w < 0.12 * W or h < 0.12 * H or w > 0.97 * W or h > 0.97 * H:
            continue
        cand.append((x, y, x + w, y + h))
    # A pan/zoom viewport draws a frame around the board with padding inside it; that frame is its own component,
    # and it beats the board on area alone. Any candidate that merely encloses a smaller one is such a frame.
    def encloses(a, b):
        return (a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]
                and (b[2] - b[0]) * (b[3] - b[1]) < 0.9 * (a[2] - a[0]) * (a[3] - a[1]))
    inner = [a for a in cand if not any(encloses(a, b) for b in cand if b is not a)]
    best = None
    for (x, y, X, Y) in (inner or cand):
        w, h = X - x, Y - y
        dens = (e[y:Y, x:X] > 0).mean()
        score = w * h * (0.5 + dens * 5)
        if best is None or score > best[0]:
            best = (score, (x, y, X, Y))
    if not best:
        return None
    x0, y0, x1, y1 = best[1]
    # Shrink the dilation halo back to the outermost edge pixels...
    sub = e[y0:y1, x0:x1] > 0

    ys = np.nonzero(sub.mean(axis=1) > 0.02)[0]; xs = np.nonzero(sub.mean(axis=0) > 0.02)[0]
    if len(xs) and len(ys):
        x0, x1, y0, y1 = x0 + xs[0], x0 + xs[-1] + 1, y0 + ys[0], y0 + ys[-1] + 1
    return x0, y0, x1, y1


def _period_scores(img, box, axis):
    """Autocorrelation of the edge profile: score[k] = how well a period of extent/k (and twice it) repeats."""
    x0, y0, x1, y1 = box
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    grad = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1)) if axis == 0 else np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    prof = grad.mean(axis=1) if axis == 0 else grad.mean(axis=0)
    prof = prof - prof.mean(); n = len(prof)
    ac = np.correlate(prof, prof, "full")[n - 1:] / np.arange(n, 0, -1)
    ac = ac / (ac[0] + 1e-6)

    def at(lag):
        lo, hi = int(lag * 0.97), int(np.ceil(lag * 1.03)) + 1
        return ac[lo:hi].max()
    sc = {}
    for k in range(2, 30):
        lag = n / k
        if lag < 14:
            break
        v2 = at(2 * lag) if 2 * lag < 0.75 * n else None  # a true period repeats at twice the lag too
        sc[k] = min(at(lag), v2) if v2 is not None else at(lag)
    return sc


def count_grid(img, box):
    """(rows, cols): the finest periods that repeat well on both axes and give near-square cells."""
    sr, sc = _period_scores(img, box, 0), _period_scores(img, box, 1)
    H, W = box[3] - box[1], box[2] - box[0]
    tr, tc = max(sr.values()), max(sc.values())
    Rs = [r for r, v in sr.items() if v >= 0.5 * tr]; Cs = [c for c, v in sc.items() if v >= 0.5 * tc]
    ok = [(r + c, r, c) for r in Rs for c in Cs if abs(np.log((W / c) / (H / r))) < 0.07]
    if ok:
        return max(ok)[1:]
    return max(r for r, v in sr.items() if v >= 0.6 * tr), max(c for c, v in sc.items() if v >= 0.6 * tc)


def ring_sat(img, b):
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    m = max(2, int(min(w, h) * 0.08))
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV).astype(np.float32)
    ring = np.ones((h, w), bool); ring[m:h - m, m:w - m] = False
    return hsv[..., 1][ring].mean(), np.median(hsv[..., 0][ring][hsv[..., 1][ring] > 60]) if (hsv[..., 1][ring] > 60).any() else -1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("img")
    ap.add_argument("--rows", type=int); ap.add_argument("--cols", type=int)
    ap.add_argument("--box", help="x0,y0,x1,y1 of the maze (px or 0-1)")
    ap.add_argument("--start", help="r,c 1-based (default: glowing tile)")
    ap.add_argument("--exit", default="top")
    ap.add_argument("--mode", choices=["auto", "tiles", "walls"], default="auto")
    ap.add_argument("--debug", help="write an overlay PNG here")
    a = ap.parse_args()
    img = cv2.imread(a.img)
    if img is None:
        sys.exit("cannot read " + a.img)
    H, W = img.shape[:2]

    cells, start, lit = None, None, set()
    if a.box:
        v = [float(x) for x in a.box.split(",")]
        if max(v) <= 1.0:
            v = [v[0] * W, v[1] * H, v[2] * W, v[3] * H]
        box = tuple(int(round(x)) for x in v)
    else:
        box = board_box(img)
        if not box:
            sys.exit("no board found; pass --box x0,y0,x1,y1 and --rows/--cols")
    if a.rows and a.cols:
        R, C = a.rows, a.cols
    else:
        R, C = count_grid(img, box)
        R, C = a.rows or R, a.cols or C
    if not R or not C:
        sys.exit("could not count rows/cols; pass --rows/--cols")
    x0, y0, x1, y1 = box
    ch, cw = (y1 - y0) / R, (x1 - x0) / C
    # separate tiles (a gap of background between them) or one drawn maze?
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = np.median(np.concatenate([gray[y0:y1, max(0, x0 - 12):max(1, x0 - 4)].ravel(), gray[y0:y1, x1 + 4:x1 + 12].ravel()]))
    gapcols = [gray[y0:y1, int(x0 + c * cw) - 2:int(x0 + c * cw) + 3] for c in range(1, C)]
    gapfrac = np.mean([(np.abs(gc - bg) < 12).mean() for gc in gapcols]) if gapcols else 0
    mode = a.mode if a.mode != "auto" else ("tiles" if gapfrac > 0.5 else "walls")
    if mode == "tiles":  # trim the gap from each cell
        gp = max(2, int(min(ch, cw) * 0.05))
        cells = [[(int(x0 + c * cw) + gp, int(y0 + r * ch) + gp, int(x0 + (c + 1) * cw) - gp, int(y0 + (r + 1) * ch) - gp) for c in range(C)] for r in range(R)]
    else:
        cells = [[(int(x0 + c * cw), int(y0 + r * ch), int(x0 + (c + 1) * cw), int(y0 + (r + 1) * ch)) for c in range(C)] for r in range(R)]
    R, C = len(cells), len(cells[0])

    # start: given, grid.py's lone marked tile, else the cell with the most saturated rim
    if a.start:
        start = tuple(int(x) - 1 for x in a.start.split(","))
    if start is None:
        # the glowing start / lit tiles: their rim colour stands out from the typical rim (Lab a,b + a bit of L)
        # glows (start ring, lit tiles) are drawn over the tile's outer band; corridors cross the band only near the
        # side midpoints, so read the band's four CORNER stretches. Cluster those colours: the big clusters are the
        # normal look (floor, wall, card), small clusters are glows; a lone glow = the start, a group = a lit path.
        Lall = lab(img)
        Lb = Lall[box[1]:box[3], box[0]:box[2]].reshape(-1, 3)
        smp = Lb[np.random.default_rng(1).choice(len(Lb), min(30000, len(Lb)), replace=False)]
        _, _, pal = cv2.kmeans(smp, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)

        def band(b_):
            """(share of tinted pixels, mean tint a/b) in the band's corner stretches; tint = colour minus nearest board colour."""
            x0_, y0_, x1_, y1_ = b_; w_, h_ = x1_ - x0_, y1_ - y0_
            i0, i1 = max(1, int(min(w_, h_) * 0.015)), max(3, int(min(w_, h_) * 0.055))
            mk = np.zeros((h_, w_), bool)
            mk[i0:h_ - i0, i0:w_ - i0] = True; mk[i1:h_ - i1, i1:w_ - i1] = False
            mk[:, int(w_ * 0.3):int(w_ * 0.7)] = False; mk[int(h_ * 0.3):int(h_ * 0.7), :] = False
            px = Lall[y0_:y1_, x0_:x1_][mk]
            d = np.stack([np.linalg.norm(px - p_, axis=1) for p_ in pal])
            near = pal[np.argmin(d, axis=0)]
            tint = (px - near) * np.array([0.25, 1.0, 1.0])  # lightness counts a quarter: glows mostly shift hue
            t = np.linalg.norm(tint, axis=1) > 8
            return t.mean(), (tint[t].mean(axis=0) if t.any() else np.zeros(3))
        info = {(r, c): band(cells[r][c]) for r in range(R) for c in range(C)}
        dist = {k: v[0] for k, v in info.items()}
        base = float(np.median(list(dist.values())))
        odd = sorted([k for k in dist if dist[k] > max(0.5, base + 0.3)], key=lambda k: -dist[k])
        groups = []
        def same(u, v):
            nu, nv = np.linalg.norm(u), np.linalg.norm(v)
            return nu > 0 and nv > 0 and float(np.dot(u, v) / (nu * nv)) > 0.8
        for k in odd:  # group glows of the same hue
            for gr in groups:
                if same(info[k][1], info[gr[0]][1]):
                    gr.append(k); break
            else:
                groups.append([k])
        lone = [g_[0] for g_ in groups if len(g_) == 1]
        if lone:
            start = max(lone, key=lambda k: (k[0], dist[k]))  # the lone glow nearest the bottom
        for g_ in groups:
            if len(g_) > 1:
                lit |= set(g_)
        if start is None:
            sys.exit("no glowing start tile found; pass --start r,c")
        lit.discard(start)

    # floor vs wall colours: floor = centre of the start cell; wall = the other k-means cluster
    L = lab(img)
    sx0, sy0, sx1, sy1 = cells[start[0]][start[1]]
    cx, cy, rr = (sx0 + sx1) // 2, (sy0 + sy1) // 2, max(2, (sx1 - sx0) // 12)
    floor = np.median(L[cy - rr:cy + rr + 1, cx - rr:cx + rr + 1].reshape(-1, 3), axis=0)
    gx0 = min(b[0] for row in cells for b in row); gy0 = min(b[1] for row in cells for b in row)
    gx1 = max(b[2] for row in cells for b in row); gy1 = max(b[3] for row in cells for b in row)
    region = L[gy0:gy1, gx0:gx1].reshape(-1, 3)
    samp = region[np.random.default_rng(0).choice(len(region), min(20000, len(region)), replace=False)]
    _, lab2, cent = cv2.kmeans(samp, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    wall = cent[int(np.argmax([np.linalg.norm(c - floor) for c in cent]))]
    dF = np.linalg.norm(L - floor, axis=2); dW = np.linalg.norm(L - wall, axis=2)
    sep = np.linalg.norm(floor - wall)
    abF = np.linalg.norm(L[..., 1:] - floor[1:], axis=2); abW = np.linalg.norm(L[..., 1:] - wall[1:], axis=2)
    # glows (cyan start, gold lit) change the hue: such pixels are neither floor nor wall
    lighter = floor[0] > wall[0]
    isfloor = (dF < dW) & (dF < 0.6 * sep) & (abF < 16)
    iswall = (dW < dF) & (dW < 0.6 * sep) & (abW < 16)
    glowing = set(lit) | {start}
    if mode == "tiles":
        # inside a glowing tile the colours shift: separate corridor from rock/card by LIGHTNESS within that tile
        Lc = L[..., 0]
        for (gr_, gc_) in glowing:
            bx0, by0, bx1, by1 = cells[gr_][gc_]
            t = Lc[by0:by1, bx0:bx1]
            lo, hi = np.percentile(t, 5), np.percentile(t, 95)
            if hi - lo <= 0.4 * abs(floor[0] - wall[0]):
                continue
            t8 = np.clip((t - lo) / max(1e-3, hi - lo) * 255, 0, 255).astype(np.uint8)
            o, _ = cv2.threshold(t8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            th = lo + o / 255.0 * (hi - lo)
            isfloor[by0:by1, bx0:bx1] = (t > th) if lighter else (t < th)
            iswall[by0:by1, bx0:bx1] = ~isfloor[by0:by1, bx0:bx1]
    # inside glowing tiles the colours shift; judge by lightness order instead of absolute colour
    lighter_floor = floor[0] > wall[0]

    def floor_frac(p, q, half):
        """Fraction of sample points from p to q where some pixel within +-half (perpendicular) is floor."""
        p, q = np.array(p, float), np.array(q, float)
        n = int(max(abs(q - p).max(), 2))
        d = (q - p) / np.linalg.norm(q - p); perp = np.array([-d[1], d[0]])
        ok = 0
        for t in np.linspace(0, 1, n):
            x, y = p + (q - p) * t
            hit = False
            for s in np.linspace(-half, half, max(3, int(2 * half) + 1)):
                xx, yy = int(round(x + perp[0] * s)), int(round(y + perp[1] * s))
                if 0 <= xx < W and 0 <= yy < H and isfloor[yy, xx]:
                    hit = True; break
            ok += hit
        return ok / float(n)

    def wall_free(p, q):
        """Walls mode: blocked if a run of wall-coloured pixels crosses the straight line p→q."""
        p, q = np.array(p, float), np.array(q, float)
        n = int(max(abs(q - p).max(), 2)); run = best = 0
        for t in np.linspace(0, 1, n):
            x, y = (p + (q - p) * t).round().astype(int)
            if 0 <= x < W and 0 <= y < H and iswall[y, x]:
                run += 1; best = max(best, run)
            else:
                run = 0
        return best < 2

    def centre(b):
        return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

    def side_open(r, c, s):
        b = cells[r][c]; cx, cy = centre(b); w, h = b[2] - b[0], b[3] - b[1]
        dr, dc = SIDES[s]
        if mode == "tiles":
            m = 0.07  # stop short of the tile's own border / rounded corner
            q = (cx + dc * w * (0.5 - m), cy + dr * h * (0.5 - m))
            if floor_frac((cx, cy), q, half=w * 0.07) < 0.88:
                return False
            if (r, c) not in glowing:
                return True
            # a corridor is a BAND with rock on both sides; a glow that lights the whole rim is not an opening
            narrow = 0
            for f in (0.30, 0.36, 0.42):
                px, py = cx + dc * w * f, cy + dr * h * f
                ax_, ay_ = (1, 0) if dr else (0, 1)  # perpendicular to the probe
                run = 0
                for sgn in (1, -1):
                    k = 0
                    while k < w * 0.5:
                        xx, yy = int(round(px + sgn * ax_ * k)), int(round(py + sgn * ay_ * k))
                        if not (0 <= xx < W and 0 <= yy < H) or not isfloor[yy, xx]:
                            break
                        k += 1
                    run += k
                narrow += run < 0.6 * (w if dr else h)
            return narrow >= 2
        # walls: cross the border line (plus a little) — a wall line blocks the whole crossing
        q = (cx + dc * (w * 0.5 + 3), cy + dr * (h * 0.5 + 3))
        p = (cx + dc * w * 0.25, cy + dr * h * 0.25)
        return wall_free(p, q)

    opens = [[{s for s in SIDES if side_open(r, c, s)} for c in range(C)] for r in range(R)]
    # an edge between two cells is open only if both cells agree (tiles), or the crossing is clear (walls: symmetric)
    def nbrs(r, c):
        for s, (dr, dc) in SIDES.items():
            rr, cc = r + dr, c + dc
            if 0 <= rr < R and 0 <= cc < C and s in opens[r][c] and {"U": "D", "D": "U", "L": "R", "R": "L"}[s] in opens[rr][cc]:
                yield rr, cc

    # map
    print(f"MAZE {R}x{C} ({mode}); start r{start[0] + 1}c{start[1] + 1}; floor is {'lighter' if lighter_floor else 'darker'} than walls")
    glyph = {frozenset(): "·", frozenset("U"): "╵", frozenset("D"): "╷", frozenset("L"): "╴", frozenset("R"): "╶",
             frozenset("UD"): "│", frozenset("LR"): "─", frozenset("DR"): "┌", frozenset("DL"): "┐", frozenset("UR"): "└",
             frozenset("UL"): "┘", frozenset("UDR"): "├", frozenset("UDL"): "┤", frozenset("DLR"): "┬", frozenset("ULR"): "┴",
             frozenset("UDLR"): "┼"}
    print("MAP (open sides per cell; S = start, * = lit; CHECK IT against the screen):")
    for r in range(R):
        print("   " + " ".join((glyph[frozenset(opens[r][c])] + ("S" if (r, c) == start else "*" if (r, c) in lit else " ")) for c in range(C)))

    # BFS
    prev = {start: None}; q = collections.deque([start])
    while q:
        cur = q.popleft()
        for nb in nbrs(*cur):
            if nb not in prev:
                prev[nb] = cur; q.append(nb)

    def path(t):
        p = []
        while t is not None:
            p.append(t); t = prev[t]
        return p[::-1]

    edges = {"top": [(0, c, "U") for c in range(C)], "bottom": [(R - 1, c, "D") for c in range(C)],
             "left": [(r, 0, "L") for r in range(R)], "right": [(r, C - 1, "R") for r in range(R)]}
    want = list(edges) if a.exit == "any" else [a.exit]
    exits_drawn = [(e, r, c) for e in edges for (r, c, s) in edges[e] if s in opens[r][c] and (r, c) != start]
    reach = [(e, r, c) for (e, r, c) in exits_drawn if (r, c) in prev and e in want]
    print(f"EXITS drawn: {', '.join(f'{e} r{r + 1}c{c + 1}' for e, r, c in exits_drawn) or 'none'}")
    if not reach:
        print("NO WAY OUT from the start with this reading: re-check the map (a wall misread as open or vice versa).")
        return
    if len(reach) > 1:
        print(f"WARNING: {len(reach)} reachable exits (expected one way out): the shortest is listed first; re-check walls near the others.")
    reach.sort(key=lambda t: len(path((t[1], t[2]))))
    for i, (e, r, c) in enumerate(reach):
        p = path((r, c))
        print(f"{'ROUTE' if i == 0 else 'ALT'} → {e} exit r{r + 1}c{c + 1} ({len(p)} cells, 1-based row,col): " + " → ".join(f"({x + 1},{y + 1})" for x, y in p))
    best = path((reach[0][1], reach[0][2]))
    # equally short alternatives (loops): count shortest paths to the chosen exit
    dist_ = {start: 0}; cnt = {start: 1}; q = collections.deque([start])
    while q:
        cur = q.popleft()
        for nb in nbrs(*cur):
            if nb not in dist_:
                dist_[nb] = dist_[cur] + 1; cnt[nb] = cnt[cur]; q.append(nb)
            elif dist_[nb] == dist_[cur] + 1:
                cnt[nb] += cnt[cur]
    ties = cnt.get((reach[0][1], reach[0][2]), 1)
    if ties > 1:
        print(f"WARNING: {ties} equally short routes to that exit (the maze has loops): re-check the walls where they split; "
              "if the screen really allows both, ask the player which rule applies")
    if lit:
        on = [k for k in best if k in lit]
        print(f"LIT tiles: {len(lit)}; on the route: {len(on)}" + ("  ← the route uses lit tiles; fragment: the safe way is never the lit one, re-check" if on else "  (the lit corridor is a decoy)"))
    print("STEPS (the start is usually pre-marked; skip it):")
    for (r, c) in best:
        b = cells[r][c]
        print(f'<step do="click" at="{b[0] / W:.3f},{b[1] / H:.3f},{b[2] / W:.3f},{b[3] / H:.3f}">Mark row {r + 1}, col {c + 1}</step>')
    if a.debug:
        dbg = img.copy()
        for (r, c) in best:
            b = cells[r][c]; cv2.rectangle(dbg, (b[0] + 3, b[1] + 3), (b[2] - 3, b[3] - 3), (60, 60, 255), 3)
        cv2.imwrite(a.debug, dbg)


if __name__ == "__main__":
    main()
