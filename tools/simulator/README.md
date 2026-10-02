# Sidekick test harness

Practice puzzles and a scripted player, for testing the Sidekick's Watch mode end to end without touching the real
screen. The sidekick must never open this folder while solving (prompt.md says so; answers are stored only as SHA-256
hashes anyway).

## Puzzles
- `anagram.html?seed=N`, "The Scramble" (3 stages): unscramble a corpus quote from tiles, then WHO SAID IT?,
  then ON WHICH PAGE? It has 7 seeded quotes (p252–274), a ticking timer and ambient animation (noise).
- `scroll.html`, "The Roster": a corpus question on a long page, for checking that pins follow scrolling.
- `variants/game7.html?seed=N`: eyes blink words in 220 ms Morse after a countdown (hover to watch; drag into slots).
  Seeds not divisible by 3 use the **corpus rule**: names from the roster, "place the lost, earliest loss to latest"
  (ASHBY p101 → BRENNER p212 → CALLOW p219 → DUNMORE p258 → ELSWORTH p277 → FAIRBAIRN p434; the rest are decoys). Other seeds use
  the practice rule ONE–FOUR plus compass decoys.
- `variants/game8.html?seed=N`: 3×3 up to 4×5 letter grids, shuffled row/column markers over fixed letters, varied
  target orders, danger glyphs, corpus phrases; checks text + both axes.
- `variants/game9m.html?style=walls|tiles|cards&rows&cols&exits=1..4&lit=1&loops=N&start=bottom|any`: MAZE tunnels
  ("walk the space between the walls"): one reachable exit, decoy exits cut off, lit decoy corridor into a dead
  end, loops that keep the shortest way unique. Solver: `tools/maze.py`. Offline: `node tools/simulator/eval/maze_matrix.js`
  (24 boards: 24/24 routes; one 12×12 lit board over-reports lit tiles).
- `variants/game9d.html?set=arcs|letters|runes&nearmiss=0.3&lit=1`: FRAGMENT cards (cream cards, tilt, speckle) + a KEY/VIEW
  key card image; near-miss fragments (a stroke missing) encode nothing. Offline: `eval/reader_matrix9d.js`.
