#!/usr/bin/env python3
"""Deterministic solvers for recurring puzzle mechanics. Seconds instead of minutes of agent reasoning.

  solvers.py crib "SYMS" [--known "S1=V,S2=E"] [--space SYM | --find-space] [--top N]
        substitution cipher over arbitrary symbol IDs (glyph labels you invent, e.g. Kr Qo Rf ...).
        Words separated by " / " if known; otherwise --find-space tries each repeated symbol as SPACE.
  solvers.py ladder W1 W2 ... [--start W] [--end W]
        order words into one-letter-change chain(s) (word ladder); prints every valid full chain
  solvers.py table KIND "INPUT"
        KIND: a1z26 | a0z25 | morse | morse-rev | nato | braille | semaphore | flags | atbash | caesar |
              keypad | binary5 | base3 | colorpair | periodic | periodic-split | roman
  solvers.py all "INPUT"      try every applicable table at once and flag outputs that look like English
"""
import argparse
import collections
import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- vocabulary / scoring

_VOCAB = None


def vocab():
    """word -> weight. Book words dominate (they are what puzzles are built from); dictionary fills gaps."""
    global _VOCAB
    if _VOCAB is None:
        freq = collections.Counter()
        with open(ROOT / "book" / "words.tsv") as f:
            next(f)
            for line in f:
                w = re.sub(r"[^a-z]", "", line.rstrip("\n").split("\t")[-1].lower())
                if w:
                    freq[w] += 1
        v = {w: 10.0 + c for w, c in freq.items()}
        for p in ("/usr/share/dict/words",):
            try:
                for w in open(p):
                    w = w.strip().lower()
                    if w.isalpha() and w not in v:
                        v[w] = 1.0 if len(w) > 2 else 0.2
            except OSError:
                pass
        _VOCAB = v
    return _VOCAB


def pattern(seq):
    m = {}
    return tuple(m.setdefault(x, len(m)) for x in seq)


def english_score(text):
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return 0.0
    v = vocab()
    return sum(1 for w in words if w in v and (len(w) > 1 or w in "ai")) / len(words)


# ---------------------------------------------------------------- crib / substitution solver

def solve_crib(words, known, top):
    """words: list of lists of symbols. known: symbol->letter. Returns ranked (score, mapping)."""
    v = vocab()
    by_pat = collections.defaultdict(list)
    for w, wt in v.items():
        by_pat[(len(w), pattern(w))].append((w, wt))
    for k in by_pat:
        by_pat[k].sort(key=lambda x: -x[1])

    uniq = list(dict.fromkeys(tuple(w) for w in words))
    # most constrained first: long words and words with many known symbols
    uniq.sort(key=lambda w: (-sum(s in known for s in w), -len(set(w))))
    results = []
    budget = [200000]

    def rec(i, mapping, used, score):
        budget[0] -= 1
        if budget[0] < 0:
            return
        if i == len(uniq):
            results.append((score, dict(mapping)))
            return
        w = uniq[i]
        for cand, wt in by_pat.get((len(w), pattern(w)), [])[:4000]:
            ok, added = True, []
            for s, ch in zip(w, cand):
                if s in mapping:
                    if mapping[s] != ch:
                        ok = False
                        break
                elif ch in used:
                    ok = False
                    break
                else:
                    mapping[s] = ch
                    used.add(ch)
                    added.append(s)
            if ok:
                rec(i + 1, mapping, used, score + min(wt, 60.0) ** 0.5)
            for s in added:
                used.discard(mapping.pop(s))

    mapping = {k: v_.lower() for k, v_ in known.items()}
    rec(0, mapping, set(mapping.values()), 0.0)
    results.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for score, m in results:
        text = " ".join("".join(m.get(s, "?") for s in w) for w in words)
        if text not in seen:
            seen.add(text)
            out.append((score, text, m))
        if len(out) >= top:
            break
    return out


