"""Hyphenation rules shared by your index builder and corpus.py.

Calibrated against the physical book (calibration/spotcheck_01.md):
- The transcriber sometimes moved a line-break hyphen to the start of the next line
  ("battle" / "-tested" is printed "battle-" / "tested").
- Mid-line syllable hyphens ("watch-ing") are transcription leftovers; print has "watching".
- Line-end hyphens are either syllable breaks ("con-" / "tinues") or real compounds
  ("battle-" / "tested"); `join_break` decides using the book's own vocabulary.
"""
import re

KEEP_HYPHEN = {"jiu-jitsu"}  # real compounds that happen to look like syllable splits


def core(word):
    return re.sub(r"[^A-Za-z']", "", word).lower()


def build_vocab(lines):
    """Words seen whole (not first/last on a line, no hyphen) anywhere in the book."""
    vocab = set()
    for words in lines:
        for w in words[1:-1]:
            if "-" not in w and "—" not in w:
                vocab.add(core(w))
    return vocab


def fix_midline(word, vocab):
    """'watch-ing,"' -> 'watching,"' when the joined form is a known whole word."""
    c = re.sub(r"[^A-Za-z'-]", "", word).lower()
    if c.count("-") != 1 or c.startswith("-") or c.endswith("-") or c in KEEP_HYPHEN:
        return word
    if c.replace("-", "") in vocab:
        return word.replace("-", "", 1)
    return word


def join_break(left, right, vocab):
    """Join a word split across lines: left ends with '-'. Returns the joined token."""
    stem = left[:-1]
    joined = core(stem + right)
    if joined in vocab:
        return stem + right                      # syllable break: con- tinues -> continues
    if core(stem) in vocab and core(right) in vocab:
        return stem + "-" + right                # compound: battle- tested -> battle-tested
    return stem + right
