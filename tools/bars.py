#!/usr/bin/env python3
"""Measure black redaction bars / mask rows in a challenge screenshot.

  python3 tools/bars.py IMAGE --x0 540 [--y0 0 --y1 99999 --x1 99999 --dark 15]

Prints one row per bar-line (top to bottom): start/end as fractions of the text block width,
whether it's indented, and any internal gaps (the "windows" a mask leaves open). Output ends
with a `layout` signature to paste into `corpus.py layout` and gap specs for `corpus.py grille`.
Use --x0 to skip anything left of the text block (flags, drag handles, icons).
"""
import argparse

import numpy as np
from PIL import Image


def runs(mask_row, min_len):
    out, start = [], None
    for x, v in enumerate(list(mask_row) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start >= min_len:
                out.append((start, x))
            start = None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--x1", type=int, default=10**6)
    ap.add_argument("--y0", type=int, default=0)
    ap.add_argument("--y1", type=int, default=10**6)
    ap.add_argument("--dark", type=int, default=15, help="max mean RGB for a bar pixel")
    ap.add_argument("--min-run", type=int, default=4)
    a = ap.parse_args()

    lum = np.asarray(Image.open(a.image).convert("RGB")).astype(int).mean(axis=2)
    lum = lum[a.y0:a.y1, a.x0:a.x1]
    dark = lum < a.dark
    # A bar-line is a band of image rows where a long dark run exists.
    row_has_bar = np.array([any(e - s >= 20 for s, e in runs(r, a.min_run)) for r in dark])
    bands, start = [], None
    for y, v in enumerate(list(row_has_bar) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= 4:
                bands.append((start, y))
            start = None

    rows = []
    for y0, y1 in bands:
        mid = dark[(y0 + y1) // 2]
        segs = runs(mid, a.min_run)
        # ignore dark specks far left of the main bars (icons)
        rows.append({"y": a.y0 + (y0 + y1) // 2, "segs": segs})
    if not rows:
        raise SystemExit("no bars found; adjust --x0/--dark")

    left = min(r["segs"][0][0] for r in rows)
    right = max(r["segs"][-1][1] for r in rows)
    width = right - left
    starts = [r["segs"][0][0] - left for r in rows]
    # indent threshold: halfway between the flush-left and the indented starts
    threshold = (min(starts) + max(starts)) / 2
    sig, gaps = [], []
    print(f"{len(rows)} bar-lines; text block x={a.x0 + left}..{a.x0 + right} ({width}px)")
    for i, r in enumerate(rows, 1):
        s0 = (r["segs"][0][0] - left) / width
        e1 = (r["segs"][-1][1] - left) / width
        ind = (r["segs"][0][0] - left) > threshold
        inner = [((b[1] - left) / width, (c[0] - left) / width) for b, c in zip(r["segs"], r["segs"][1:])]
        gtxt = " ".join(f"{g0:.2f}-{g1:.2f}" for g0, g1 in inner)
        print(f"row {i:>2} y={r['y']:<4} {'I' if ind else 'L'} start={s0:.2f} end={e1:.2f}" + (f"  gaps: {gtxt}" if inner else ""))
        sig.append(f"{'I' if ind else 'L'}{e1:.2f}")
        gaps += [f"{i}:{g0:.2f}-{g1:.2f}" for g0, g1 in inner]
    print("\nLAYOUT:", " ".join(sig))
    print("GAPS (row:from-to):", " ".join(gaps) or "(none)")


if __name__ == "__main__":
    main()
