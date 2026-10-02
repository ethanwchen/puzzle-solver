#!/usr/bin/env python3
"""Query tool for an indexed SOURCE TEXT ("the corpus"): see docs/corpus.md for the index format.

Every result is cited as p<page>:L<line>[:w<word>] so answers can be verified
against the physical source.

  corpus.py --pages 249-288 CMD ...     any command restricted to a page range (e.g. the current round's section)
  corpus.py search REGEX [-C N]         phrase/regex search; matches across line breaks and
                                      end-of-line hyphenation ("mak- ing" matches "making")
  corpus.py search TEXT --letters       letters-only match, ignoring spaces/punctuation/case
                                      ("QOPH" finds "Q-O-P-H", "broadcasting" finds "broad- casting")
  corpus.py count WORD                  occurrences of an exact word (case-insensitive)
  corpus.py page P                      print a printed page with line numbers
  corpus.py line P L                    one line, words numbered
  corpus.py word P L W [--letter N]     one word (and optionally its Nth letter)
  corpus.py decode "P:L:W[:N] ..."      book-cipher: page:line:word[:letter] triples -> text
  corpus.py decode-pw "P:W ..."         page:word-on-page (words counted across the whole page)
  corpus.py chapter N                   clean text of chapter N (or 'front', 'epilogue')
  corpus.py toc                         chapters, titles, sections, page ranges
  corpus.py acrostic P [P2] [--last]    first (or last) letter of every line on page(s)
  corpus.py initials SCOPE              first letter of each chapter / first word of each chapter
  corpus.py anagram LETTERS [--words N] book words (or N-word phrases from one line) using those letters
  corpus.py grille P "L:F0-F1 ..."      overlay mask: words visible through a gap spanning fraction
                                      F0..F1 of the text width on line L (redaction bars, cut-outs)
  corpus.py layout "I0.72 L1.00 ..."     find pages whose line shapes (Indented/Left + length as a fraction of
                                      the text width) match a mask/bar layout; --ordered to respect row order
  corpus.py probe "ALL SCREEN TEXT"      one-shot triage: decodes codes, searches the rarest phrases verbatim,
                                      anagram-checks letter strings, flags page refs (use this FIRST)
  corpus.py unmask P --rows LETTERS --target PHRASE --layout "L0.72 ..." --gaps "ROW:F0-F1 ..."
                                      full mask solve: assign shuffled rows to page lines (row letters must spell
                                      the target; same-letter rows resolved by bar shape), then read every gap
  corpus.py numbers [REGEX]             every number / number-word with citation
  corpus.py caps                        ALL-CAPS tokens in the narrative (possible emphasis/clues)
  corpus.py notes                       picture / blank-page annotations
  corpus.py who NAME                    player card + every page the name appears on
"""
import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "book"

NUMBER_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand million billion first second third fourth fifth sixth "
    "seventh eighth ninth tenth dozen half"
).split()


def load_lines():
    rows = []
    with open(BOOK / "lines.tsv") as f:
        next(f)
        for raw in f:
            page, line, ch, sec, text = raw.rstrip("\n").split("\t", 4)
            rows.append({"page": page, "line": int(line), "chapter": ch, "section": sec, "text": text})
    return rows


def pages(rows):
    out = collections.OrderedDict()
    for r in rows:
        out.setdefault(r["page"], []).append(r)
    return out


def cite(r, w=None):
    return f"p{r['page']}:L{r['line']}" + (f":w{w}" if w else "")


def norm(w):
    return re.sub(r"[^\w']", "", w).lower()


def joined_stream(rows):
    """Concatenate all lines into one string (dehyphenating line ends) with an offset->row map."""
    text, spans = [], []
    pos = 0
    for r in rows:
        t = r["text"]
        if text and re.search(r"[A-Za-z]-$", text[-1]):
            text[-1] = text[-1][:-1]
            pos -= 1
            sep = ""
        else:
            sep = " " if text else ""
        spans.append((pos + len(sep), r))
        text.append(sep + t)
        pos += len(sep) + len(t)
    return "".join(text), spans


def row_at(spans, offset):
    lo, hi = 0, len(spans) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if spans[mid][0] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return spans[lo][1]


