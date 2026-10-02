#!/usr/bin/env python3
"""Zoom helpers for reading small details (glyphs, flags, bars, fine print) in challenge screenshots.

  zoom.py grid IMAGE [--step 100]           full image with a labelled pixel grid -> pick crop boxes in one look
  zoom.py crop IMAGE X0 Y0 X1 Y1 [--scale 4] [--sharpen] [--contrast 1.8] [--grid 20]
                                            enlarged crop (optionally with its own fine grid in ORIGINAL coords)
  zoom.py strip IMAGE X0 Y0 X1 Y1 --n N [--axis x|y] [--scale 4]
                                            split a row/column of N items (glyphs, flags, tiles) into numbered,
                                            enlarged cells on one sheet, so each can be read and labelled

Outputs are PNGs in /tmp/puzzle_zoom/ (printed paths); open them with the Read tool.
Coordinates are ORIGINAL image pixels (the Read tool may show a downscaled image: multiply by its stated factor).
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

OUT = Path("/tmp/puzzle_zoom")


def font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_grid(im, step, origin=(0, 0), scale=1.0, color=(0, 255, 255)):
    d = ImageDraw.Draw(im)
    f = font(max(10, int(step * scale / 5)))
    ox, oy = origin
    w, h = im.size
    x = (step - ox % step) % step
    while x * scale < w:
        X = int(x * scale)
        d.line([(X, 0), (X, h)], fill=color, width=1)
        d.text((X + 2, 2), str(ox + x), fill=color, font=f)
        x += step
    y = (step - oy % step) % step
    while y * scale < h:
        Y = int(y * scale)
        d.line([(0, Y), (w, Y)], fill=color, width=1)
        d.text((2, Y + 2), str(oy + y), fill=color, font=f)
        y += step
    return im


def save(im, name):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    im.save(path)
    print(path, f"({im.size[0]}x{im.size[1]})")


def enhance(im, a):
    if a.contrast and a.contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(a.contrast)
    if a.sharpen:
        im = im.filter(ImageFilter.SHARPEN)
    return im


def cmd_grid(a):
    im = Image.open(a.image).convert("RGB")
    print(f"image {im.size[0]}x{im.size[1]}")
    save(draw_grid(im, a.step), f"{Path(a.image).stem}_grid.png")


def cmd_crop(a):
    im = Image.open(a.image).convert("RGB").crop((a.x0, a.y0, a.x1, a.y1))
    im = im.resize((int(im.width * a.scale), int(im.height * a.scale)), Image.LANCZOS)
    im = enhance(im, a)
    if a.grid:
        draw_grid(im, a.grid, origin=(a.x0, a.y0), scale=a.scale)
    save(im, f"{Path(a.image).stem}_{a.x0}_{a.y0}_{a.x1}_{a.y1}_x{a.scale:g}.png")


def cmd_strip(a):
    src = Image.open(a.image).convert("RGB").crop((a.x0, a.y0, a.x1, a.y1))
    n = a.n
    cells = []
    for i in range(n):
        if a.axis == "x":
            w = src.width / n
            box = (int(i * w), 0, int((i + 1) * w), src.height)
        else:
            h = src.height / n
            box = (0, int(i * h), src.width, int((i + 1) * h))
        c = src.crop(box)
        c = c.resize((int(c.width * a.scale), int(c.height * a.scale)), Image.LANCZOS)
        cells.append(enhance(c, a))
    pad, label_h = 12, 28
    cw = max(c.width for c in cells)
    ch = max(c.height for c in cells)
    cols = min(n, max(1, 1600 // (cw + pad)))
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cw + pad) + pad, rows * (ch + label_h + pad) + pad), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    f = font(20)
    for i, c in enumerate(cells):
        r, k = divmod(i, cols)
        x, y = pad + k * (cw + pad), pad + r * (ch + label_h + pad)
        d.text((x, y), f"#{i + 1}", fill=(255, 220, 0), font=f)
        sheet.paste(c, (x, y + label_h))
    save(sheet, f"{Path(a.image).stem}_strip_{a.axis}{n}.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("grid"); s.add_argument("image"); s.add_argument("--step", type=int, default=100)
    for name in ("crop", "strip"):
        s = sp.add_parser(name); s.add_argument("image")
        for k in ("x0", "y0", "x1", "y1"):
            s.add_argument(k, type=int)
        s.add_argument("--scale", type=float, default=4)
        s.add_argument("--sharpen", action="store_true")
        s.add_argument("--contrast", type=float, default=1.0)
        if name == "crop":
            s.add_argument("--grid", type=int, default=0)
        else:
            s.add_argument("--n", type=int, required=True)
            s.add_argument("--axis", choices=["x", "y"], default="x")
    a = ap.parse_args()
    {"grid": cmd_grid, "crop": cmd_crop, "strip": cmd_strip}[a.cmd](a)


if __name__ == "__main__":
    main()
