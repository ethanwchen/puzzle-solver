#!/usr/bin/env python3
"""Scrambles and ciphers that anagram.py / solvers.py don't cover. Book-first, cited.

  unscramble.py words "EVAS SA YANM SA OYU NCA"   each word's letters scrambled, word breaks kept
  unscramble.py order "may live others so that"   words shuffled (letters intact)
  unscramble.py cipher "TEXT"                     reverse, per-word reverse, rail fence 2-6, columnar 2-8,
                                                  Vigenere / Beaufort / keyed Caesar with book keys, cryptogram
  unscramble.py all "TEXT"                        run everything, best first
Book keys = player names, THEHOST, game names, and words from --keys "A,B". Use anagram.py for one letter bag
with unknown word breaks, solvers.py for symbol codes (morse, a1z26, braille, ...).
"""
import argparse, collections, itertools, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solvers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK_KEYS = ["HOST", "THEHOST", "WATCHER", "THEWATCHER", "KEEPER", "DANGEROUS", "GAMES",
             "ASHBY", "RIVERA", "MERCER", "OKONKWO", "GRANT", "ANT", "BRENNER", "CALLOW", "DUNMORE", "NORTH",
             "ELSWORTH", "SAAD", "DELACROIX", "HOLLIS", "KEANE", "LOWELL", "IVERS", "OAKES", "FAIRBAIRN"]


def load_words():
    toks = []
    with open(os.path.join(ROOT, "book/words.tsv")) as f:
        next(f)
        for row in f:
            p = row.rstrip("\n").split("\t")
            core = re.sub(r"[^a-z]", "", p[3].lower())
            if core:
                toks.append((core, p[3], p[0], p[1], p[2]))
    # join words hyphen-broken across printed lines ("com-" + "petition")
    out, i = [], 0
    while i < len(toks):
        c, raw, pg, ln, w = toks[i]
        if raw.endswith("-") and i + 1 < len(toks) and toks[i + 1][3] != ln:
            n = toks[i + 1]
            out.append((c + n[0], raw[:-1] + n[1], pg, ln, w)); i += 2
        else:
            out.append(toks[i]); i += 1
    return out


def cite(t):
    return f"p{t[2]}:L{t[3]}:w{t[4]}"


def en(text):
    return solvers.english_score(text)


# ------------------------------------------------------------------ word-scramble (breaks kept)
def per_word(text, top):
    words = [re.sub(r"[^a-z]", "", w.lower()) for w in text.split()]
    words = [w for w in words if w]
    keys = ["".join(sorted(w)) for w in words]
    book = load_words()
    bk = ["".join(sorted(t[0])) for t in book]
    n = len(keys)
    print(f"== WORDS: {n} scrambled words, breaks kept")
    hits_order, hits_any = [], []
    want = collections.Counter(keys)
    for i in range(len(book) - n + 1):
        if bk[i:i + n] == keys:
            hits_order.append(i)
        elif bk[i] in want and collections.Counter(bk[i:i + n]) == want:
            hits_any.append(i)
    for label, hs in (("BOOK RUN, same order", hits_order), ("BOOK RUN, words in another order", hits_any)):
        for i in hs[:top]:
            print(f"  {label}: {cite(book[i])}  «{' '.join(t[1] for t in book[i:i + n])}»")
    # per-word candidates, book words first
    v = solvers.vocab()
    by = collections.defaultdict(list)
    for w, wt in v.items():
        by["".join(sorted(w))].append((wt, w))
    cands = []
    for w, k in zip(words, keys):
        c = sorted(by.get(k, []), reverse=True)
        cands.append([x[1] for x in c[:6]] or ["?" + w])
    print("  per word (most bookish first): " + " | ".join("/".join(c).upper() for c in cands))
    best = " ".join(c[0] for c in cands).upper()
    print(f"  best reading: {best}")
    # try the best reading as a book phrase
    s = " ".join(c[0] for c in cands)
    joined = [t[0] for t in book]
    first = [c[0] for c in cands]
    for i in range(len(joined) - n + 1):
        if joined[i:i + n] == first:
            print(f"  → verbatim in book at {cite(book[i])}"); break
    return bool(hits_order or hits_any)


# ------------------------------------------------------------------ word order
def order(text, top):
    words = [re.sub(r"[^a-z]", "", w.lower()) for w in text.split()]
    words = [w for w in words if w]
    n = len(words)
    want = collections.Counter(words)
    book = load_words()
    bw = [t[0] for t in book]
    print(f"== ORDER: {n} words, any order")
    found = 0
    for i in range(len(bw) - n + 1):
        if bw[i] in want and collections.Counter(bw[i:i + n]) == want:
            print(f"  BOOK RUN: {cite(book[i])}  «{' '.join(t[1] for t in book[i:i + n])}»")
            found += 1
            if found >= top:
                break
    if not found:
        # nearest windows: most of the words within n+3 words
        best = []
        for i in range(len(bw) - n):
            win = collections.Counter(bw[i:i + n + 3])
            got = sum(min(c, win[w]) for w, c in want.items())
            if got >= max(2, n - 1):
                best.append((got, i))
        best.sort(key=lambda x: -x[0])
        for got, i in best[:top]:
            print(f"  near ({got}/{n}): {cite(book[i])}  «{' '.join(t[1] for t in book[i:i + n + 3])}»")
        if not best:
            print("  no book window; not a book quote (order it by grammar)")
    return found > 0