def cmd_search_letters(a, rows):
    """Match on letters only, so hyphens, dashes, spaces and line breaks are all invisible."""
    letters, owners = [], []
    for r in rows:
        for ch in r["text"]:
            if ch.isalpha():
                letters.append(ch.lower())
                owners.append(r)
    hay = "".join(letters)
    needle = re.sub(r"[^a-z]", "", a.pattern.lower())
    n, start = 0, hay.find(needle)
    while start != -1 and n < a.max:
        r = owners[start]
        end_r = owners[start + len(needle) - 1]
        span = cite(r) + ("" if end_r is r else f"–{cite(end_r)}")
        text = r["text"] + ("" if end_r is r else f" / {end_r['text']}")
        print(f"{span} [ch {r['chapter']}]  {text[:220]}")
        n += 1
        start = hay.find(needle, start + 1)
    print(f"{n} hit(s)", file=sys.stderr)


def cmd_search(a, rows):
    if a.letters:
        return cmd_search_letters(a, rows)
    text, spans = joined_stream(rows)
    flags = 0 if a.case else re.I
    n = 0
    for m in re.finditer(a.pattern, text, flags):
        r = row_at(spans, m.start())
        s, e = max(0, m.start() - a.context), min(len(text), m.end() + a.context)
        snippet = text[s:m.start()] + "«" + m.group(0) + "»" + text[m.end():e]
        print(f"{cite(r)} [ch {r['chapter']}]  …{snippet}…")
        n += 1
        if n >= a.max:
            print(f"(stopped at {a.max} hits; use --max)")
            break
    print(f"{n} hit(s)", file=sys.stderr)


def cmd_count(a, rows):
    target = a.word.lower()
    hits = [(r, i) for r in rows for i, w in enumerate(r["text"].split(), 1) if norm(w) == target]
    print(f"{len(hits)} occurrence(s) of '{a.word}'")
    for r, i in hits[: a.max]:
        print(" ", cite(r, i), r["text"])


def cmd_page(a, rows):
    for r in pages(rows).get(a.page, []):
        print(f"L{r['line']:>2}  {r['text']}")


def get_line(rows, p, l):
    for r in rows:
        if r["page"] == p and r["line"] == l:
            return r
    sys.exit(f"no line p{p}:L{l}")


def cmd_line(a, rows):
    r = get_line(rows, a.page, a.line)
    print(cite(r), f"[ch {r['chapter']}]")
    for i, w in enumerate(r["text"].split(), 1):
        print(f"  w{i:<3} {w}")


def cmd_word(a, rows):
    r = get_line(rows, a.page, a.line)
    ws = r["text"].split()
    if not 1 <= a.word <= len(ws):
        sys.exit(f"{cite(r)} has only {len(ws)} words: {r['text']}")
    w = ws[a.word - 1]
    out = f"{cite(r, a.word)} = {w}"
    if a.letter:
        letters = re.sub(r"[^A-Za-z]", "", w)
        out += f"  letter {a.letter} = {letters[a.letter - 1]}"
    print(out)


def cmd_decode(a, rows):
    res = []
    for trip in a.triples.replace(",", " ").split():
        parts = trip.split(":")
        p, l, w = parts[0], int(parts[1]), int(parts[2])
        r = get_line(rows, p, l)
        word = r["text"].split()[w - 1]
        if len(parts) > 3:
            word = re.sub(r"[^A-Za-z]", "", word)[int(parts[3]) - 1]
        res.append(word)
        print(f"{trip:>14} -> {word}")
    print("RESULT:", ("" if any(len(x) == 1 for x in res) else " ").join(res))


def cmd_decode_pw(a, rows):
    pg = pages(rows)
    res = []
    for pair in a.pairs.replace(",", " ").split():
        p, w = pair.split(":")[:2]
        words = [x for r in pg[p] for x in r["text"].split()]
        res.append(words[int(w) - 1])
        print(f"{pair:>10} -> {res[-1]}")
    print("RESULT:", " ".join(res))


def cmd_chapter(a, rows):
    name = f"{int(a.n):03d}" if a.n.isdigit() else a.n
    print((BOOK / "chapters" / f"{name}.md").read_text())


def cmd_toc(a, rows):
    print((BOOK / "toc.tsv").read_text())


def cmd_acrostic(a, rows):
    pg = pages(rows)
    keys = list(pg)
    lo = keys.index(a.page)
    hi = keys.index(a.page2) if a.page2 else lo
    for p in keys[lo : hi + 1]:
        letters = []
        for r in pg[p]:
            ws = re.sub(r"[^A-Za-z ]", "", r["text"]).split()
            if ws:
                letters.append((ws[-1][-1] if a.last else ws[0][0]))
        print(f"p{p}: {''.join(letters)}")


