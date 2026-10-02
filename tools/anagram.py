#!/usr/bin/env python3
"""Anagram solver tuned for the book: letters in, ranked words/phrases out, book-first.

  anagram.py LETTERS                      everything below, ranked
  anagram.py LETTERS --lengths "4 3 5"    only phrases with these word lengths (in this order); huge speed-up
  anagram.py LETTERS --known "?O?? ?H? ?????"   fix known letters (implies lengths); ? = unknown
  anagram.py LETTERS --max-words 4 --dict       allow English dictionary words, not just book words
  anagram.py LETTERS --top 30

Sections printed:
  BOOK RUNS    consecutive words ANYWHERE in the book (crossing lines/pages) that use exactly these letters, cited
               p:L:w. The strongest evidence for a book-based puzzle.
  WORDS        single words (book vocabulary, then dictionary) that use all the letters
  PHRASES      multi-word combinations from book vocabulary (plus the dictionary with --dict), ranked by how
               "bookish" they are: words the book uses often, adjacent pairs the book actually contains.
Non-letters in LETTERS are ignored, so "RIDE A TIGER" and "rideatiger" are the same input.
"""
import argparse
import collections
import csv
import math
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def letters_of(s):
    return re.sub(r"[^a-z]", "", s.lower())


def load_book():
    toks = []  # (word, page, line, idx)
    with open(os.path.join(ROOT, "book", "words.tsv"), newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            w = letters_of(r["word"])
            if w:
                toks.append((w, r["page"], r["line"], r["word_idx"]))
    return toks


def book_runs(toks, target, max_words=12):
    n = len(target)
    key = sorted(target)
    out, seen = [], set()
    for i in range(len(toks)):
        total = 0
        for j in range(i, min(len(toks), i + max_words)):
            total += len(toks[j][0])
            if total > n:
                break
            if total == n:
                s = "".join(t[0] for t in toks[i:j + 1])
                if sorted(s) == key:
                    phrase = " ".join(t[0] for t in toks[i:j + 1])
                    if phrase not in seen:
                        seen.add(phrase)
                        w, p, l, k = toks[i]
                        out.append((f"p{p}:L{l}:w{k}", phrase))
                break
    return out


def dict_words():
    try:
        with open("/usr/share/dict/words") as f:
            return {w.strip().lower() for w in f if w.strip().isalpha() and (len(w.strip()) > 1 or w.strip().lower() in "ai")}
    except OSError:
        return set()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("letters")
    ap.add_argument("--lengths")
    ap.add_argument("--known")
    ap.add_argument("--max-words", type=int, default=5)
    ap.add_argument("--dict", action="store_true", help="also use /usr/share/dict/words for phrases")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--seconds", type=float, default=6.0, help="time budget for the phrase search")
    a = ap.parse_args()

    target = letters_of(a.letters)
    if not target:
        sys.exit("no letters")
    need = collections.Counter(target)
    lengths = [int(x) for x in a.lengths.split()] if a.lengths else None
    known = None
    if a.known:
        known = [letters_of(w.replace("?", "0")) and w.lower() for w in a.known.split()]
        lengths = [len(w) for w in known]
    if lengths and sum(lengths) != len(target):
        sys.exit(f"lengths add up to {sum(lengths)} but there are {len(target)} letters")

    toks = load_book()
    freq = collections.Counter(t[0] for t in toks)
    pairs = collections.Counter((toks[i][0], toks[i + 1][0]) for i in range(len(toks) - 1))
    print(f"{len(target)} letters: {''.join(sorted(target)).upper()}")

    runs = book_runs(toks, target)
    print("\nBOOK RUNS (consecutive words in the book using exactly these letters):")
    for cite, phrase in runs[:a.top]:
        print(f"  {cite}  {phrase.upper()}")
    if not runs:
        print("  none")

    dwords = dict_words()
    key = sorted(target)
    singles = sorted({w for w in set(freq) | dwords if len(w) == len(target) and sorted(w) == key},
                     key=lambda w: (-freq[w], w))
    print("\nWORDS:")
    print("  " + (", ".join(f"{w.upper()}{' (book x%d)' % freq[w] if freq[w] else ''}" for w in singles[:a.top]) or "none"))

    # ---- multi-word phrases ----
    # Phrase vocabulary: real words only. Corpus tokens must be dictionary words or recur (proper names); short
    # words come from a common list so abbreviations (DC, TV) and glued tokens don't flood the results.
    SHORT = set("a i am an as at be by do go he hi if in is it me my no of oh ok on or so to up us we".split())
    def good(w):
        if len(w) <= 2:
            return w in SHORT
        return w in dwords or freq[w] >= 3
    vocab = {w for w in freq if good(w)} | ({w for w in dwords if len(w) > 2 or w in SHORT} if a.dict else set())
    fits = [w for w in vocab if not (collections.Counter(w) - need)]
    by_len = collections.defaultdict(list)
    for w in fits:
        by_len[len(w)].append(w)
    for L in by_len:
        by_len[L].sort(key=lambda w: -freq[w])

    def score(ws):
        s = sum(math.log(1 + freq[w]) for w in ws) / len(ws)
        s += sum(3.0 for x, y in zip(ws, ws[1:]) if pairs[(x, y)])  # the book says these words together
        s -= 1.5 * (len(ws) - 1)
        s -= sum(2.0 for w in ws if not freq[w])  # dictionary-only word
        return s

    results = {}
    deadline = time.time() + a.seconds
    timed_out = False

    def matches_known(w, pos):
        if not known:
            return True
        pat = known[pos]
        return all(p == "?" or p == c for p, c in zip(pat, w))

    def search(rem, ws):
        nonlocal timed_out
        if time.time() > deadline:
            timed_out = True
            return
        if not rem:
            if len(ws) > 1 or lengths:
                ph = tuple(ws) if lengths else tuple(sorted(ws))
                results[ph] = score(list(ph)) if not lengths else score(ws)
            return
        pos = len(ws)
        if lengths:
            if pos >= len(lengths):
                return
            cands = by_len.get(lengths[pos], [])
        else:
            if pos >= a.max_words:
                return
            left = sum(rem.values())
            cands = [w for L in sorted(by_len, reverse=True) if L <= left for w in by_len[L]]
            if ws:  # unordered search: enforce non-increasing (len, word) to avoid permutations
                last = ws[-1]
                cands = [w for w in cands if (len(w), w) <= (len(last), last)]
        for w in cands:
            if not matches_known(w, pos):
                continue
            c = collections.Counter(w)
            if c - rem:
                continue
            search(rem - c, ws + [w])

    search(need, [])
    if not lengths:  # unordered finds: show each in the word order the book likes best
        import itertools
        reordered = {}
        for ws, sc in results.items():
            best = max(itertools.permutations(ws), key=lambda p: sum(pairs[(x, y)] > 0 for x, y in zip(p, p[1:])))
            reordered[best] = score(list(best))
        results = reordered
    ranked = sorted(results.items(), key=lambda kv: -kv[1])
    label = "PHRASES" + (f" (lengths {' '.join(map(str, lengths))})" if lengths else f" (up to {a.max_words} words, any order)")
    print(f"\n{label}:" + ("  [time budget hit: partial; add --lengths/--known to narrow]" if timed_out else ""))
    for ws, sc in ranked[:a.top]:
        tag = " ← book says these words together" if any(pairs[(x, y)] for x, y in zip(ws, ws[1:])) else ""
        print(f"  {' '.join(ws).upper():40s} {sc:5.1f}{tag}")
    if not ranked:
        print("  none")
    if not lengths:
        print("\n(unordered search: word order is yours to choose; pass --lengths or --known to get ordered phrases)")


if __name__ == "__main__":
    main()