def cmd_crib(a):
    known = dict(kv.split("=") for kv in a.known.replace(" ", "").split(",") if kv) if a.known else {}
    toks = a.symbols.split()
    variants = []
    if " / " in a.symbols or a.space:
        sp = "/" if not a.space else a.space
        variants.append((sp, toks))
    elif a.find_space:
        counts = collections.Counter(toks)
        for sym, n in counts.most_common():
            if n >= 2 and sym not in known:
                variants.append((sym, toks))
    else:
        variants.append((None, toks))
    for sp, t in variants:
        if sp:
            words, cur = [], []
            for s in t:
                if s == sp:
                    if cur:
                        words.append(cur)
                    cur = []
                else:
                    cur.append(s)
            if cur:
                words.append(cur)
        else:
            words = [t]
        if any(len(w) > 15 for w in words):
            continue
        sols = solve_crib(words, known, a.top)
        if sols:
            label = f"SPACE={sp}" if sp and sp != "/" else "given word breaks" if sp else "no word breaks"
            print(f"== {label}")
            for score, text, m in sols:
                print(f"  {score:7.1f}  {text.upper()}")
            new = {s: c.upper() for s, c in sols[0][2].items() if s not in known}
            print("  key:", " ".join(f"{s}={c}" for s, c in sorted(new.items())))


# ---------------------------------------------------------------- word ladder

def cmd_ladder(a):
    words = [w.upper() for w in a.words]
    if a.start:
        words.append(a.start.upper())
    if a.end:
        words.append(a.end.upper())
    words = list(dict.fromkeys(words))
    adj = {w: [x for x in words if x != w and len(x) == len(w) and sum(p != q for p, q in zip(w, x)) == 1] for w in words}
    chains = []

    def dfs(path):
        if len(path) == len(words):
            if not a.end or path[-1] == a.end.upper():
                chains.append(list(path))
            return
        for n in adj[path[-1]]:
            if n not in path:
                path.append(n)
                dfs(path)
                path.pop()

    starts = [a.start.upper()] if a.start else words
    for s in starts:
        dfs([s])
    if not chains:
        print("no chain uses every word; degrees:", {w: len(n) for w, n in adj.items()})
        return
    uniq = []
    for c in chains:
        if c[::-1] not in uniq:
            uniq.append(c)
    print(f"{len(uniq)} chain(s) (reversals merged):")
    for c in uniq[:10]:
        print("  " + " -> ".join(c))
    ends = [w for w, n in adj.items() if len(n) == 1]
    print("forced endpoints (only one neighbour):", ", ".join(ends) or "none")


# ---------------------------------------------------------------- lookup tables

MORSE = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                 ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
                 "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.".split()))
MORSE_REV = {v: k for k, v in MORSE.items()}
NATO = "ALFA BRAVO CHARLIE DELTA ECHO FOXTROT GOLF HOTEL INDIA JULIETT KILO LIMA MIKE NOVEMBER OSCAR PAPA QUEBEC ROMEO SIERRA TANGO UNIFORM VICTOR WHISKEY XRAY YANKEE ZULU".split()
BRAILLE = {"1": "A", "12": "B", "14": "C", "145": "D", "15": "E", "124": "F", "1245": "G", "125": "H", "24": "I", "245": "J",
           "13": "K", "123": "L", "134": "M", "1345": "N", "135": "O", "1234": "P", "12345": "Q", "1235": "R", "234": "S",
           "2345": "T", "136": "U", "1236": "V", "2456": "W", "1346": "X", "13456": "Y", "1356": "Z"}
# Semaphore: flag positions as clock-ish directions 1-8 (1=down, 2=down-left, 3=left, 4=up-left, 5=up, 6=up-right, 7=right, 8=down-right)
SEMAPHORE = {"12": "A", "13": "B", "14": "C", "15": "D", "16": "E", "17": "F", "18": "G", "23": "H", "24": "I", "57": "J",
             "25": "K", "26": "L", "27": "M", "28": "N", "34": "O", "35": "P", "36": "Q", "37": "R", "38": "S", "45": "T",
             "46": "U", "58": "V", "67": "W", "68": "X", "47": "Y", "78": "Z"}