def cmd_initials(a, rows):
    firsts = collections.OrderedDict()
    for r in rows:
        if r["chapter"] in firsts or r["line"] == 0 and r["text"].startswith("Chapter"):
            if r["chapter"] not in firsts:
                continue
        if r["chapter"] not in firsts:
            body = re.sub(r"^Chapter \d+\.?\s*[A-Z ,'Ñ]*\b", "", r["text"]).strip()
            if body:
                firsts[r["chapter"]] = (r, body)
    letters = []
    for ch, (r, body) in firsts.items():
        fw = body.split()[0]
        letters.append(re.sub(r"[^A-Za-z]", "", fw)[:1])
        print(f"ch {ch:>9} {cite(r)}  {fw:<15} {body[:70]}")
    print("FIRST LETTERS:", "".join(letters))


def cmd_anagram(a, rows):
    target = collections.Counter(re.sub(r"[^a-z]", "", a.letters.lower()))
    n = sum(target.values())
    seen = set()
    for r in rows:
        ws = [norm(w) for w in r["text"].split()]
        for k in range(1, a.words + 1):
            for i in range(len(ws) - k + 1):
                phrase = " ".join(ws[i : i + k])
                if phrase in seen:
                    continue
                if collections.Counter(phrase.replace(" ", "").replace("'", "")) == target:
                    seen.add(phrase)
                    print(f"{cite(r, i + 1)}  {phrase}")
    if not seen:
        print(f"no {a.words}-word-or-fewer run in the book is an anagram of {n} letters")


def cmd_grille(a, rows):
    """Words visible through gaps in a mask over page P (gap positions as fractions of the text-block width).
    Uses the proportional-font + justification model shared with `unmask`."""
    page_rows = [r for r in pages(rows)[a.page] if r["line"] > 0]
    letters = []
    for spec in a.gaps.replace(",", " ").split():
        ln, rng = spec.split(":")
        f0, f1 = (float(x) for x in rng.split("-"))
        words, fit = gap_words(page_rows, int(ln), f0, f1)
        chars, narrow = gap_letters(page_rows, int(ln), f0, f1)
        letters.append(chars[:1] if narrow else "")
        tag = f"  NARROW → letter '{chars[:1]}'" if narrow else f"  chars under gap: {chars}"
        print(f"p{a.page}:L{ln} gap {f0:.2f}-{f1:.2f}: {' | '.join(words)}  (fit {fit:.2f}){tag}")
    if any(letters):
        print("NARROW-GAP LETTERS (in order):", "".join(letters).upper())


def page_shape(lines):
    """Per printed line: (indented?, length as fraction of the text width). Line 1's indent is unknown (None)."""
    full = max(len(r["text"]) for r in lines)
    shape = []
    for i, r in enumerate(lines):
        n = len(r["text"])
        length = 1.0 if n >= 0.9 * full else n / full
        indented = None if i == 0 else len(lines[i - 1]["text"]) < 0.9 * full
        shape.append((indented, length))
    return shape


def cmd_layout(a, rows):
    target = [(tok[0].upper() == "I", float(tok[1:])) for tok in a.signature.split()]
    scored = []
    for p, lines in pages(rows).items():
        lines = [r for r in lines if r["line"] > 0]
        if not lines:
            continue
        shape = page_shape(lines)
        count_pen = abs(len(shape) - len(target)) * 1.0
        if a.ordered:
            pairs = list(zip(target, shape))
        else:
            # order-invariant: match within indent classes by sorted length
            pairs = []
            for want in (True, False):
                t = sorted(l for i, l in target if i == want)
                s_ = sorted(l for i, l in shape if i == want or (i is None))
                pairs += [((want, x), (want, y)) for x, y in zip(t, s_)]
                count_pen += abs(len(t) - len(s_)) * 0.5
        cost = count_pen
        for (ti, tl), (si, sl) in pairs:
            cost += abs(tl - sl) + (0.3 if si is not None and si != ti else 0)
        scored.append((cost, p, len(shape)))
    scored.sort()
    print(f"target: {len(target)} lines ({'ordered' if a.ordered else 'order-invariant'})")
    for cost, p, n in scored[: a.top]:
        print(f"  p{p:<5} lines={n:<3} cost={cost:.2f}")


