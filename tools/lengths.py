#!/usr/bin/env python3
"""Find book passages whose word lengths fit a pattern (answer boxes, blanks, enumerations).

  lengths.py 8/4/5/5/9                 exact runs of 5 consecutive words
  lengths.py 8/4/5/5/9 --variants      also -1 each, +1 each, and total fuzz 1 (one word off by one)
  lengths.py 8/4/5/5/9 --fuzz 2        any run within total letter distance 2
  lengths.py 8/4/5/5/9 --perm          lengths in any order
  lengths.py 8/4/5/5/9 --groups        each number = a chunk of 1+ words, counting the spaces
                                       inside it ("spaces between": 8 = "I NEED U")
  lengths.py 8/4/5/5/9 --groups-nospace  chunk of 1+ words, letters only
  lengths.py 7/?/4/4/8                 ? = any length;  7-8 = range
  --clean        only runs that start and end on a sentence/quote boundary
  --host         only runs inside quoted speech in a paragraph that mentions the Host
Word counting is tried four ways (letters only; apostrophes/hyphens counted; contractions
expanded; hyphenated words split) and hits are merged. Output: p<page>:L<line> citations.
"""
import argparse, itertools, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTR = [(r"(?i)\bwon't", "will not"), (r"(?i)\bcan't", "can not"), (r"(?i)n't\b", " not"),
         (r"(?i)'re\b", " are"), (r"(?i)'ll\b", " will"), (r"(?i)'ve\b", " have"),
         (r"(?i)\bI'm\b", "I am"), (r"(?i)'d\b", " would")]
MODES = ["plain", "apos", "expand", "hyphsplit"]


def parse_pattern(s):
    out = []
    for part in re.split(r"[/,\s]+", s.strip()):
        if part in ("?", "*"):
            out.append((0, 99))
        elif "-" in part:
            a, b = part.split("-")
            out.append((int(a), int(b)))
        else:
            out.append((int(part), int(part)))
    return out


def load_lines():
    idx = {}
    with open(os.path.join(ROOT, "book/lines.tsv")) as f:
        next(f)
        for row in f:
            p = row.rstrip("\n").split("\t")
            if len(p) >= 5:
                idx.setdefault(p[0], []).append((p[1], re.sub(r"[^a-z]", "", p[4].lower())))
    return idx


def tokens(text, mode):
    """Yield (core, raw, offset) for each word under a counting mode; offsets index the original text."""
    out = []
    for m in re.finditer(r"[^\s—–]+", text):
        raw, off = m.group(), m.start()
        pieces = [raw]
        if mode == "hyphsplit":
            pieces = [x for x in re.split(r"-+", raw) if x]
        elif mode == "expand":
            t = raw
            for a, b in CONTR:
                t = re.sub(a, b, t)
            pieces = t.split()
        for pc in pieces:
            if mode == "apos":
                core = re.sub(r"[^A-Za-z0-9'’-]", "", pc).strip("'’-")
            else:
                core = re.sub(r"[^A-Za-z0-9]", "", pc)
            if core:
                out.append((core, pc, off))
    return out


def fits(lens, pat, perm, fuzz):
    if len(lens) != len(pat):
        return None
    if perm:
        lo = sorted(p[0] for p in pat)
        seq = sorted(lens)
        pat = [(a, a) for a in lo] if all(p[0] == p[1] for p in pat) else pat
    else:
        seq = lens
    d = 0
    for x, (a, b) in zip(seq, pat):
        if x < a:
            d += a - x
        elif x > b:
            d += x - b
        if d > fuzz:
            return None
    return d