# International Code of Signals flag descriptions -> letter (keywords matched loosely)
FLAGS = [
    ("A", "white blue swallowtail"), ("B", "red swallowtail"), ("C", "blue white red white blue horizontal"),
    ("D", "yellow blue yellow horizontal"), ("E", "blue over red"), ("F", "white red diamond"),
    ("G", "yellow blue vertical stripes"), ("H", "white red vertical"), ("I", "yellow black circle disc"),
    ("J", "blue white blue horizontal"), ("K", "yellow blue vertical halves"), ("L", "yellow black quarters"),
    ("M", "blue white saltire diagonal cross"), ("N", "blue white checkerboard checker"), ("O", "red yellow diagonal"),
    ("P", "blue white square center"), ("Q", "yellow solid"), ("R", "red yellow cross"),
    ("S", "white blue square center"), ("T", "red white blue vertical"), ("U", "red white quarters"),
    ("V", "white red saltire diagonal cross"), ("W", "blue border white red center"), ("X", "white blue cross"),
    ("Y", "yellow red diagonal stripes"), ("Z", "yellow blue red black triangles"),
]
COLOURS = {"white", "blue", "red", "yellow", "black"}
KEYPAD = {"2": "ABC", "3": "DEF", "4": "GHI", "5": "JKL", "6": "MNO", "7": "PQRS", "8": "TUV", "9": "WXYZ"}
ELEMENTS = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
            "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
            "Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv "
            "Ts Og").split()
# Telecom 25-pair colour code: tip (primary) x ring (secondary) -> pair 1..25 -> letter A..Y
PRIMARY = ["white", "red", "black", "yellow", "violet"]
SECONDARY = ["blue", "orange", "green", "brown", "slate"]
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def nums(s):
    return [int(x) for x in re.findall(r"\d+", s)]


def t_a1z26(s):
    return "".join(chr(64 + n) if 1 <= n <= 26 else f"[{n}]" for n in nums(s))


def t_a0z25(s):
    return "".join(chr(65 + n) if 0 <= n <= 25 else f"[{n}]" for n in nums(s))


def t_morse(s, rev=False):
    s = s.replace("•", ".").replace("·", ".").replace("—", "-").replace("_", "-")
    words = re.split(r"\s*[/|]\s*|\s{3,}", s.strip())
    out = []
    for w in words:
        letters = []
        for code in w.split():
            code = code[::-1] if rev else code
            letters.append(MORSE_REV.get(code, "?"))
        out.append("".join(letters))
    return " ".join(out)


def t_nato(s):
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", s) if w.upper() in NATO or w.upper() == "ALPHA")


def t_braille(s):
    return "".join(BRAILLE.get("".join(sorted(g)), "?") for g in re.findall(r"\d+", s))


def t_semaphore(s):
    return "".join(SEMAPHORE.get("".join(sorted(g)), "?") for g in re.findall(r"\d{2}", s))


def t_flags(s):
    out = []
    for desc in re.split(r"[;,\n|]", s):
        d = set(re.findall(r"[a-z]+", desc.lower()))
        if not d:
            continue
        first = next((w for w in re.findall(r"[a-z]+", desc.lower()) if w in COLOURS), None)
        # word overlap, plus a tie-break on the background (first-named) colour: S=white/blue vs P=blue/white
        best = max(FLAGS, key=lambda f: len(d & set(f[1].split())) + (0.5 if first == f[1].split()[0] else 0)
                   - 0.01 * len(f[1].split()))
        out.append(best[0])
    return "".join(out)


def t_atbash(s):
    return "".join(chr(155 - ord(c)) if c.isupper() else chr(219 - ord(c)) if c.islower() else c for c in s)


def t_caesar(s):
    rows = []
    for k in range(1, 26):
        r = "".join(chr((ord(c) - 65 + k) % 26 + 65) if c.isupper() else chr((ord(c) - 97 + k) % 26 + 97) if c.islower() else c for c in s)
        rows.append((english_score(r), k, r))
    rows.sort(reverse=True)
    return "\n".join(f"  +{k:<2} {r}  (english {sc:.2f})" for sc, k, r in rows[:5])