def cmd_probe(a, rows):
    """Run every cheap text probe on the screen text in one call, ranked by how distinctive each hit is."""
    text = a.text
    freq = collections.Counter(norm(w) for r in rows for w in r["text"].split())
    total_hits = 0

    codes = re.findall(r"\b(\d{1,3})[-:.](\d{1,3})[-:.](\d{1,3})(?:[-:.](\d{1,2}))?\b", text)
    if codes:
        print("== CODES (page-line-word[-letter])")
        out = []
        for c in codes:
            p, l, w = str(int(c[0])), int(c[1]), int(c[2])
            try:
                r = get_line(rows, p, l)
                word = r["text"].split()[w - 1]
                if c[3]:
                    word = re.sub(r"[^A-Za-z]", "", word)[int(c[3]) - 1]
                out.append(word)
                print(f"  {'-'.join(x for x in c if x)} -> p{p}:L{l}:w{w} = {word}")
            except (SystemExit, IndexError):
                print(f"  {'-'.join(x for x in c if x)} -> (no such position)")
        print("  RESULT:", " ".join(re.sub(r"[^A-Za-z0-9']", "", x) for x in out))
        total_hits += len(out)

    # Distinctive phrases: word n-grams scored by rarity in the book; search the rarest verbatim.
    words = re.findall(r"[A-Za-z']+", text)
    grams = []
    for n in (4, 3, 2):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            rarity = sum(1.0 / (1 + freq[w.lower()]) for w in g)
            grams.append((rarity, " ".join(g)))
    grams.sort(reverse=True)
    seen, tried = set(), 0
    joined, spans = joined_stream(rows)
    print("== PHRASE HITS (rarest n-grams from the screen, searched verbatim)")
    for rarity, g in grams:
        if tried >= a.phrases:
            break
        if g.lower() in seen:
            continue
        seen.add(g.lower())
        tried += 1
        pat = r"\b" + r"\W+".join(map(re.escape, g.split())) + r"\b"
        hits = list(re.finditer(pat, joined, re.I))
        if 0 < len(hits) <= 5:
            for m in hits:
                r = row_at(spans, m.start())
                ctx = joined[max(0, m.start() - 70):m.end() + 70].replace("\n", " ")
                print(f"  '{g}' -> {cite(r)} [ch {r['chapter']}]  …{ctx}…")
                total_hits += 1

    letters = [w for w in re.findall(r"\b[A-Z]{5,}\b", text)]
    if letters:
        print("== LETTER STRINGS (letters-only search; anagram if no hit)")
        for w in dict.fromkeys(letters):
            hay = re.sub(r"[^a-z]", "", joined.lower())
            if w.lower() in hay:
                print(f"  {w}: appears letters-only in the book")
            elif len(w) <= 12:
                ana = collections.Counter(w.lower())
                found = sorted({norm(x) for r in rows for x in r["text"].split() if collections.Counter(norm(x).replace("'", "")) == ana})
                if found:
                    print(f"  {w}: anagram of book word(s) {', '.join(found[:5])}")

    refs = re.findall(r"\b(?:page|p\.?)\s*(\d{1,3})\b", text, re.I)
    if refs:
        print("== PAGE REFS:", ", ".join(dict.fromkeys(refs)), "-> corpus.py page P")
    print(f"({total_hits} hits)", file=sys.stderr)


_FONT = None


def text_width(t):
    """Printed width of a string in a Times-like face (proportional: quotes narrow, 'm'/'W' wide)."""
    global _FONT
    if _FONT is None:
        try:
            from PIL import ImageFont
            _FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Times New Roman.ttf", 100)
        except Exception:
            _FONT = False
    return _FONT.getlength(t) if _FONT else len(t) * 45.0


def word_spans(page_rows, ln, indent=0.045):
    """(start, end, word) for each word on line ln as fractions of the text-block width, modelling indentation
    and full justification (full lines stretch their spaces to the column width)."""
    by_line = {r["line"]: r for r in page_rows}
    natural = {r["line"]: text_width(r["text"]) for r in page_rows}
    column = max(natural.values())
    r = by_line[ln]
    prev = by_line.get(ln - 1)
    words = r["text"].split()
    indented = prev is not None and natural[prev["line"]] < 0.9 * column
    off = indent if indented else 0.0
    avail = column * (1 - off)
    space = text_width(" ")
    ink = sum(text_width(w) for w in words)
    full = natural[ln] >= 0.9 * column and len(words) > 1
    gap = (avail - ink) / (len(words) - 1) if full else space
    x = off * column
    spans = []
    for w in words:
        wd = text_width(w)
        # dash-joined tokens ("here—after") are separate words in print: give each part its own span
        sub_x = x
        for i, part in enumerate(w.split("—")):
            if i:
                sub_x += text_width("—")
            pw = text_width(part)
            if part:
                spans.append((sub_x / column, (sub_x + pw) / column, part))
            sub_x += pw
        x += wd + gap
    return spans


