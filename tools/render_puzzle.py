#!/usr/bin/env python3
"""Render a practice-puzzle spec (JSON) into a contest-style screenshot PNG.

  render_puzzle.py SPEC.json OUT.png

Spec:
{
  "code": "R5·G13", "title": "The Lantern", "tagline": "WHAT YOU SEEK IS WRITTEN DOWN", "timer": "00:05:00",
  "display_title": "Gsv Uzoo",   # optional: big title shown instead of "title" (e.g. a garbled/ciphered title)
  "blocks": [
    {"type": "text", "text": "…", "italic": true, "size": 22},
    {"type": "tiles", "items": ["133-025-002", "..."], "fixed": "DARK"},          # code tiles with empty slots
    {"type": "glyphs", "label": "THE CRIB", "items": [{"g": "♞", "rot": 0, "mirror": false, "fill": "V"}], "boxes": true},
    {"type": "bars", "rows": [{"flag": "T", "segs": [[0.0, 0.55], [0.62, 1.0]], "indent": false}]},
    {"type": "flags", "letters": "HELLO"},
    {"type": "swatches", "colors": ["red", "#00ff00"]},
    {"type": "wires", "words": [[["white","blue"],["red","green"]]], "label": "..."},  # 25-pair colour-code punch block
    {"type": "braille", "text": "⠓⠑⠇⠇⠕"},
    {"type": "image", "path": "field.png", "width": 820},   # path relative to the spec file
    {"type": "boxes", "n": 7, "label": "ANSWER"},
    {"type": "buttons", "items": ["USE THIS DEVICE CAMERA", "CONTINUE"]},
    {"type": "input", "label": "TYPE YOUR ANSWER"}
  ]
}
Glyph "g" may be any unicode symbol; chess: outline ♔♕♖♗♘♙, filled ♚♛♜♝♞♟.
"""
import json
import sys

from PIL import Image, ImageDraw, ImageFont

W = 1372
BG = (14, 12, 14)
INK = (230, 225, 215)
DIM = (150, 145, 140)
PINK = (236, 72, 153)
TILE = (216, 185, 138)

FONTS = {
    "sans": "/System/Library/Fonts/Helvetica.ttc",
    "serif": "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "serif_i": "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
    "sym": "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "braille_u": "/System/Library/Fonts/Apple Symbols.ttf",
}


def F(kind, size):
    try:
        return ImageFont.truetype(FONTS[kind], size)
    except OSError:
        return ImageFont.load_default()


# ------------------------------------------------------------------ signal flags (ICS)
Y, B, R, Wt, K = (250, 204, 21), (29, 78, 216), (220, 38, 38), (245, 245, 245), (10, 10, 10)


def draw_flag(d, x, y, s, letter):
    """Draw on a private tile (clips diagonal patterns), then paste onto the target canvas."""
    tile = Image.new("RGB", (s, s), Wt)
    _draw_flag(ImageDraw.Draw(tile), 0, 0, s, letter)
    d._image.paste(tile, (int(x), int(y)))
    d.rectangle((x, y, x + s - 1, y + s - 1), outline=(60, 60, 60))


