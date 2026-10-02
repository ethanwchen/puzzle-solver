# eval_costs.py SESSION_DIR BG EXP OUT -> runs motion.py on each clip with its crop, writes "k EXPECT_COSTS ..." lines
import re, subprocess, sys
d, bg, exp, out = sys.argv[1:5]
log = open(d + '/log.md').read()
crops = {}
for m in re.finditer(r'CLIP (clip\d+)\.mp4[^\n]*\n[^\n]*video px (\d+),(\d+),(\d+),(\d+)', log):
    crops.setdefault(m.group(1), m.groups()[1:])
with open(out, 'w') as f:
    for clip, c in sorted(crops.items(), key=lambda kv: int(kv[0][4:])):
        r = subprocess.run(['python3', 'tools/motion.py', f'{d}/{clip}.mp4', '--crop', *c, '--regions', '1', '--unit', '220',
                            '--expect', exp + ',' + bg, '--out', f'/tmp/ev_{clip}'], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if 'EXPECT_COSTS' in line:
                f.write(f'{clip[4:]} {line.strip()}\n')