def split_groups(L, i, pat, spaces):
    res = []
    def rec(j, k, acc):
        if k == len(pat):
            res.append(list(acc)); return True
        lo, hi = pat[k]
        tot, n = 0, 0
        while j + n < len(L):
            tot += L[j + n] + (1 if spaces and n else 0)
            n += 1
            if tot > hi:
                return False
            if tot >= lo and rec(j + n, k + 1, acc + [n]):
                return True
        return False
    rec(i, 0, [])
    return res[0] if res else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="+")
    ap.add_argument("--fuzz", type=int, default=0)
    ap.add_argument("--perm", action="store_true")
    ap.add_argument("--variants", action="store_true")
    ap.add_argument("--groups", action="store_true")
    ap.add_argument("--groups-nospace", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--host", action="store_true")
    ap.add_argument("--dialogue", action="store_true", help="only runs inside quoted speech")
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()

    pats = []
    for s in a.pattern:
        base = parse_pattern(s)
        pats.append((s, base, a.fuzz))
        if a.variants:
            fixed = all(x == y for x, y in base)
            if fixed:
                m1 = "/".join(str(x - 1) for x, _ in base)
                p1 = "/".join(str(x + 1) for x, _ in base)
                pats.append((m1, parse_pattern(m1), 0))
                pats.append((p1, parse_pattern(p1), 0))
            if a.fuzz < 1:
                pats.append((s + " ±1", base, 1))

    lines = load_lines()
    hits = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "book/chapters/*.md"))):
        raw = open(f).read()
        marks = [(m.start(), m.group(1)) for m in re.finditer(r"\[p\.([^\]]+)\]", raw)]
        text = re.sub(r"\[p\.[^\]]+\]", lambda m: " " * len(m.group()), raw)
        ch = os.path.basename(f)[:-3]
        for mode in MODES:
            tk = tokens(text, mode)
            L = [len(c) for c, _, _ in tk]
            for label, pat, fz in pats:
                n = len(pat)
                for i in range(len(tk)):
                    if a.groups or a.groups_nospace:
                        g = split_groups(L, i, pat, spaces=a.groups)
                        if not g:
                            continue
                        j, d = i + sum(g), 0
                        chunks, k = [], i
                        for c in g:
                            chunks.append(" ".join(t[1] for t in tk[k:k + c])); k += c
                        shown = " | ".join(chunks)
                    else:
                        if i + n > len(tk):
                            break
                        d = fits(L[i:i + n], pat, a.perm, fz)
                        if d is None:
                            continue
                        j = i + n
                        shown = " ".join(t[1] for t in tk[i:j])
                    start, end = tk[i][2], tk[j - 1][2] + len(tk[j - 1][1])
                    hits.setdefault((ch, start, end), []).append((d, label, mode, shown, f, text, marks))
    if not hits:
        print("no hits"); return

    out = []
    for (ch, start, end), hs in hits.items():
        d, label, mode, shown, f, text, marks = min(hs, key=lambda h: (h[0], MODES.index(h[2])))
        before = text[max(0, start - 3):start]
        after = text[end:end + 2]
        para_s = text.rfind("\n", 0, start)
        para_e = text.find("\n", end)
        para = text[para_s:para_e if para_e > 0 else None]
        opens = text[para_s:start].count('"') % 2 == 1
        clean_start = bool(re.search(r'(^|[.!?]["”]?\s+|["“]\s*|\n\s*)$', text[max(0, start - 4):start])) or start == 0
        clean_end = bool(re.search(r'[.!?,]["”]?$|[.!?]', shown[-2:]))
        host = "host" in para.lower()
        if a.clean and not (clean_start and clean_end):
            continue
        if a.dialogue and not opens:
            continue
        if a.host and not (opens and host):
            continue
        page = "?"
        for off, p in marks:
            if off <= start:
                page = p
        # line: first page line containing the first two words
        key = re.sub(r"[^a-z]", "", " ".join(shown.split()[:2]).lower())
        ln = "?"
        for pl, lt in lines.get(page, []):
            if key and key in lt:
                ln = pl; break
        score = d * 10 - 3 * clean_start - 3 * clean_end - 2 * opens - 2 * (opens and host)
        tags = ",".join(t for t, ok in [("clean", clean_start and clean_end), ("quote", opens),
                                        ("host", opens and host)] if ok)
        ctx = re.sub(r"\s+", " ", text[max(0, start - 50):start]).strip()[-45:]
        ctx2 = re.sub(r"\s+", " ", text[end:end + 40]).strip()
        out.append((score, f"p{page}:L{ln}", ch, label, mode, d, tags, shown, ctx, ctx2))
    out.sort(key=lambda r: (r[0], r[1]))
    print(f"{len(out)} hit(s); best first  (d = letters off; tags: clean=sentence-bounded, quote, host)")
    for sc, cite, ch, label, mode, d, tags, shown, ctx, ctx2 in out[:a.top]:
        print(f"{cite:11} ch{ch} [{label} {mode} d{d}{' ' + tags if tags else ''}]  «{shown}»   …{ctx[-30:]} ‹›{ctx2[:30]}…")


if __name__ == "__main__":
    main()