def _draw_flag(d, x, y, s, letter):
    L = letter.upper()
    box = (x, y, x + s, y + s)
    rect = lambda x0, y0, x1, y1, c: d.rectangle((x + x0 * s, y + y0 * s, x + x1 * s, y + y1 * s), fill=c)
    poly = lambda pts, c: d.polygon([(x + px * s, y + py * s) for px, py in pts], fill=c)
    if L == "A":
        rect(0, 0, .5, 1, Wt); poly([(.5, 0), (1, 0), (.75, .5), (1, 1), (.5, 1)], B)
    elif L == "B":
        poly([(0, 0), (1, 0), (.75, .5), (1, 1), (0, 1)], R)
    elif L == "C":
        for i, c in enumerate([B, Wt, R, Wt, B]): rect(0, i / 5, 1, (i + 1) / 5, c)
    elif L == "D":
        rect(0, 0, 1, 1, Y); rect(0, .25, 1, .75, B)
    elif L == "E":
        rect(0, 0, 1, .5, B); rect(0, .5, 1, 1, R)
    elif L == "F":
        rect(0, 0, 1, 1, Wt); poly([(.5, 0), (1, .5), (.5, 1), (0, .5)], R)
    elif L == "G":
        for i in range(6): rect(i / 6, 0, (i + 1) / 6, 1, Y if i % 2 == 0 else B)
    elif L == "H":
        rect(0, 0, .5, 1, Wt); rect(.5, 0, 1, 1, R)
    elif L == "I":
        rect(0, 0, 1, 1, Y); d.ellipse((x + .3 * s, y + .3 * s, x + .7 * s, y + .7 * s), fill=K)
    elif L == "J":
        rect(0, 0, 1, 1, B); rect(0, 1 / 3, 1, 2 / 3, Wt)
    elif L == "K":
        rect(0, 0, .5, 1, Y); rect(.5, 0, 1, 1, B)
    elif L == "L":
        rect(0, 0, .5, .5, Y); rect(.5, 0, 1, .5, K); rect(0, .5, .5, 1, K); rect(.5, .5, 1, 1, Y)
    elif L == "M":
        rect(0, 0, 1, 1, B); d.line((x, y, x + s, y + s), fill=Wt, width=int(s * .2)); d.line((x + s, y, x, y + s), fill=Wt, width=int(s * .2))
    elif L == "N":
        for i in range(4):
            for j in range(4): rect(i / 4, j / 4, (i + 1) / 4, (j + 1) / 4, B if (i + j) % 2 == 0 else Wt)
    elif L == "O":
        poly([(0, 1), (1, 0), (1, 1)], Y); poly([(0, 0), (1, 0), (0, 1)], R)
    elif L == "P":
        rect(0, 0, 1, 1, B); rect(.3, .3, .7, .7, Wt)
    elif L == "Q":
        rect(0, 0, 1, 1, Y)
    elif L == "R":
        rect(0, 0, 1, 1, R); rect(.4, 0, .6, 1, Y); rect(0, .4, 1, .6, Y)
    elif L == "S":
        rect(0, 0, 1, 1, Wt); rect(.3, .3, .7, .7, B)
    elif L == "T":
        rect(0, 0, 1 / 3, 1, R); rect(1 / 3, 0, 2 / 3, 1, Wt); rect(2 / 3, 0, 1, 1, B)
    elif L == "U":
        rect(0, 0, .5, .5, R); rect(.5, 0, 1, .5, Wt); rect(0, .5, .5, 1, Wt); rect(.5, .5, 1, 1, R)
    elif L == "V":
        rect(0, 0, 1, 1, Wt); d.line((x, y, x + s, y + s), fill=R, width=int(s * .2)); d.line((x + s, y, x, y + s), fill=R, width=int(s * .2))
    elif L == "W":
        rect(0, 0, 1, 1, B); rect(.2, .2, .8, .8, Wt); rect(.35, .35, .65, .65, R)
    elif L == "X":
        rect(0, 0, 1, 1, Wt); rect(.4, 0, .6, 1, B); rect(0, .4, 1, .6, B)
    elif L == "Y":
        for i in range(-5, 6):
            poly([(i / 5, 0), ((i + 1) / 5, 0), ((i + 2) / 5, 1), ((i + 1) / 5, 1)], Y if i % 2 == 0 else R)
    elif L == "Z":
        poly([(0, 0), (1, 0), (.5, .5)], Y); poly([(1, 0), (1, 1), (.5, .5)], B)
        poly([(0, 1), (1, 1), (.5, .5)], R); poly([(0, 0), (0, 1), (.5, .5)], K)
    d.rectangle(box, outline=(60, 60, 60))


# ------------------------------------------------------------------ blocks

