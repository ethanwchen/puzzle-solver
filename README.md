# puzzle-solver

An **overlay solver**: a small always-on-top panel that watches your screen while you play a timed puzzle
hunt, reads each board deterministically, and tells you the next move — while *you* stay the one clicking,
typing and submitting.

It was built for a book-keyed puzzle hunt, where every answer had to be traceable to a line in a source text.
The hunt-specific data is gone; what is here is the framework, and it generalises to any hunt with a
**corpus** (a text you can cite) and **boards** (things on screen you have to read).

> **No source text ships with this repo.** You bring your own corpus and index it locally; `.gitignore` keeps
> it and everything derived from it out of git. Nothing here trains a model — the corpus is only ever indexed
> for local lookup and cited back at you.

---

## Why an overlay, and not a bot

The constraint that shaped every design decision: **the tool never touches the puzzle site.** It reads pixels
from your screen and prints advice. You act. That is a deliberate rule, not a limitation —
it keeps a solver usable in contests where automation is against the rules, and it means the solver has to be
honest, because a human is checking every move before it happens.

Everything else follows from that:

- it must read a board from a **screenshot**, so the readers are computer-vision tools, not DOM scrapers;
- it must be **fast**, because the clock is running, so cheap deterministic passes run before any model call;
- it must **cite**, because a confident wrong answer costs you the round.

## The three pieces

### 1. Deterministic readers (`tools/`)

Model calls are slow and guess. These do not: they turn a screenshot into structured data, or say they
could not. That line — *solve it in code, ask the model only what code cannot decide* — is the core idea.

| Tool | Reads |
|---|---|
| `grid.py` | tile grids, symbol classes, highlighted cells, marker tiles, dashed input boxes — all with pixel boxes |
| `maze.py` | which sides of each cell are open, the glowing start, lit decoy corridors, and the route out |
| `motion.py` | a screen recording → what moved, on/off timings, Morse in both polarities |
| `bars.py` | redaction bars and mask rows → a layout signature |
| `zoom.py` | enlarges small glyphs into numbered cells before you read them |
| `ocr/ocr.swift` | native Vision OCR with bounding boxes |
| `solvers.py` | substitution/crib, word ladders, 17 classical code tables |
| `anagram.py`, `unscramble.py`, `lengths.py` | corpus-first anagrams, scrambles, word-length pattern matching |
| `corpus.py` | the corpus query CLI: search, page/line/word, book-cipher decode, acrostic, grille, layout |

### 2. The Sidekick overlay (`tools/sidekick/`)

An Electron panel that sits beside your browser. See **[docs/sidekick.md](docs/sidekick.md)** for the full
design; the ideas worth stealing:

- **Pre-pass before prompt.** Every screenshot is OCR'd and run through the board readers *first*. The model
  receives structured text and exact boxes, not a bare image. Most turns need no further tool call.
- **Two lanes.** A quick lane answers in ~15s; a verified lane checks properly in parallel. Verified output
  replaces quick output on screen. You see a usable answer immediately and a trustworthy one shortly after.
- **Adaptive watch.** It learns which screen cells change on their own (timers, pulsing icons) and ignores
  them, diffs the OCR between looks, and escalates to the verified lane on a new stage or a wrong-answer
  message.
- **Answers drawn in place.** `<place box=… >TEXT</place>` outlines the tile on your screen and pins a card
  to it; `<step do="click|drag|type|record" at=…>` renders numbered markers for your next physical actions.
- **Never re-issue a toggle.** Swaps and marks are state; the planner does not re-plan on the effects of
  steps you have not performed yet. This one rule took a game from 33% to 100%.

### 3. The simulator harness (`tools/simulator/`)

The part most people skip, and the reason the rest works. You cannot iterate on a solver against a live
puzzle that runs once — so this builds **seeded, self-grading replicas** of puzzle engines and a scripted
player that follows *only* the sidekick's emitted steps. A pass means the solver drove the whole game itself.

- `variants/*.html` — parameterised puzzle engines (mazes, symbol-key routes, Morse-blinking items, grid
  ciphers), each with `?seed=N` and `truth=1` to export ground truth.
- `drive.js` — a generic player. It turns on watch mode and does nothing but execute the sidekick's steps.
- `eval/*.js` — **offline matrices**: run the readers across dozens of generated boards and check them against
  ground truth, with no model in the loop and no agent cost. This is how you find a reader bug in a minute
  rather than during a live round.

See **[docs/simulator.md](docs/simulator.md)**. Answers are stored only as SHA-256 hashes, so a solver
pointed at the harness cannot cheat by reading the page.

---

## Quick start

```sh
git clone https://github.com/ethanwchen/puzzle-solver && cd puzzle-solver

# 1. Readers (Python 3 + OpenCV)
pip install opencv-python numpy
python3 tools/maze.py --help

# 2. Harness: serve the variants and run the offline reader matrix
python3 -m http.server 8777 --bind 127.0.0.1 &
cd tools/simulator && npm install && cd ../..
node tools/simulator/eval/maze_matrix.js

# 3. Overlay (macOS; needs Screen Recording permission)
cd tools/sidekick && npm install && npm start
```

To use it against a real hunt you also need a corpus: index your source text into the TSV format described in
**[docs/corpus.md](docs/corpus.md)**, drop it in `book/` (gitignored), and `corpus.py` lights up.

## Adapting this to your hunt

1. **Index your corpus** → `docs/corpus.md`. Everything citable flows from this.
2. **Write a variant** for each puzzle engine you expect, in `tools/simulator/variants/`. Copy the closest
   existing one; they all share `common.js` (seeded RNG, clue frame, hashed grading).
3. **Write an eval matrix** for it in `tools/simulator/eval/`. Generate boards, run the reader, diff against
   `window.__truth`. Fix the reader until the matrix is green.
4. **Point the sidekick at it** with `./run.sh NAME URL` and let `drive.js` play. If it finishes unaided,
   the loop works end to end.
5. **Edit `tools/sidekick/prompt.md`** — the agent playbook — to describe your hunt's conventions.

## A note on scope and fairness

This reads your screen and nothing else. It does not log in, fetch, script, or automate any puzzle site, and
the agent prompt forbids it. If you adapt this, keep that rule: check the rules of whatever you are entering,
and let the tool advise while you play.

## License

MIT — see [LICENSE](LICENSE).
