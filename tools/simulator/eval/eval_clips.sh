#!/bin/zsh
# Replays a finished harness run's recorded clips through motion.py + the batch assignment used by the sidekick,
# and prints the answer the run scored with. Tune motion.py / assignWords offline, at no agent cost.
# eval_clips.sh NAME (run from the repo root) -> offline batch assignment on that run's clips, next to the answer that scored 100%
n=$1; D=$(grep -m1 SESSION ${TMPDIR:-/tmp}/sidekick-harness-$n/app.log | cut -d' ' -f2)
BG=$(node -e "const s=require('fs').readFileSync('tools/sidekick/main.js','utf8'); const m=s.match(/const BG_WORDS = (\[[\s\S]*?\]);/); console.log(eval(m[1]).join(','))")
EXP=$(grep -o -- "--expect [A-Z,]*" $D/log.md | head -1 | awk '{print $2}')
[ -s /tmp/allcosts_$n.txt ] && [ -n "$CACHED" ] || python3 tools/simulator/eval/eval_costs.py $D $BG $EXP /tmp/allcosts_$n.txt
N=$n EXP=$EXP node -e '
const src = require("fs").readFileSync("tools/sidekick/main.js","utf8");
eval(src.slice(src.indexOf("const BG_WORDS"), src.indexOf("// ---------- recording:")));
const lines = require("fs").readFileSync("/tmp/allcosts_" + process.env.N + ".txt","utf8").trim().split("\n");
const targets = new Set(process.env.EXP.split(","));
let best = null;
for (const pol of ["dark","bright"]) {
  const all = {}; for (const l of lines) { const m = l.match(new RegExp("^(\\d+) +EXPECT_COSTS " + pol + ": (.*)")); if (m) all[m[1]] = Object.fromEntries(m[2].split(",").map(kv => { const [w,v] = kv.split("="); return [w, Number(v)]; })); }
  const idx = Object.keys(all);
  const rows = idx.map(i => Object.fromEntries(Object.entries(all[i]).filter(([w]) => targets.has(w))));
  const skip = idx.map(i => Math.min(...Object.entries(all[i]).filter(([w]) => !targets.has(w) && w.length >= 4).map(([,v]) => v + Number(process.env.MARGIN || 0.08)), 9));
  const a = assignWords(rows, 0.32, skip);
  if (a && (!best || a.total < best.total)) best = { ...a, pol, idx };
}
console.log(process.env.N, "targets:", targets.size, best.pol, best.idx.map((k,j) => "clip"+k+":"+(best.pick[j] ? best.pick[j].word : "—")).join(" "));'
grep -o 'answer so far: "[^"]*" (deep)' ${TMPDIR:-/tmp}/sidekick-harness-$n/driver.log | tail -1 | cut -c1-120