def gap_words(page_rows, ln, f0, f1):
    """Words visible through gap F0-F1, ranked by how much of each word the gap exposes; plus a fit score
    (1.0 = the gap frames exactly one whole word)."""
    ranked = []
    for s0, s1, w in word_spans(page_rows, ln):
        ov = min(s1, f1) - max(s0, f0)
        if ov > 0:
            ranked.append((ov / (s1 - s0), w))
    ranked.sort(reverse=True)
    fit = ranked[0][0] if ranked else 0.0
    return [w for _, w in ranked], fit


def gap_letters(page_rows, ln, f0, f1):
    """Characters whose centres fall inside the gap, and whether the gap is letter-narrow (< ~1.5 chars wide)."""
    natural = max(text_width(r["text"]) for r in page_rows)
    avg = text_width("n") / natural
    mid_chars = []
    for s0, s1, w in word_spans(page_rows, ln):
        if s1 < f0 or s0 > f1:
            continue
        x = s0
        scale = (s1 - s0) / max(text_width(w), 1e-9)
        for ch in w:
            cw = text_width(ch) * scale
            if f0 <= x + cw / 2 <= f1 and ch.isalnum():
                mid_chars.append(ch)
            x += cw
    return "".join(mid_chars), (f1 - f0) < 1.5 * avg


def cmd_unmask(a, rows):
    import itertools
    page_rows = [r for r in pages(rows)[a.page] if r["line"] > 0]
    shape = page_shape(page_rows)
    letters = re.sub(r"[^A-Z]", "", a.rows.upper())
    target = re.sub(r"[^A-Z]", "", a.target.upper())
    lay = a.layout.split()
    if sorted(letters) != sorted(target) or len(letters) != len(lay) or len(target) != len(shape):
        sys.exit(f"mismatch: rows={len(letters)} layout={len(lay)} target={len(target)} page lines={len(shape)}")
    row_shape = [(tok[0] == "I", float(tok[1:])) for tok in lay]

    gaps = {}
    for spec in a.gaps.replace(",", " ").split():
        rw, rng = spec.split(":")
        gaps.setdefault(int(rw) - 1, []).append(tuple(float(x) for x in rng.split("-")))

    def cost(row, line):
        (ri, rl), (li, ll) = row_shape[row], shape[line]
        c = abs(rl - ll) + (0.3 if li is not None and li != ri else 0)
        for f0, f1 in gaps.get(row, []):          # a mask gap should expose a whole word on its true line
            c += 0.5 * (1 - gap_words(page_rows, line + 1, f0, f1)[1])
        return c

    assign = {}
    for ch in sorted(set(target)):
        rws = [i for i, c in enumerate(letters) if c == ch]
        lns = [i for i, c in enumerate(target) if c == ch]
        best = min(itertools.permutations(rws), key=lambda perm: sum(cost(r, l) for r, l in zip(perm, lns)))
        for r, l in zip(best, lns):
            assign[r] = l
    total = sum(cost(r, l) for r, l in assign.items())
    print(f"row -> line assignment (shape cost {total:.2f}):")
    print("  " + " ".join(f"{r + 1}->{assign[r] + 1}" for r in sorted(assign)))
    found = []
    for row, gl in sorted(gaps.items()):
        for f0, f1 in gl:
            ln = assign[row] + 1
            words, fit = gap_words(page_rows, ln, f0, f1)
            chars, narrow = gap_letters(page_rows, ln, f0, f1)
            found.append((ln, f0, words, chars[:1] if narrow else ""))
            tag = f"  NARROW → letter '{chars[:1]}'" if narrow else ""
            print(f"  row {row + 1:>2} -> p{a.page}:L{ln:<2} gap {f0:.2f}-{f1:.2f}: {' | '.join(words)}  (fit {fit:.2f}){tag}")
    found.sort()
    phrase = " ".join(re.sub(r"[^A-Za-z']", "", w[0]) if w else "?" for _, _, w, _ in found)
    print("READ IN LINE ORDER (words):", phrase.upper())
    letters = "".join(l for *_, l in found)
    if letters:
        print("READ IN LINE ORDER (narrow-gap letters):", letters.upper())