- `variants/game9b.html?move=dir|diag|jump|turn|pipe&exit=top|left|right|bottom&starts=1|3&entry=click|word&key=panel|legend|none`: G9 rule permutations (truth=1 exports the answer). Offline check: `node tools/simulator/eval/reader_matrix9b.js` (solver 24/24, reader+route 23/24; one pipe grid merges two pipe shapes).
- `variants/game9z.html?style=walls|tiles|cards&rows&cols&tile&zoom&open=start|corner|fit&exits&lit=1&loops&start`:
  OVERSIZED tunnels in a **pan/zoom viewport**, the one documented Challenge3 behaviour nothing else exercised —
  the board does not fit on screen at the opening zoom, and the solver must drag/wheel/**Home** to fit it first.
  Also the only variant with the engine's two real submission rules: *only one top-row exit stays marked* (picking
  another replaces it) and *Continue unlocks only once a top-edge cell is marked*.
  Offline: `node tools/simulator/eval/maze_matrix9z.js`.
- `variants/game9t.html?tone=sepia|blueprint|xray&rows&cols&grain&vignette&bleed&rot&exits&lit=1&loops`:
  the tunnels as a **badly printed plate** — paper grain, uneven development, ink bleed, vignette, press skew
  (e.g. a scanned plate from the corpus). `blueprint`/`xray` invert the ink/paper polarity. The maze itself is
  identical to game9m, so any failure here is a *reader* failure, not a solving failure.
  Offline: `node tools/simulator/eval/maze_matrix9t.js`.
- `variants/maze_gen.js`: the maze generator (perfect maze, cut-off decoy exits, unique-shortest loops, lit dead-end
  corridor) shared by game9z and game9t. `game9m.html` deliberately keeps its own inline copy — it is the validated
  reference board.
- `variants/game9.html?seed=N`: 5×5–7×7 tunnels whose tiles use symbols (◐, Ψ, ♠, Ⅰ, arrows) mapped by a key panel.
- A live hunt's own practice build, when one exists, is the best reference for the real engines. Point `run.sh` at
  its URL the same way you point it at a local variant.

## Run
```sh
cd tools/simulator && npm install          # playwright-core (uses a cached Chromium; set CHROME=... if needed)
./run.sh NAME URL [--intro S] [--max S] [--until REGEX]      # PORT=9449 ./run.sh … to run several at once
./run.sh v7 "http://127.0.0.1:8777/variants/game7.html?seed=1"
./run.sh g9 https://example.test/hunt/game-9 --intro 40
```
`drive.js` is a **generic player**. It turns on Watch mode (level = Answer) and does only what the sidekick's
`<step>`s say: hover, click, drag, type, scroll, or record (it screencasts the page when a record step fires). If the
sidekick goes quiet it asks "what next?", and it stops when the page shows the finish text. A pass therefore means the
sidekick drove the whole game itself. `SIDEKICK_SOURCE` makes a sidekick instance read `$SRC/latest.png` as its
screen, log pins/steps to its session folder, and stay invisible and click-through.

## Results
Every run is appended to `results.tsv` (URL, result, time to first steps, total seconds). On 2026-09-28, with the
generic player following only the sidekick's steps, all 14 runs in this batch passed (plus 3 earlier checks):
| Game | Runs | Result | Total time |
|---|---|---|---|
| Live-style G7 (Morse eyes, 8 eyes, 4 slots) | 2 | 100% both | 7.7 / 9.6 min |
| Live-style G9 (arrow tunnels) | 1 | 100% | 2.3 min |
| G7 variants (corpus rule seeds 1, 4; number rule seed 3) | 3 | 100% all | 2.6–3.4 min |
| G8 variants (4×4 grids, seeds 1, 2, 5) | 3 | 100% all | 1.7–2.9 min |
| G9 variants (symbol keys, seeds 1, 2, 3) | 3 | 100% all | 1.1–1.4 min |
| Anagram (3 stages, seeds 3, 5) | 2 | complete both | 4.4 / 2.7 min |
| Earlier: anagram seed 1, game 8 site, scroll | 3 | pass | |

Iteration 2 (same day): quick/verified lanes warmed up at launch; clip batches get a polarity-consistent,
each-word-once assignment (Hungarian, with a background decoy vocabulary); steps that re-appear keep their recorded
state; `--view` and seeded Morse units (170/200/250 ms) added. 10 more runs:
| Game | Result | Total time |
|---|---|---|
| Live-style G7 | 100% | 7.6 min (verified-lane analysis turn 356 s → 71 s) |
| G7 variants (corpus seeds 5, 11 @250 ms; numbers 12 @170 ms, 13 @200 ms) | 100% all | 3.1–3.8 min |
| G8 seed 7 @1440×900 · G9 seed 4 @1440×900 | 100% both | 1.9 / 2.5 min |
| Anagram seed 2 @1024×700 | complete | 1.7 min |
`eval/eval_clips.sh NAME` replays a run's clips through the analyzer + assignment offline (for tuning at no agent cost).

Iteration 3: deterministic grid tooling (`tools/grid.py`): board reader (tile grids, symbol classes via blurred-glyph
correlation + silhouette, highlighted start, marker tiles with boxes), G9 `route`, G8 `message` (text, the trap
reading, swap plan with the order after each move). Watch no longer re-plans on the effects of pending steps; toggles
(swaps, marks) are never re-issued blind.
| Game | Before | After |
|---|---|---|
| Live-style G9 | 136 s (92 s after Watch on) | 104–107 s (60–67 s after Watch on), route from grid.py |
| G9 variant seed 5 | n/a | 116 s |
| Live-style G8 | 33% (swaps re-issued blind) → 258 s | 100%, 221 s |
| G8 variant seed 3 | n/a | 100%, 186 s |

Iteration 4: `grid.py` now finds dashed answer boxes (gap-closing pass), keeps only evenly spaced rows/columns,
drops sparse ones, and infers unread keys on alphabetical trays; `eval/test_grid.py` is a regression test over the
reference screenshots (6/6 pass). Record steps size clips from the longest expected Morse word. `drive.js --real` runs a
headed browser on the actual screen while a normal (non-harness) Sidekick watches the display:
a live-style G9 on a real 1728×1117 Retina screen → **100%**, step markers drawn exactly on the route tiles.

Iteration 5 (2026-10-01): two new G9 simulators aimed at how the board is *presented* rather than how it is solved,
since every earlier variant fit on screen as crisp vector art.

**`maze.py` fix — framed viewports.** A pan/zoom viewport draws a frame around the board with padding inside it.
That frame is its own connected component and beat the board on area alone, so `board_box` locked onto the frame and
`maze.py` read a 14×14 board as 18×24. `board_box` now drops any candidate component that merely *encloses* a smaller
one. Regression: `maze_matrix.js` **23/24**, unchanged (the one failure is the pre-existing 12×12 lit over-report).

| Board | Result |
|---|---|
| `game9z` oversized + pan/zoom, after HOME (`maze_matrix9z.js`, 18 boards) | 9/18 routed |
| `game9z` read from the *cropped* opening view | refuses on 15/18 — it does not silently answer from a partial board |
| `game9t` printed plate, given rows/cols/start (`maze_matrix9t.js`, 15 boards) | 6/15 routed, 4/15 also got the lit decoy |
| `game9t` printed plate, unaided | **0/15** |

Two gaps this leaves open, both worth knowing before a live round:
- **Big boards.** After fitting, `count_grid` goes off by one on the larger boards (reads 20×12 as 21×12) because it
  breaks ties toward the finest division. Scoring the tie by autocorrelation strength instead made things worse
  (9→8 on 9z), so it is left alone. **Workaround: count the rows/cols off the screen and pass `--rows/--cols`.**
- **Plate artwork.** `maze.py` cannot read a grainy plate at all on its own, and only routes 6/15 even when handed
  the geometry. It mostly *refuses* rather than answering wrong, which is the safe failure — but if the live board is
  plate art rather than crisp tiles, treat `maze.py` as unavailable and read the route by eye.