def t_keypad(s):
    out = []
    for g in re.findall(r"(\d)\1*", s):
        pass
    for run in re.findall(r"((\d)\2*)", s):
        digits, d = run
        if d in KEYPAD:
            keys = KEYPAD[d]
            out.append(keys[(len(digits) - 1) % len(keys)])
    return "".join(out)


def t_binary5(s):
    return "".join(chr(64 + int(b, 2)) if 1 <= int(b, 2) <= 26 else "?" for b in re.findall(r"[01]{5}", s))


def t_base3(s):
    return "".join(chr(64 + int(b, 3)) if 1 <= int(b, 3) <= 26 else "?" for b in re.findall(r"[012]{3}", s))


def t_colorpair(s):
    toks = re.findall(r"[a-z]+", s.lower())
    out = []
    for p, q in zip(toks[0::2], toks[1::2]):
        if p in PRIMARY and q in SECONDARY:
            out.append(chr(65 + PRIMARY.index(p) * 5 + SECONDARY.index(q)))
        elif q in PRIMARY and p in SECONDARY:
            out.append(chr(65 + PRIMARY.index(q) * 5 + SECONDARY.index(p)))
        else:
            out.append("?")
    return "".join(out)


def t_periodic(s):
    return "".join(ELEMENTS[n - 1] if 1 <= n <= len(ELEMENTS) else f"[{n}]" for n in nums(s))


def t_periodic_split(s):
    w = re.sub(r"[^a-z]", "", s.lower())
    syms = {e.lower(): i + 1 for i, e in enumerate(ELEMENTS)}
    sols = []

    def rec(i, acc):
        if i == len(w):
            sols.append(acc)
            return
        for L in (1, 2):
            if w[i:i + L] in syms:
                rec(i + L, acc + [w[i:i + L].capitalize() + f"({syms[w[i:i + L]]})"])

    rec(0, [])
    return "\n".join("  " + " ".join(x) for x in sols[:5]) or "  (no element spelling)"


def t_roman(s):
    out = []
    for r in re.findall(r"[IVXLCDM]+", s.upper()):
        total = 0
        for i, c in enumerate(r):
            v = ROMAN[c]
            total += -v if i + 1 < len(r) and ROMAN[r[i + 1]] > v else v
        out.append(str(total))
    return " ".join(out)


TABLES = {
    "a1z26": t_a1z26, "a0z25": t_a0z25, "morse": t_morse, "morse-rev": lambda s: t_morse(s, rev=True),
    "nato": t_nato, "braille": t_braille, "semaphore": t_semaphore, "flags": t_flags, "atbash": t_atbash,
    "caesar": t_caesar, "keypad": t_keypad, "binary5": t_binary5, "base3": t_base3, "colorpair": t_colorpair,
    "periodic": t_periodic, "periodic-split": t_periodic_split, "roman": t_roman,
}


def cmd_table(a):
    print(TABLES[a.kind](a.input))


def cmd_all(a):
    s = a.input
    rows = []
    for k, f in TABLES.items():
        try:
            r = f(s)
        except Exception:
            continue
        if r and set(r) - set("?[] \n"):
            rows.append((english_score(r) if "\n" not in r else 0.5, k, r))
    for sc, k, r in sorted(rows, reverse=True):
        flag = "  <-- English-like" if sc >= 0.6 else ""
        print(f"{k:>14}: {r.strip()[:120]}{flag}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("crib"); s.add_argument("symbols"); s.add_argument("--known", default="")
    s.add_argument("--space"); s.add_argument("--find-space", action="store_true"); s.add_argument("--top", type=int, default=5)
    s = sp.add_parser("ladder"); s.add_argument("words", nargs="+"); s.add_argument("--start"); s.add_argument("--end")
    s = sp.add_parser("table"); s.add_argument("kind", choices=sorted(TABLES)); s.add_argument("input")
    s = sp.add_parser("all"); s.add_argument("input")
    a = ap.parse_args()
    {"crib": cmd_crib, "ladder": cmd_ladder, "table": cmd_table, "all": cmd_all}[a.cmd](a)


if __name__ == "__main__":
    main()