def glyph_img(g, size, rot=0, mirror=False):
    f = F("sym", size)
    im = Image.new("RGBA", (int(size * 1.4), int(size * 1.4)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((size * .2, 0), g, font=f, fill=INK)
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if rot:
        im = im.rotate(-rot, expand=True)
    return im


def render(spec):
    blocks = spec.get("blocks", [])
    canvas = Image.new("RGB", (W, 2400), BG)
    d = ImageDraw.Draw(canvas)
    # header panel (mimics the contest card)
    d.rounded_rectangle((30, 20, 400, 250), radius=14, outline=(90, 50, 80), width=2, fill=(24, 18, 24))
    d.text((52, 38), f"{spec.get('code', '')}  {spec.get('title', '').upper()}", font=F("sans", 14), fill=PINK)
    d.text((52, 60), spec.get("display_title", spec.get("title", "")), font=F("sans", 38), fill=INK)
    y = 112
    for line in wrap(spec.get("tagline", ""), F("serif_i", 18), 330):
        d.text((52, y), line, font=F("serif_i", 18), fill=DIM)
        y += 24
    d.text((230, 212), spec.get("timer", "00:05:00"), font=F("sans", 22), fill=PINK)
    d.rounded_rectangle((W - 170, 30, W - 30, 64), radius=8, outline=(120, 120, 120), width=1)
    d.text((W - 155, 39), "BACK TO BOARD", font=F("sans", 13), fill=INK)

    y = 290
    cx = 460
    for b in blocks:
        t = b["type"]
        if t == "text":
            f = F("serif_i" if b.get("italic") else "serif", b.get("size", 22))
            for line in wrap(b["text"], f, 820):
                d.text((cx, y), line, font=f, fill=INK)
                y += int(b.get("size", 22) * 1.35)
            y += 16
        elif t == "tiles":
            for item in b["items"]:
                d.rectangle((cx, y, cx + 180, y + 30), outline=(120, 120, 120))
                d.rounded_rectangle((cx + 190, y, cx + 320, y + 30), radius=4, outline=TILE, width=2, fill=(10, 10, 12))
                d.text((cx + 208, y + 7), item, font=F("sans", 15), fill=INK)
                y += 36
            if b.get("fixed"):
                d.rectangle((cx, y, cx + 180, y + 30), outline=PINK, width=2)
                d.text((cx + 60, y + 6), b["fixed"], font=F("sans", 17), fill=INK)
                y += 36
            y += 16
        elif t == "glyphs":
            if b.get("label"):
                d.text((cx + 300, y), b["label"], font=F("sans", 15), fill=DIM)
                y += 28
            per = b.get("per_row", 12)
            items = b["items"]
            for r0 in range(0, len(items), per):
                x = cx
                for it in items[r0:r0 + per]:
                    gi = glyph_img(it["g"], 46, it.get("rot", 0), it.get("mirror", False))
                    canvas.paste(gi, (x, y), gi)
                    if b.get("boxes", True):
                        by = y + 72
                        if it.get("fill"):
                            d.rounded_rectangle((x + 6, by, x + 56, by + 50), radius=4, fill=TILE)
                            d.text((x + 20, by + 10), it["fill"], font=F("sans", 26), fill=(30, 30, 30))
                        else:
                            d.rectangle((x + 6, by, x + 56, by + 50), outline=(130, 130, 130))
                    x += 72
                y += 140 if b.get("boxes", True) else 80
            y += 10
        elif t == "bars":
            rows = b["rows"]
            top = y
            d.rectangle((cx - 10, top - 10, cx + 560, top + 22 * len(rows) + 10), fill=(36, 22, 22))
            for r in rows:
                if r.get("flag"):
                    draw_flag(d, cx, y + 2, 14, r["flag"])
                x0, x1 = cx + 40, cx + 540
                for s0, s1 in r["segs"]:
                    d.rectangle((x0 + s0 * (x1 - x0), y + 4, x0 + s1 * (x1 - x0), y + 16), fill=(6, 6, 6))
                y += 22
            y += 30
        elif t == "flags":
            x = cx
            for ch in b["letters"]:
                if ch == " ":
                    x += 30
                    continue
                draw_flag(d, x, y, 40, ch)
                x += 50
                if x > W - 80:
                    x, y = cx, y + 56
            y += 70
        elif t == "swatches":
            x = cx
            for c in b["colors"]:
                d.rectangle((x, y, x + 40, y + 40), fill=c, outline=(80, 80, 80))
                x += 50
            y += 60
        elif t == "wires":
            # punch-down block: each word is a group of twisted pairs; each pair = two wires (left, right)
            words = b["words"]
            wc = {"white": (245, 245, 240), "red": (210, 35, 35), "black": (12, 12, 12), "yellow": (250, 204, 21),
                  "violet": (130, 70, 210), "blue": (30, 80, 220), "orange": (245, 125, 20), "green": (22, 150, 60),
                  "brown": (120, 72, 30), "slate": (112, 128, 144)}
            ww, gap_pair, gap_word, hgt = 16, 14, 72, 110
            rows, cur, curw = [], [], 0
            for wd in words:
                wlen = len(wd) * (2 * ww + gap_pair)
                if cur and curw + gap_word + wlen > 840:
                    rows.append(cur); cur, curw = [], 0
                cur.append(wd); curw += wlen + (gap_word if curw else 0)
            if cur:
                rows.append(cur)
            if b.get("label"):
                d.text((cx, y), b["label"], font=F("sans", 14), fill=DIM)
                y += 40
            for row in rows:
                d.rounded_rectangle((cx - 12, y - 12, cx + 860, y + hgt + 12), radius=6, fill=(214, 208, 196))
                x = cx + 4
                for wd in row:
                    for tip, ring in wd:
                        for k, col in enumerate((tip, ring)):
                            x0 = x + k * (ww + 2)
                            d.rectangle((x0, y, x0 + ww, y + hgt), fill=wc.get(col, col), outline=(60, 60, 60))
                        x += 2 * ww + gap_pair
                    x += gap_word - gap_pair
                y += hgt + 36
            y += 10
        elif t == "image":
            # {"type": "image", "path": "field.png", "width": 820}  (path relative to the spec file's folder)
            import os
            p = b["path"] if os.path.isabs(b["path"]) else os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), b["path"])
            im = Image.open(p).convert("RGB")
            if b.get("width"):
                im = im.resize((b["width"], int(im.height * b["width"] / im.width)), Image.LANCZOS)
            canvas.paste(im, (cx, y))
            y += im.height + 24
        elif t == "braille":
            d.text((cx, y), b["text"], font=F("braille_u", 44), fill=INK)
            y += 70
        elif t == "boxes":
            if b.get("label"):
                d.text((cx, y), b["label"], font=F("sans", 14), fill=DIM)
                y += 24
            for i in range(b["n"]):
                d.rectangle((cx + i * 58, y, cx + i * 58 + 48, y + 48), outline=(130, 130, 130))
            y += 70
        elif t == "input":
            d.text((cx, y), b.get("label", "YOUR ANSWER"), font=F("sans", 14), fill=DIM)
            d.rectangle((cx, y + 22, cx + 520, y + 62), outline=(130, 130, 130))
            y += 84
        elif t == "buttons":
            x = cx
            for it in b["items"]:
                w = int(F("sans", 14).getlength(it)) + 40
                d.rounded_rectangle((x, y, x + w, y + 36), radius=8, outline=PINK if it == "CONTINUE" else (130, 130, 130))
                d.text((x + 20, y + 10), it, font=F("sans", 14), fill=INK)
                x += w + 16
            y += 60
    return canvas.crop((0, 0, W, max(y + 40, 600)))


def wrap(text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        nxt = (cur + " " + w).strip()
        if font.getlength(nxt) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    render(spec).save(sys.argv[2])
    print(sys.argv[2])
