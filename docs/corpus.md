# The corpus

Tools in this repo cite everything as `p<page>:L<line>[:w<word>]` — a *physical* location, so any claim can be
checked by hand against the printed source. That only works if your index preserves the printed page and line
breaks, rather than reflowing the text.

**No corpus ships with this repo**, and `.gitignore` excludes `book/`, `corpus/`, `*.pdf` and `*.tsv`. Index
your own source locally. Only index something you have the right to use, and keep the index private.

## Layout

`corpus.py` expects a `book/` directory at the repo root:

```
book/
  lines.tsv        one row per printed line
  words.tsv        one row per printed word
  page_shapes.tsv  per-page layout fingerprint (optional; needed for `corpus.py layout`)
```

### `lines.tsv`

Tab-separated, with a header row:

| column | meaning |
|---|---|
| `page` | printed page number as a string (`1`, `252`, or `front` for front matter) |
| `line` | 1-based line number on that page; `0` for a chapter heading or a front-matter block |
| `chapter` | chapter identifier |
| `section` | human-readable section name |
| `text` | the line exactly as printed, including end-of-line hyphenation |

```
page	line	chapter	section	text
252	16	66	Game #3	the bunkers promised safety right up until they didn't
```

### `words.tsv`

| column | meaning |
|---|---|
| `page` | printed page |
| `line` | line on the page |
| `word_idx` | 1-based index of the word within the line |
| `word` | the word as printed |

This is what makes book ciphers work: `corpus.py decode "252:16:3"` resolves page 252, line 16, word 3.

### `page_shapes.tsv` (optional)

Fingerprints each page by its shape so a screenshot of an unlabelled page can be matched back to it.

| column | meaning |
|---|---|
| `page` | printed page |
| `lines` | number of lines on the page |
| `short_lines` | comma-separated indices of lines shorter than full measure |
| `indented_lines` | comma-separated indices of indented lines |
| `signature` | per-line `L<fill-ratio>` / `I<indent-ratio>` tokens |

## Writing your own builder

There is no builder in this repo, because any real one is specific to your source's PDF or EPUB. A builder
needs to:

1. extract text **per printed page**, keeping the publisher's page numbers rather than PDF page indices;
2. keep hard line breaks, including hyphenation (`mak-` / `ing`) — `tools/textnorm.py` holds the de-hyphenation
   rules used at query time, so the index should store lines *as printed*;
3. emit the TSVs above.

Spot-check a few pages against the physical copy before trusting it; an off-by-one in page numbering silently
corrupts every citation.

## Using it

```sh
python3 tools/corpus.py search "between the walls"       # regex/phrase, matches across line breaks
python3 tools/corpus.py search QOPH --letters            # letters only: finds "Q-O-P-H"
python3 tools/corpus.py page 252                         # a page with line numbers
python3 tools/corpus.py decode "252:16:3 253:1:7"        # book cipher
python3 tools/corpus.py --pages 249-288 probe "<screen text>"   # fast triage over one section
```

`probe` is the one to reach for first on a live board: it runs code detection, rarest-phrase search, anagram
checks and page-reference extraction in a fraction of a second.
