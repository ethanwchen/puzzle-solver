#!/usr/bin/env python3
"""Decode Morse blinks from a screen recording.

  python3 tools/blink.py VIDEO.mov [--crop X0 Y0 X1 Y1] [--debug]

Finds the image region whose brightness changes most over time (the blinking eye), thresholds it into
open/closed, measures each closed period (dot vs dash, split by the largest gap in durations) and each open gap
(within a letter vs between letters vs between words), and decodes Morse. Long pauses (> 3x letter gap) separate
eyes/words when several eyes are recorded one after another.
"""
import argparse
import sys

import cv2
import numpy as np

sys.path.insert(0, __import__("os").path.dirname(__file__))
from solvers import MORSE_REV  # noqa: E402


def signal(path, crop):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if crop:
            x0, y0, x1, y1 = crop
            g = g[y0:y1, x0:x1]
        frames.append(cv2.resize(g, (g.shape[1] // 4 or 1, g.shape[0] // 4 or 1)).astype(np.float32))
    if not frames:
        sys.exit("no frames read")
    stack = np.stack(frames)
    # the most temporally variable 2% of pixels = the blinking eye
    var = stack.var(axis=0)
    mask = var >= np.percentile(var, 98)
    s = stack[:, mask].mean(axis=1)
    return s, fps


def runs(bits):
    out, cur, n = [], bits[0], 0
    for b in bits:
        if b == cur:
            n += 1
        else:
            out.append((cur, n))
            cur, n = b, 1
    out.append((cur, n))
    return out


def split_two(vals):
    """Threshold between two clusters (largest gap in sorted values)."""
    v = sorted(vals)
    if len(v) < 2 or v[-1] < 1.6 * v[0]:
        return None
    gaps = [(v[i + 1] - v[i], (v[i + 1] + v[i]) / 2) for i in range(len(v) - 1)]
    return max(gaps)[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--crop", type=int, nargs=4)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    s, fps = signal(a.video, a.crop)
    lo, hi = np.percentile(s, 5), np.percentile(s, 95)
    thr = (lo + hi) / 2
    # "event" = the rarer state (a blink/flash); decide polarity by which state is the minority
    bright = s > thr
    event = bright if bright.mean() < 0.5 else ~bright
    rs = [(b, n / fps) for b, n in runs(list(event))]
    # drop leading/trailing idle
    while rs and not rs[0][0]:
        rs.pop(0)
    while rs and not rs[-1][0]:
        rs.pop()
    ons = [d for b, d in rs if b]
    offs = [d for b, d in rs if not b]
    if not ons:
        sys.exit("no blinks detected; try --crop around one eye")
    dash_thr = split_two(ons) or (max(ons) * 0.6 if len(set(round(x, 2) for x in ons)) > 1 else 10)
    letter_thr = split_two(offs) if offs else None
    if a.debug:
        print("fps", fps, "on durations", [round(x, 2) for x in ons])
        print("off durations", [round(x, 2) for x in offs])
        print("dash>", round(dash_thr, 3), "letter gap>", letter_thr and round(letter_thr, 3))
    words, word, sym = [], [], ""
    for b, d in rs:
        if b:
            sym += "-" if d > dash_thr else "."
        else:
            if letter_thr and d > letter_thr:
                word.append(MORSE_REV.get(sym, "?"))
                sym = ""
                if d > 3 * letter_thr:
                    words.append("".join(word))
                    word = []
    word.append(MORSE_REV.get(sym, "?"))
    words.append("".join(word))
    print("DECODED:", " | ".join(words))


if __name__ == "__main__":
    main()
