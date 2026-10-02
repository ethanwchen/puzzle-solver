#!/usr/bin/env python3
"""Analyze a screen recording of anything that moves: blinks, flashes, lights, animations, changing text.

  python3 tools/motion.py CLIP.mp4 [--crop X0 Y0 X1 Y1] [--regions 6] [--out DIR]

For puzzles a single screenshot can't capture (an eye that blinks Morse while hovered, a flashing light, cards that
flip, a sequence that plays once). Prints:
  1. ACTIVE REGIONS: every area that changed during the clip (numbered boxes, in pixels AND fractions of the frame),
     ranked by how much it changed, with the time window when it was active. A moving cursor shows up as a long, thin
     trail of weak change and is ranked low.
  Page loads / navigation / intro screens (most of the frame changing at once) split the clip into scenes,
  analyzed separately.
  2. For each region, its ON/OFF TIMELINE, plus a BEST MORSE READING chosen across both polarities (flash vs blink),
     two brightness features and trimmed countdowns, scored by Morse timing fit and real (book/dictionary) words.
     Also (brightness thresholded into two states): event durations and gaps in ms,
     classified short/long, plus a Morse reading (dot = short event, dash = long; gaps split letters/words).
     If several regions were active one after another (the player hovered eye 1, then eye 2, ...), each gets its own reading.
  3. Images to open with Read: regions.png (last scene's final frame with its numbered boxes) and sheet.png (keyframes with timestamps,
     one per visible change), for anything that isn't on/off: changing text, moving pieces, colours.
Morse: --unit MS (else estimated), --expect W1,W2,... (words the clue/book allows: aligned against every reading,
junk before/after ignored; the most reliable way to read noisy blinks).
Tuning: --window T0 T1 (ignore intros/outros), --crop (one item only), --debounce N (merge animation glitches),
--strip X0 Y0 X1 Y1 (filmstrip of one area). signal_N.png plots each region's brightness with events shaded.
Crop values are pixels of the video frame. Pair with tools/blink.py (single-region Morse) and tools/solvers.py.
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from solvers import MORSE_REV  # noqa: E402

AW = 360  # analysis width (px)
DEBOUNCE = 2


def load(path, crop):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    grays, times = [], []
    W = H = None
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if crop:
            x0, y0, x1, y1 = crop
            f = f[y0:y1, x0:x1]
        H, W = f.shape[:2]
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (AW, max(1, round(AW * H / W))), interpolation=cv2.INTER_AREA)
        grays.append(g)
        t = cap.get(cv2.CAP_PROP_POS_MSEC)
        times.append(t if t > 0 or i == 0 else i * 1000 / fps)
        i += 1
    cap.release()
    if len(grays) < 3:
        sys.exit("clip too short / unreadable")
    return np.stack(grays), np.array(times, dtype=float), fps, (W, H)


def find_regions(stack, k):
    """Connected areas of high temporal variation, ranked by total variation."""
    std = stack.astype(np.float32).std(axis=0)
    thr = max(6.0, float(np.percentile(std, 99.0)) * 0.35)
    mask = (std > thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    regs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 6:
            continue
        sel = lab == i
        score = float(std[sel].sum())
        # thin, sparse trails (cursor paths) have low fill ratio and weak per-pixel change
        fill = area / float(w * h)
        regs.append({"box": (x, y, x + w, y + h), "sel": sel, "score": score * (0.4 + fill), "mean_std": float(std[sel].mean())})
    regs.sort(key=lambda r: -r["score"])
    return regs[:k], std


def runs(bits, times):
    out, start = [], 0
    for i in range(1, len(bits) + 1):
        if i == len(bits) or bits[i] != bits[start]:
            end_t = times[i] if i < len(times) else times[-1] + (times[-1] - times[-2])
            out.append((bool(bits[start]), end_t - times[start], times[start]))
            start = i
    return out


def split_two(vals):
    v = sorted(vals)
    if len(v) < 2 or v[-1] < 1.6 * v[0]:
        return None
    gaps = [(v[i + 1] - v[i], (v[i + 1] + v[i]) / 2) for i in range(len(v) - 1)]
    return max(gaps)[1]


UNIT = None  # ms; set by --unit when the Morse timing unit is known (Round 3 G7: 220)


def morse(rs):
    """rs: [(is_event, ms, t0)] trimmed to start/end with events -> (reading, symbols, thresholds)."""
    ons = [d for b, d, _ in rs if b]
    offs = [d for b, d, _ in rs if not b]
    if UNIT:  # known unit: dot 1u / dash 3u; gaps 1u / 3u (letter) / 7u (word)
        dash, letter = 2 * UNIT, 2 * UNIT
        words, word, sym, syms = [], [], "", []
        for b, d, _ in rs:
            if b:
                sym += "-" if d > dash else "."
            elif d > letter:
                word.append(MORSE_REV.get(sym, "?")); syms.append(sym); sym = ""
                if d > 5 * UNIT:
                    words.append("".join(word)); word = []
        word.append(MORSE_REV.get(sym, "?")); syms.append(sym)
        words.append("".join(word))
        return " ".join(words), " ".join(syms), dash, letter
    dash = split_two(ons)
    if dash is None:  # all events alike: call them dots unless they're long relative to the gaps
        dash = max(ons) + 1 if not offs or np.median(ons) < 2 * np.median(offs) else 0
    letter = split_two(offs) if offs else None
    if letter is not None and letter < 1.5 * min(ons):  # gap split looks like noise
        letter = None
    words, word, sym, syms = [], [], "", []
    for b, d, _ in rs:
        if b:
            sym += "-" if d > dash else "."
        elif letter and d > letter:
            word.append(MORSE_REV.get(sym, "?")); syms.append(sym); sym = ""
            if d > 2.75 * letter:  # Morse: intra 1u, letter 3u (threshold ~2u), word 7u
                words.append("".join(word)); word = []
    word.append(MORSE_REV.get(sym, "?")); syms.append(sym)
    words.append("".join(word))
    return " ".join(words), " ".join(syms), dash, letter


def debounce(bits, k=2):
    """Merge runs shorter than k frames into their neighbours (compression noise, single-frame glitches)."""
    bits = bits.copy()
    i = 0
    while i < len(bits):
        j = i
        while j < len(bits) and bits[j] == bits[i]:
            j += 1
        if j - i < k and i > 0 and j < len(bits):
            bits[i:j] = bits[i - 1]
        i = j
    return bits


def otsu(vals):
    v = np.sort(np.asarray(vals, dtype=float))
    best, thr = -1, float(v.mean())
    for t in np.unique(np.percentile(v, np.arange(5, 96, 2.5))):
        a, b = v[v <= t], v[v > t]
        if len(a) < 2 or len(b) < 2:
            continue
        var = len(a) * len(b) * (a.mean() - b.mean()) ** 2
        if var > best:
            best, thr = var, t
    return thr


def timeline(series, times, force=None, method="flips"):
    """Two-state reading of a brightness series. Signals can be faint (a 4-level flicker) and sit next to big one-off
    changes (fade-in, page dimming), so instead of one mid-range threshold, try many and keep the one that yields the
    most clean on/off transitions."""
    lo, hi = np.percentile(series, 1), np.percentile(series, 99)
    if hi - lo < 2.5:
        return None
    best = None
    k = DEBOUNCE
    if UNIT and len(times) > 2:  # with a known unit, anything shorter than ~0.45 unit is animation noise
        k = max(k, int(np.ceil(0.5 * UNIT / max(1.0, float(np.median(np.diff(times)))))))
    if method == "otsu":
        # three levels are common (faded / closed / open): drop the faded tail first, then split the rest in two
        lo_cut = otsu(series)
        active = series[series > lo_cut] if (series > lo_cut).sum() > len(series) * 0.3 else series
        thresholds = [otsu(active)]
    else:
        thresholds = np.unique(np.percentile(series, np.arange(3, 98, 1.5)))
    for thr in thresholds:
        bits = debounce(series > thr, k)
        on, off = series[bits], series[~bits]
        if len(on) < 2 or len(off) < 2 or on.mean() - off.mean() < 2.5:
            continue
        flips = int(np.count_nonzero(bits[1:] != bits[:-1]))
        if best is None or flips > best[0]:
            best = (flips, thr, bits)
    if best is None or best[0] < 2:
        return None
    bright = best[2]
    # The resting state is the one holding the longest unbroken run (before/after the sequence plays); the other
    # state is the "event". Fall back to the minority state when neither run stands out.
    longest = {True: 0, False: 0}
    for b_, d_, _ in runs(bright, times):
        longest[b_] = max(longest[b_], d_)
    if force:
        rest_bright = force == "dark"
    elif max(longest.values()) >= 1.5 * min(longest.values()):
        rest_bright = longest[True] > longest[False]
    else:
        rest_bright = bright.mean() >= 0.5
    event = ~bright if rest_bright else bright
    polarity = "dark blinks" if rest_bright else "bright flashes"
    rs = runs(event, times)
    while rs and not rs[0][0]:
        rs.pop(0)
    while rs and not rs[-1][0]:
        rs.pop()
    return rs, polarity


_WORDS = None


def words():
    """Book vocabulary + dictionary, to recognise readings that are real words."""
    global _WORDS
    if _WORDS is None:
        _WORDS = set()
        try:
            import csv
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "book", "words.tsv")) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    w = "".join(ch for ch in r["word"].upper() if ch.isalpha())
                    if len(w) >= 2:
                        _WORDS.add(w)
        except OSError:
            pass
        try:
            with open("/usr/share/dict/words") as f:
                pass  # the system dictionary is full of obscure words (SNAB); book vocabulary is the better prior
        except OSError:
            pass
    return _WORDS


def score_reading(rs, reading):
    """Higher = more plausible Morse: valid letters, durations near 1u/3u (gaps 1u/3u/7u), real words."""
    ons = [d for b, d, _ in rs if b]
    offs = [d for b, d, _ in rs if not b]
    if not ons:
        return -99
    u = UNIT or (np.median([d for d in ons if d <= (split_two(ons) or max(ons) + 1)]) or 1)
    fit_on = np.mean([min(abs(d - u), abs(d - 3 * u)) / u for d in ons])
    fit_off = np.mean([min(abs(d - u), abs(d - 3 * u), abs(d - 7 * u)) / u for d in offs]) if offs else 0
    letters = reading.replace(" ", "")
    bad = letters.count("?") / max(1, len(letters))
    ws = [w for w in reading.split() if w]
    real = sum(1 for w in ws if w in words() and len(w) >= 3) / max(1, len(ws))
    return round(2.0 * real - 3.0 * bad - fit_on - 0.5 * fit_off + min(len(letters), 8) * 0.05, 3)


MORSE_FWD = {v: k for k, v in MORSE_REV.items()}


def expect_match(rs, expected):
    """Semi-global alignment of the observed dot/dash/gap stream to each expected word's Morse (junk before/after
    the message is free). Returns [(cost, word)] best first; cost = edits per symbol of the word."""
    obs = ""
    u = UNIT or 220
    for b, d, _ in rs:
        if b:
            obs += "-" if d > 2 * u else "."
        else:
            obs += "|" if d > 2 * u else ""
    res = []
    for w in expected:
        code = "|".join(MORSE_FWD.get(ch, "") for ch in w.upper() if ch.isalpha())
        if not code:
            continue
        n, m = len(code), len(obs)
        # The first/last letter can be LOST (merged into the resting state before/after the message): skipping the
        # word's first or last letter costs 0.3 per symbol instead of 1. Junk before/after the message is free.
        first = code.find("|") if "|" in code else n
        last = n - 1 - code.rfind("|") if "|" in code else n
        # Junk before/after the message (countdown, fade) is free up to FREE symbols each side, then costs 0.5 per
        # symbol, so a short word can't hide inside a long message.
        LOST, FREE, EXTRA = 0.3, 3, 0.5
        junk = lambda k: max(0, k - FREE) * EXTRA
        D = [[junk(j) for j in range(m + 1)]]
        for i in range(1, n + 1):
            row = [LOST * i if i <= first else D[i - 1][0] + 1] + [0.0] * m
            for j in range(1, m + 1):
                row[j] = min(D[i - 1][j] + 1, row[j - 1] + 1, D[i - 1][j - 1] + (code[i - 1] != obs[j - 1]))
            D.append(row)
        best = min(D[i][j] + junk(m - j) + LOST * (n - i) for i in range(max(0, n - last), n + 1) for j in range(m + 1))
        res.append((round(best / n, 3), w.upper()))
    return sorted(res)


def candidates(sub_pixels, times):
    """Every plausible Morse reading of one region: 2 features x 2 polarities x trimming leading junk (countdowns).
    Returns [(score, reading, syms, polarity, feature, rs)] best first."""
    feats = {"brightness": sub_pixels.mean(axis=1)}
    thr = np.percentile(sub_pixels, 85)
    feats["bright-pixel share"] = (sub_pixels > thr).mean(axis=1) * 255
    out = []
    for fname, series in feats.items():
        for pol, method in (("bright", "flips"), ("dark", "flips"), ("bright", "otsu"), ("dark", "otsu")):
            tl = timeline(series, times, force=pol, method=method)
            if not tl or not tl[0]:
                continue
            rs, polname = tl
            if UNIT:  # an event far longer than a dash is the eye settling, not a symbol
                while rs and rs[-1][0] and rs[-1][1] > 4.5 * UNIT:
                    rs = rs[:-1]
                    while rs and not rs[-1][0]:
                        rs = rs[:-1]
            for trim in range(0, 4):  # drop leading events (countdown digits, fade-ins)
                r2 = rs[:]
                for _ in range(trim):
                    while r2 and r2[0][0]:
                        r2.pop(0)
                    while r2 and not r2[0][0]:
                        r2.pop(0)
                if sum(1 for b, _, _ in r2 if b) < 2:
                    break
                reading, syms, _, _ = morse(r2)
                out.append((score_reading(r2, reading), reading, syms, polname + (f", first {trim} event(s) dropped" if trim else "") + ("" if method == "flips" else ", 2-level split"), fname, r2))
                # partial letters at either end (clip started mid-message, fade-out): also score the reading with a
                # letter or two trimmed off each end, and keep whichever reads as real words
                letters = reading.split(" ")
                if len(letters) == 1 and len(reading) >= 4:
                    for a in range(0, 3):
                        for z in range(0, 2):
                            sub = reading[a:len(reading) - z]
                            if (a or z) and len(sub) >= 3 and sub in words():
                                out.append((score_reading(r2, sub) - 0.15 * (a + z), sub, syms, polname + f", trimmed {a} letter(s) front / {z} back", fname, r2))
    out.sort(key=lambda c: -c[0])
    seen, best = set(), []
    for c in out:
        if c[1] not in seen:
            seen.add(c[1]); best.append(c)
    return best


def split_sessions(rs):
    """Break a timeline at very long idle gaps (the player moved to another item)."""
    offs = [d for b, d, _ in rs if not b]
    if len(offs) < 3:
        return [rs]
    big = max(1500.0, 4 * float(np.median(offs)))
    out, curr = [], []
    for r in rs:
        if not r[0] and r[1] > big:
            if curr:
                out.append(curr)
            curr = []
        else:
            curr.append(r)
    if curr:
        out.append(curr)
    return [s for s in out if any(b for b, _, _ in s)]


def keyframes(stack, times, maxn=12):
    idx = [0]
    for i in range(1, len(stack)):
        if np.abs(stack[i].astype(np.int16) - stack[idx[-1]].astype(np.int16)).mean() > 1.2:
            idx.append(i)
    if len(idx) > maxn:
        idx = [idx[round(j * (len(idx) - 1) / (maxn - 1))] for j in range(maxn)]
    return idx


def read_color(path, crop, want, width):
    cap = cv2.VideoCapture(path)
    frames, i, want = {}, 0, set(want)
    while want:
        ok, f = cap.read()
        if not ok:
            break
        if i in want:
            if crop:
                x0, y0, x1, y1 = crop
                f = f[y0:y1, x0:x1]
            h, w = f.shape[:2]
            frames[i] = cv2.resize(f, (width, round(width * h / w)), interpolation=cv2.INTER_AREA)
            want.discard(i)
        i += 1
    cap.release()
    return frames


def plot(series, times, rs, path, title):
    """Brightness over time with the detected events shaded, for a visual sanity check."""
    Wp, Hp, pad = 1200, 260, 30
    img = np.full((Hp, Wp, 3), 24, np.uint8)
    t0, t1 = times[0], times[-1] if times[-1] > times[0] else times[0] + 1
    lo, hi = float(series.min()), float(series.max()) if series.max() > series.min() else float(series.min()) + 1
    X = lambda t: int(pad + (t - t0) / (t1 - t0) * (Wp - 2 * pad))
    Y = lambda v: int(Hp - pad - (v - lo) / (hi - lo) * (Hp - 2 * pad))
    for b, d, ts in rs:
        if b:
            cv2.rectangle(img, (X(ts), pad), (X(ts + d), Hp - pad), (40, 90, 40), -1)
    pts = np.array([[X(t), Y(v)] for t, v in zip(times, series)], np.int32)
    cv2.polylines(img, [pts], False, (80, 200, 255), 2)
    for sec in range(int(t0 // 1000), int(t1 // 1000) + 1):
        x = X(sec * 1000)
        cv2.line(img, (x, Hp - pad), (x, Hp - pad + 6), (200, 200, 200), 1)
        cv2.putText(img, f"{sec}s", (x - 8, Hp - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    cv2.putText(img, title + " (green = event)", (pad, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    cv2.imwrite(path, img)


def strip(video, crop, box, times, path, n=42):
    x0, y0, x1, y1 = box
    cap = cv2.VideoCapture(video)
    step = max(1, len(times) // n)
    tiles, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0 and len(tiles) < n:
            if crop:
                f = f[crop[1]:crop[3], crop[0]:crop[2]]
            t = cv2.resize(f[y0:y1, x0:x1], (110, max(1, round(110 * (y1 - y0) / max(1, x1 - x0)))))
            cv2.putText(t, f"{i / (cap.get(cv2.CAP_PROP_FPS) or 25):.2f}", (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
            tiles.append(t)
        i += 1
    cap.release()
    if tiles:
        while len(tiles) % 7:
            tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(path, np.vstack([np.hstack(tiles[r:r + 7]) for r in range(0, len(tiles), 7)]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--crop", type=int, nargs=4)
    ap.add_argument("--regions", type=int, default=6)
    ap.add_argument("--out")
    ap.add_argument("--window", type=float, nargs=2, metavar=("T0", "T1"), help="only analyze seconds T0..T1 of the clip")
    ap.add_argument("--expect", help="comma-separated words the message could be (from the clue or the book, e.g. player names); "
                    "each region's timeline is aligned to their Morse and the closest words are listed")
    ap.add_argument("--unit", type=float, help="Morse unit in ms if known (Round 3 G7 uses 220): fixed dot/dash/gap thresholds")
    ap.add_argument("--debounce", type=int, default=2, help="merge on/off runs shorter than N frames (animation glitches)")
    ap.add_argument("--strip", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                    help="also write strip.png: this area every few frames with timestamps (to eyeball a blink/flip)")
    a = ap.parse_args()
    global DEBOUNCE, UNIT
    DEBOUNCE = a.debounce
    UNIT = a.unit
    out = a.out or os.path.splitext(a.video)[0] + "_motion"
    os.makedirs(out, exist_ok=True)

    stack, times, fps, (W, H) = load(a.video, a.crop)
    if a.window:
        keep = (times >= a.window[0] * 1000) & (times <= a.window[1] * 1000)
        stack, times = stack[keep], times[keep]
        if len(stack) < 3:
            sys.exit("window holds too few frames")
    dur = (times[-1] - times[0]) / 1000
    sx = W / stack.shape[2]
    print(f"CLIP {os.path.basename(a.video)}: {dur:.1f}s, {len(stack)} frames (~{len(stack) / max(dur, 1e-6):.0f} fps), frame {W}x{H}px")
    # Scene cuts (page loads, navigation, intro screens) change most of the frame at once; they would swamp the
    # region finder, so the clip is split at cuts and each steady scene is analyzed on its own.
    moved = [(np.abs(stack[i].astype(np.int16) - stack[i - 1].astype(np.int16)) > 25).mean() for i in range(1, len(stack))]
    cuts = [i for i, m in enumerate(moved, 1) if m > 0.25]
    bounds, start = [], 0
    for c in cuts + [len(stack)]:
        if c - start >= 8 and times[min(c, len(stack) - 1)] - times[start] >= 800:
            bounds.append((start, c))
        start = c
    if not bounds:
        bounds = [(0, len(stack))]
    if len(bounds) > 1:
        print(f"{len(bounds)} steady scenes (split at {len(cuts)} scene cuts): " + ", ".join(f"{times[s0] / 1000:.1f}-{times[s1 - 1] / 1000:.1f}s" for s0, s1 in bounds))

    last = read_color(a.video, a.crop, [bounds[-1][1] - 1], 1000)
    shot = next(iter(last.values())) if last else np.zeros((round(1000 * H / W), 1000, 3), np.uint8)
    fx = 1000 / W
    n = 0
    for s0, s1 in bounds:
        sub, st = stack[s0:s1], times[s0:s1]
        regs, _ = find_regions(sub, a.regions)
        print(f"\nSCENE {times[s0] / 1000:.1f}-{times[s1 - 1] / 1000:.1f}s. ACTIVE REGIONS (ranked by amount of change):")
        if not regs:
            print("    nothing moved")
        for r in regs:
            n += 1
            x0, y0, x1, y1 = r["box"]
            px = [round(v * sx) for v in (x0, y0, x1, y1)]
            fr = [px[0] / W, px[1] / H, px[2] / W, px[3] / H]
            series = sub[:, r["sel"]].mean(axis=1)
            act = np.abs(np.diff(series)) > 2
            tw = (st[1:][act].min() / 1000, st[1:][act].max() / 1000) if act.any() else (0, 0)
            print(f"\n[{n}] px {px}  frac ({fr[0]:.3f},{fr[1]:.3f},{fr[2]:.3f},{fr[3]:.3f})  active {tw[0]:.1f}-{tw[1]:.1f}s  strength {r['mean_std']:.0f}")
            tl = timeline(series, st)
            if not tl or not tl[0]:
                print("    gradual change (no clean on/off) -> look at sheet.png")
            else:
                rs, pol = tl
                ev = [round(d) for b_, d, _ in rs if b_]
                gp = [round(d) for b_, d, _ in rs if not b_]
                print(f"    {pol}: {len(ev)} events. durations ms: {ev[:60]}{' ...' if len(ev) > 60 else ''}")
                print(f"    gaps ms: {gp[:60]}{' ...' if len(gp) > 60 else ''}")
                if len(ev) >= 2:
                    sessions = split_sessions(rs)
                    for si, ss in enumerate(sessions, 1):
                        reading, syms, dash, letter = morse(ss)
                        tag = f"session {si} @{ss[0][2] / 1000:.1f}s" if len(sessions) > 1 else "as morse"
                        print(f"    {tag}: {syms}  ->  {reading}   (dash>{dash:.0f}ms, letter gap>{(letter or 0):.0f}ms)")
                if len(ev) >= 3:
                    given = UNIT
                    if not given:  # estimate the Morse unit: dots AND 1-unit gaps are the most common short runs
                        allrun = [d for d in ev + gp if 60 <= d <= 2500]
                        short = [d for d in allrun if d < np.median(allrun)] if allrun else []
                        UNIT = float(np.median(short)) if short else None
                        if UNIT:
                            print(f"    estimated unit ≈ {UNIT:.0f} ms (pass --unit if you know it; Round 3 G7 uses 220)")
                    cands = candidates(sub[:, r["sel"]].astype(np.float32), st)
                    if cands:
                        sc, reading, syms, pol2, fname, _ = cands[0]
                        print(f"    BEST MORSE READING: {reading}   [{syms}]  ({pol2}; {fname}; score {sc})")
                        for sc, reading, syms, pol2, fname, _ in cands[1:4]:
                            print(f"      alt: {reading}   [{syms}]  ({pol2}; {fname}; score {sc})")
                        if a.expect:
                            exp = [w for w in a.expect.split(",") if w.strip()]
                            best = {}
                            for sc, reading, syms, pol2, fname, rs2 in cands[:12]:
                                for cost, w in expect_match(rs2, exp)[:3]:
                                    if w not in best or cost < best[w][0]:
                                        best[w] = (cost, pol2, fname)
                            # machine-readable: best cost per word for each polarity (used for batch assignment)
                            for pk in ("dark", "bright"):
                                per = {}
                                for sc, reading, syms, pol2, fname, rs2 in cands:
                                    if pk not in pol2:
                                        continue
                                    for cost, w in expect_match(rs2, exp):
                                        per[w] = min(per.get(w, 9), cost)
                                if per:
                                    print(f"    EXPECT_COSTS {pk}: " + ",".join(f"{w}={c:.3f}" for w, c in sorted(per.items())))
                            ranked = sorted(best.items(), key=lambda kv: kv[1][0])[:4]
                            print("    EXPECTED-WORD MATCH (edits per symbol, 0 = exact): " + "; ".join(f"{w} {c:.2f} ({p.split(',')[0]})" for w, (c, p, _) in ranked))
                    UNIT = given
                if len(ev) < 3:
                    print("    (few events: a one-off change, or the clip missed the sequence; record longer)")
                if n <= 4:
                    plot(series, st, rs, os.path.join(out, f"signal_{n}.png"), f"region {n}: {pol}")
                    print(f"    plot: {os.path.join(out, f'signal_{n}.png')}")
            if (s0, s1) == bounds[-1]:
                cv2.rectangle(shot, (round(px[0] * fx), round(px[1] * fx)), (round(px[2] * fx), round(px[3] * fx)), (60, 220, 60), 2)
                cv2.putText(shot, str(n), (round(px[0] * fx) + 3, round(px[1] * fx) + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 220, 60), 2)
    cv2.imwrite(os.path.join(out, "regions.png"), shot)

    ki = keyframes(stack, times)
    col = read_color(a.video, a.crop, ki, 480)
    tiles = []
    for i in ki:
        t = col.get(i)
        if t is None:
            continue
        t = t.copy()
        cv2.rectangle(t, (0, 0), (92, 22), (0, 0, 0), -1)
        cv2.putText(t, f"{times[i] / 1000:.2f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(t)
    if tiles:
        cols = 3
        h, w = tiles[0].shape[:2]
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(len(tiles) // cols)]
        cv2.imwrite(os.path.join(out, "sheet.png"), np.vstack(rows))
    if a.strip:
        strip(a.video, a.crop, a.strip, times, os.path.join(out, "strip.png"))
        print(f"STRIP: {os.path.join(out, 'strip.png')} (the --strip area over time)")
    print(f"\nIMAGES: {os.path.join(out, 'regions.png')} (numbered boxes)  {os.path.join(out, 'sheet.png')} ({len(ki)} keyframes)")


if __name__ == "__main__":
    main()
