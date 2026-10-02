# The Sidekick overlay

An always-on-top Electron panel (~400px) that sits beside your browser during a timed puzzle. It sees what
you see and solves *with* you. It never touches the puzzle site — you click, type and submit.

```sh
cd tools/sidekick && npm install && npm start
```

macOS: grant **Screen Recording** permission on first launch.

## The loop

```
screen change ──> capture ──> PRE-PASS (no model) ──┬──> quick lane  (fast model)  ──> pins + steps
                                                    └──> verified lane (strong model) ──> replaces them
```

### 1. Capture

`⌃⌥W` turns on **watch mode**: the panel captures whenever the screen changes *and settles* (block-diff, with
the menu bar and Dock masked out), plus a nudge after 60s with no progress. `⌃⌥S` takes a single look.
`⌃⌥R` records a clip via ffmpeg for anything animated.

**Adaptive watch** is what makes this usable rather than maddening. It learns which cells of the screen change
on their own — countdown timers, pulsing icons, ambient animation — and stops treating them as events. It
diffs the OCR between looks and tells the model exactly which text appeared or disappeared, detects scrolling
and moves existing pins with the page, and escalates to the verified lane when it sees a new stage, a
multi-line change, or page feedback like `NO` / `CORRECT`.

### 2. Pre-pass — the important part

Before any model call, every screenshot goes through:

- **native OCR** (`tools/ocr/ocr`, Vision framework) → every text line with bounding boxes as screen fractions;
- **`corpus.py probe`** on that text → codes, rarest-phrase search, anagrams, page references;
- **`grid.py read`** → tile grids with symbol classes, highlighted cells, marker tiles, and empty input fields
  that OCR cannot see — all with exact boxes.

The model receives this as structured text. It opens the image only for what the pre-pass cannot give:
layout, colour, pictures. The boxes are also what make the on-screen drawing exact — the agent never guesses
where a tile or an empty field is.

### 3. Two lanes

| Lane | Model | Budget | Job |
|---|---|---|---|
| ⚡ quick | fast | ~15s, ≤2 tool calls | lead with the best current read and a confidence |
| ✓ verified | strong | as long as it needs | check properly; its output replaces the quick lane's |

Watch-mode turns use only the quick lane. Steps that would *enter a solution* wait for the verified lane —
a cheap rule that prevents the fast model from submitting a guess.

### 4. Output: answers drawn on your screen

The agent emits tagged markup that the panel renders onto the display:

| Tag | Effect |
|---|---|
| `<place box=… n=…>TEXT</place>` | dashed outline on that region + a draggable answer card (blurred unless you asked for full answers) |
| `<place kind="label" …>` | a small numbered item tag |
| `<answer conf=… cite=…>` | a blurred answer chip in the panel; `cite` is required whenever the answer rests on the corpus |
| `<step do="hover\|click\|drag\|type\|scroll\|record\|look" at=… to=…>` | a numbered **Next steps** card plus markers and drag arrows drawn on screen |

Hint levels (`nudge` / `hint` / `solve`) control how much is revealed, so the same system works whether you
want a push or the answer.

### 5. State rules that mattered

Two rules fixed more failures than any model change:

- **Do not re-plan on the effects of pending steps.** If the agent has told you to swap two tiles and you have
  not done it yet, the next screenshot still shows the old board. Planning against it produces contradictory
  instructions.
- **Never re-issue a toggle blind.** Swaps and marks flip state. Re-issuing one undoes it. Toggles are tracked
  and only emitted once.

### Slash commands

`/anagram`, `/probe`, `/search`, `/decode`, `/page`, `/solvers`, `/zoom … $LAST`, `/r <cmd>` run the
deterministic tools directly and feed their output back into the conversation.

## The agent playbook

`tools/sidekick/prompt.md` is the system prompt, and it is the file to edit when adapting this to your own
hunt. Its spine is general:

> read the rules → list the unknowns → ask the player for the *cheapest* observation that resolves one →
> decode deterministically → check the result against every stated constraint → only then answer.

It also carries the house rules: cite whenever a claim rests on the corpus, never guess a corpus fact,
prefer a tool over a hunch, and never automate the puzzle site.