def cmd_numbers(a, rows):
    pat = re.compile(r"\d|\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
    for r in rows:
        if r["line"] == 0 and r["page"] == "front":
            continue
        if pat.search(r["text"]) and (not a.pattern or re.search(a.pattern, r["text"], re.I)):
            hl = pat.sub(lambda m: f"«{m.group(0)}»", r["text"])
            print(f"{cite(r)} [ch {r['chapter']}]  {hl}")


def cmd_caps(a, rows):
    c = collections.defaultdict(list)
    for r in rows:
        if r["text"].startswith("Chapter"):
            continue
        for i, w in enumerate(r["text"].split(), 1):
            core = re.sub(r"[^A-Za-z]", "", w)
            if len(core) >= 2 and core.isupper() and core not in {"MIT", "OK", "TV", "US", "AI"}:
                c[core].append(cite(r, i))
    for w, cs in sorted(c.items(), key=lambda x: -len(x[1])):
        print(f"{w:<18} {len(cs):>3}  {' '.join(cs[:12])}{' …' if len(cs) > 12 else ''}")


def cmd_notes(a, rows):
    print((BOOK / "notes.tsv").read_text())


def cmd_who(a, rows):
    front = " ".join(r["text"] for r in rows if r["page"] in {"ix", "x", "xi", "xii"})
    m = re.search(rf"{a.name.upper()}\.\s(.*?PLAYER #\d+\.|.*?(?=[A-Z]{{3,}}\.))", front)
    if m:
        print("PLAYER CARD:", m.group(0), "\n")
    by_page = collections.OrderedDict()
    for r in rows:
        if re.search(rf"\b{re.escape(a.name)}\b", r["text"], re.I):
            by_page.setdefault(r["page"], 0)
            by_page[r["page"]] += 1
    print(f"appears on {len(by_page)} pages:", " ".join(f"{p}({n})" for p, n in by_page.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("search"); s.add_argument("pattern"); s.add_argument("-C", "--context", type=int, default=80)
    s.add_argument("--case", action="store_true"); s.add_argument("--max", type=int, default=200)
    s.add_argument("--letters", action="store_true", help="letters-only match (ignore spaces, hyphens, punctuation)")
    s = sp.add_parser("count"); s.add_argument("word"); s.add_argument("--max", type=int, default=100)
    s = sp.add_parser("page"); s.add_argument("page")
    s = sp.add_parser("line"); s.add_argument("page"); s.add_argument("line", type=int)
    s = sp.add_parser("word"); s.add_argument("page"); s.add_argument("line", type=int)
    s.add_argument("word", type=int); s.add_argument("--letter", type=int)
    s = sp.add_parser("decode"); s.add_argument("triples")
    s = sp.add_parser("decode-pw"); s.add_argument("pairs")
    s = sp.add_parser("chapter"); s.add_argument("n")
    sp.add_parser("toc")
    s = sp.add_parser("acrostic"); s.add_argument("page"); s.add_argument("page2", nargs="?")
    s.add_argument("--last", action="store_true")
    s = sp.add_parser("initials"); s.add_argument("scope", nargs="?", default="chapters")
    s = sp.add_parser("anagram"); s.add_argument("letters"); s.add_argument("--words", type=int, default=3)
    s = sp.add_parser("grille"); s.add_argument("page"); s.add_argument("gaps")
    s = sp.add_parser("layout"); s.add_argument("signature"); s.add_argument("--ordered", action="store_true")
    s.add_argument("--top", type=int, default=8)
    s = sp.add_parser("probe"); s.add_argument("text"); s.add_argument("--phrases", type=int, default=25)
    s = sp.add_parser("unmask"); s.add_argument("page"); s.add_argument("--rows", required=True)
    s.add_argument("--target", required=True); s.add_argument("--layout", required=True); s.add_argument("--gaps", required=True)
    s = sp.add_parser("numbers"); s.add_argument("pattern", nargs="?")
    sp.add_parser("caps")
    sp.add_parser("notes")
    s = sp.add_parser("who"); s.add_argument("name")
    ap.add_argument("--pages", help="restrict to a printed-page range, e.g. 249-288 (Round 3's book part)")
    a = ap.parse_args()
    rows = load_lines()
    if a.pages:
        lo, hi = (int(x) for x in a.pages.split("-"))
        rows = [r for r in rows if r["page"].isdigit() and lo <= int(r["page"]) <= hi]
    globals()["cmd_" + a.cmd.replace("-", "_")](a, rows)


if __name__ == "__main__":
    main()
