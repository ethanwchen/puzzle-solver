#!/usr/bin/env python3
"""Regression test for tools/grid.py on reference screenshots (run from the repo root):  python3 tools/simulator/eval/test_grid.py"""
import os, subprocess, sys, tempfile

CASES = [
    # (screenshot, expected substrings in `grid.py read` output)
    ("challenges/sim-game9/screen2.png", ["GRID 1: 6 rows × 6 cols", "symbol classes: 4", "highlighted: r6c3",
                                          "A   B   C   A   A   B", "A   A  C*   D   A   A"]),
    ("challenges/sim-game8/screen1.png", ["MARKERS: column of 3 tiles: 3 | 1 | 2"]),
    ("challenges/sim-game8/screen5.png", ["3 rows × 3 cols", "A  B~   C   D   E"]),
    ("tools/simulator/eval/fixtures/variant_game9_seed1.png", ["GRID 1: 7 rows × 7 cols", "symbol classes: 4", "highlighted: r7c2",
                                                               "A   B   A   C   A   C   B"]),
]
ROUTE = ("challenges/sim-game9/screen2.png", "A=DOWN,B=LEFT,C=UP,D=RIGHT",
         "(6,3) → (5,3) → (5,4) → (4,4) → (4,5) → (3,5) → (3,4) → (2,4) → (2,3) → (1,3)")

fails = 0
for img, want in CASES:
    out = subprocess.run([sys.executable, "tools/grid.py", "read", img, "--out", tempfile.mkdtemp()], capture_output=True, text=True).stdout
    miss = [w for w in want if w not in out]
    print(("PASS " if not miss else "FAIL ") + img + ("" if not miss else f"  missing: {miss}"))
    fails += bool(miss)
d = tempfile.mkdtemp()
subprocess.run([sys.executable, "tools/grid.py", "read", ROUTE[0], "--out", d], capture_output=True)
out = subprocess.run([sys.executable, "tools/grid.py", "route", "--json", os.path.join(d, "grid.json"), "--key", ROUTE[1]], capture_output=True, text=True).stdout
ok = ROUTE[2] in out and "EXITS" in out
print(("PASS " if ok else "FAIL ") + "route on practice G9")
fails += not ok
out = subprocess.run([sys.executable, "tools/grid.py", "message", "--seats", "STA/Y_C/ALM", "--rows", "3,1,2", "--cols", "STORM,FIRE,WAVE",
                      "--want-rows", "1,2,3", "--want-cols", "FIRE,WAVE,STORM", "--coords",
                      "1:FIRE 1:WAVE 1:STORM 2:FIRE 2:WAVE 2:STORM 3:FIRE 3:WAVE 3:STORM"], capture_output=True, text=True).stdout
ok = "'STAY CALM'" in out
print(("PASS " if ok else "FAIL ") + "message on practice G8")
fails += not ok
sys.exit(1 if fails else 0)