# ------------------------------------------------------------------ ciphers
def letters_only(s):
    return re.sub(r"[^A-Za-z]", "", s).upper()


def rail_decode(c, k):
    n = len(c)
    pat = list(range(k)) + list(range(k - 2, 0, -1))
    rails = [pat[i % len(pat)] for i in range(n)]
    order_ = sorted(range(n), key=lambda i: (rails[i], i))
    out = [""] * n
    for ch, i in zip(c, order_):
        out[i] = ch
    return "".join(out)


def columnar_decode(c, cols):
    n = len(c); rows = -(-n // cols); short = rows * cols - n
    lens = [rows - (1 if j >= cols - short else 0) for j in range(cols)]
    colstr, p = [], 0
    for L in lens:
        colstr.append(c[p:p + L]); p += L
    return "".join(colstr[j][r] for r in range(rows) for j in range(cols) if r < len(colstr[j]))


def vig(c, key, mode):
    k = [ord(x) - 65 for x in key]
    out = []
    for i, ch in enumerate(c):
        x, y = ord(ch) - 65, k[i % len(k)]
        out.append(chr(((x - y) if mode == "vig" else (y - x) if mode == "beau" else (x + y)) % 26 + 65))
    return "".join(out)


def segment(s):
    """Greedy-DP word segmentation of a letters-only string using book+dictionary vocab."""
    v = solvers.vocab()
    s = s.lower(); n = len(s)
    best = [(0.0, None)] * (n + 1)
    best[0] = (0.0, 0)
    for i in range(1, n + 1):
        cand = (-1e9, None)
        for j in range(max(0, i - 15), i):
            w = s[j:i]
            wt = v.get(w)
            if wt is None or (len(w) == 1 and w not in "ai"):
                sc = best[j][0] - 6 - len(w)
            else:
                sc = best[j][0] + min(wt, 60) ** 0.5 * len(w) / 3
            if sc > cand[0]:
                cand = (sc, j)
        best[i] = cand
    out, i = [], n
    while i > 0:
        j = best[i][1]; out.append(s[j:i]); i = j
    words = out[::-1]
    good = sum(len(w) for w in words if w in v and (len(w) > 2 or w in ("a", "i", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we")))
    return " ".join(words).upper(), good / max(1, n)


def cipher(text, top, extra_keys):
    raw = text.strip()
    c = letters_only(raw)
    spaced = len(raw.split()) > 1
    rows = []

    def add(name, plain, keep_spaces=False):
        if keep_spaces:
            sc = en(plain); shown = plain
        else:
            shown, sc = segment(plain)
        rows.append((sc, name, shown))

    add("reverse", raw[::-1].upper(), spaced)
    add("reverse each word", " ".join(w[::-1] for w in raw.upper().split()), True)
    for k in range(2, 7):
        add(f"rail fence {k}", rail_decode(c, k))
    for k in range(2, 9):
        add(f"columnar {k} cols", columnar_decode(c, k))
        add(f"read down {k} cols", "".join(c[j::k] for j in range(k)))
    keys = BOOK_KEYS + [k.strip().upper() for k in extra_keys.split(",") if k.strip()]
    for key in keys:
        key = letters_only(key)
        if not key:
            continue
        for mode in ("vig", "beau", "plus"):
            p = vig(c, key, mode)
            if spaced:  # restore word breaks
                it = iter(p); p = "".join(next(it) if ch.isalpha() else ch for ch in raw.upper() if ch.isalpha() or ch == " ")
                add(f"{mode} key={key}", p, True)
            else:
                add(f"{mode} key={key}", p)
    if spaced and len(set(c)) > 5:
        words = [list(letters_only(w)) for w in raw.split() if letters_only(w)]
        if all(len(w) <= 15 for w in words):
            for score, t, m in solvers.solve_crib(words, {}, 2):
                rows.append((en(t) - 0.05, "cryptogram (substitution)", t.upper()))
    rows.sort(key=lambda r: -r[0])
    print("== CIPHER (best first; english = share of real words)")
    for sc, name, p in rows[:top]:
        flag = "  <-- English-like" if sc >= 0.75 else ""
        print(f"  {sc:4.2f}  {name:26} {p[:90]}{flag}")
    print("  (also run: solvers.py all \"…\"  for caesar/atbash/a1z26/morse/…)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["words", "order", "cipher", "all"])
    ap.add_argument("text")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--keys", default="", help="extra cipher keys, comma-separated")
    a = ap.parse_args()
    if a.mode in ("words", "all"):
        per_word(a.text, a.top)
    if a.mode in ("order", "all"):
        order(a.text, a.top)
    if a.mode in ("cipher", "all"):
        cipher(a.text, a.top, a.keys)


if __name__ == "__main__":
    main()
