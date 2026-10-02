// Offline matrix for tools/maze.py on variants/game9z.html (oversized boards in a pan/zoom viewport).
// Two reads per board: as it OPENS (cropped — the solver must not answer from this) and after HOME (fitted).
// The fitted read is the pass/fail criterion; the cropped read is reported so we know how the reader behaves
// when a solver forgets to fit first.
//   node tools/simulator/eval/maze_matrix9z.js [filter]   (from the repo root, sim server on :8777)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const CONFIGS = [];
let s = 1;
for (const style of ['walls', 'tiles', 'cards'])
  for (const [r, c] of [[16, 16], [14, 14], [20, 12], [12, 20]])
    CONFIGS.push(`style=${style}&rows=${r}&cols=${c}&exits=${1 + (s % 3)}&lit=${s % 2}&open=${['start', 'corner', 'fit'][s % 3]}&seed=${900 + s++}`);
for (const style of ['walls', 'tiles', 'cards']) {
  CONFIGS.push(`style=${style}&rows=18&cols=18&exits=2&lit=1&loops=2&open=start&tile=64&seed=${950 + s++}`);
  CONFIGS.push(`style=${style}&rows=16&cols=16&exits=3&lit=1&start=any&open=corner&zoom=1.6&seed=${950 + s++}`);
}
const filt = process.argv[2] || '';
const run = (img, extra = []) => { try { return execFileSync('python3', ['tools/maze.py', img, ...extra]).toString(); } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); } };
(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'maze9z-'));
  let pass = 0, n = 0, croppedOk = 0;
  for (const q of CONFIGS.filter(x => x.includes(filt))) {
    n++;
    const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9z.html?${q}&truth=1`); await p.waitForTimeout(3600);
    const T = await p.evaluate(() => window.__truth);
    const base = path.join(out, q.replace(/[&=]/g, '_'));
    await p.screenshot({ path: base + '_open.png' });
    await p.keyboard.press('Home'); await p.waitForTimeout(500);          // the solver fits the board
    await p.screenshot({ path: base + '_fit.png' });
    await p.close();

    const r = run(base + '_fit.png');
    const probs = [];
    const m = r.match(/MAZE (\d+)x(\d+)/);
    if (!m || +m[1] !== T.rows || +m[2] !== T.cols) probs.push(`size ${m ? m[1] + 'x' + m[2] : '?'} want ${T.rows}x${T.cols}`);
    const st = r.match(/start r(\d+)c(\d+)/);
    if (!st || +st[1] !== T.start[0] || +st[2] !== T.start[1]) probs.push(`start ${st ? st[1] + ',' + st[2] : 'not found'} want ${T.start}`);
    const want = T.route.map(([a, c]) => `(${a},${c})`).join(' → ');
    const route = (r.match(/^ROUTE[^\n]*/m) || [''])[0];
    if (!route.includes(want)) probs.push('route ' + (route ? 'differs' : (r.match(/NO WAY[^\n]*/) || ['missing'])[0]));
    if (/WARNING: \d+ reachable/.test(r)) probs.push('extra reachable exits');
    if (T.lit.length && !/LIT tiles: \d+; on the route: 0/.test(r)) probs.push('lit ' + ((r.match(/LIT tiles[^\n]*/) || ['not reported'])[0]));
    if (!probs.length) pass++;

    // informational: what the reader does with the cropped opening view
    const ro = run(base + '_open.png');
    const mo = ro.match(/MAZE (\d+)x(\d+)/);
    const cropMatches = mo && +mo[1] === T.rows && +mo[2] === T.cols;
    if (cropMatches) croppedOk++;
    const cropNote = T.open_mode === 'fit' ? 'opened fitted'
      : cropMatches ? 'CROPPED READ LOOKS RIGHT (risk: silently wrong)' : `cropped read ${mo ? mo[1] + 'x' + mo[2] : 'refused'}`;
    console.log(`${probs.length ? 'FAIL' : 'PASS'} ${q.padEnd(66)} ${probs.join('; ')}${probs.length ? '  [' + base + '_fit.png]' : ''}  · ${cropNote}`);
  }
  console.log(`\n${pass}/${n} oversized boards read and solved after HOME`);
  console.log(`${croppedOk}/${n} also "read" from the cropped opening view — those are the dangerous ones`);
  await b.close();
})();
