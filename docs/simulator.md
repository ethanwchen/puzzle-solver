# The simulator harness

You cannot debug a solver against a puzzle that runs once, under a clock, with no ground truth. So this
builds replicas you can run a thousand times.

Full tool reference: [`tools/simulator/README.md`](../tools/simulator/README.md).

## Three layers

### 1. Variants — seeded, self-grading puzzle engines

`tools/simulator/variants/*.html` are parameterised re-implementations of puzzle mechanics:

| Variant | Mechanic |
|---|---|
| `game7.html` | items blinking Morse on a timer; order the right ones |
| `game8.html`, `game8b.html` | letter grid with movable row/column markers; read the message between |
| `game9.html` | symbol→direction key, follow the route |
| `game9b.html` | the same with rule permutations: diagonal, jump, relative-turn, pipe-shape |
| `game9d.html` | fragment cards + a key card, with near-miss glyphs that encode nothing |
| `game9m.html` | actual mazes: decoy exits, loops, a lit decoy corridor |
| `game9z.html` | an oversized board in a pan/zoom viewport — you must fit it before you can read it |
| `game9t.html` | the same maze rendered as a badly printed plate: grain, ink bleed, vignette, press skew |

Every one takes `?seed=N` for a reproducible board and `?truth=1` to export `window.__truth`. Correct answers
are compared as **SHA-256 hashes**, so a solver pointed at the page cannot read the answer out of the DOM.

Shared pieces live in `variants/common.js` (seeded RNG, clue frame, clock, confirm dialog, hashed grading) and
`variants/maze_gen.js` (perfect maze, cut-off decoy exits, unique-shortest loops, lit dead-end corridor).

### 2. Offline eval matrices — the cheap loop

`tools/simulator/eval/*.js` generate dozens of boards, screenshot them headlessly, run a reader, and diff
against ground truth. **No model, no agent cost**, a couple of minutes end to end.

```sh
python3 -m http.server 8777 --bind 127.0.0.1 &
node tools/simulator/eval/maze_matrix.js        # maze.py across styles x sizes x exits x loops
node tools/simulator/eval/maze_matrix9z.js      # oversized boards, read before and after "fit"
node tools/simulator/eval/maze_matrix9t.js      # printed-plate artwork
```

Each prints a `PASS`/`FAIL` line per board with the specific discrepancy and the path to the failing
screenshot. This is where reader bugs get found. A worked example: a pan/zoom viewport draws a frame around
the board, that frame is its own connected component, and it beat the board on area — so the reader locked
onto the frame and read a 14×14 board as 18×24. The matrix surfaced it in one run.

**Report the metric you actually mean.** `maze_matrix9t.js` reports *route correct* separately from *lit
decoy reported*, because the route is the answer and the rest is advisory. Collapsing them hides real passes.

### 3. `drive.js` — the end-to-end player

A generic scripted player. It turns on watch mode and does **only** what the sidekick's `<step>`s say: hover,
click, drag, type, scroll, record. If the sidekick goes quiet it asks "what next?"; it stops when the page
shows its finish text.

```sh
cd tools/simulator
./run.sh v9 "http://127.0.0.1:8777/variants/game9m.html?style=walls&lit=1&seed=11"
PORT=9449 ./run.sh v7 "http://127.0.0.1:8777/variants/game7.html?seed=1"   # run several at once
```

`SIDEKICK_SOURCE=<dir>` makes a hidden sidekick instance read `<dir>/latest.png` as its screen instead of the
real display, so tests run headless and in parallel. `drive.js --real` instead drives a headed browser on the
actual screen while a normal sidekick watches the display.

Because the player contributes no intelligence, **a pass means the solver drove the whole game itself.**
Results append to `results.tsv`.

## The method

1. Build a variant for the mechanic you expect.
2. Write an eval matrix; fix the reader until it is green across seeds, sizes and styles.
3. Run `drive.js` end to end.
4. When a reader fails, decide honestly whether to fix it or document it. Two of the fixes attempted on
   `maze.py` made the matrix *worse* (24/24 → 13/24, and 9/18 → 8/18) and were reverted. A measured regression
   is worth more than a plausible-sounding patch.
5. Record what is still broken. The README's iteration tables carry known failures, including a reader that
   cannot read printed-plate artwork at all — better to know that before a live round than during one.
