// Offline matrix for tools/maze.py on variants/game9m.html (maze tunnels: walls / tiles / cards × sizes × lit × exits × loops).
// No agent. Checks the map read (open sides per cell) and the route against the page's hidden truth.
//   node tools/simulator/eval/maze_matrix.js [filter]   (from the repo root, sim server on :8777)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const CONFIGS = [];
let s = 1;
for (const style of ['walls', 'tiles', 'cards'])
  for (const [r, c] of [[7, 5], [5, 5], [8, 8], [10, 6], [6, 10]])
    CONFIGS.push(`style=${style}&rows=${r}&cols=${c}&exits=${1 + (s % 3)}&lit=${s % 2}&seed=${300 + s++}`);
for (const style of ['walls', 'tiles', 'cards']) {
  CONFIGS.push(`style=${style}&rows=7&cols=5&exits=3&lit=1&loops=2&seed=${400 + s++}`);
  CONFIGS.push(`style=${style}&rows=7&cols=7&exits=2&lit=1&start=any&seed=${400 + s++}`);
  CONFIGS.push(`style=${style}&rows=12&cols=12&exits=4&lit=1&seed=${400 + s++}`);
}
const filt = process.argv[2] || '';
(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'maze-'));
  let pass = 0, n = 0;
  for (const q of CONFIGS.filter(x => x.includes(filt))) {
    n++;
    const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9m.html?${q}&truth=1`); await p.waitForTimeout(3600);
    const T = await p.evaluate(() => window.__truth);
    const img = path.join(out, q.replace(/[&=]/g, '_') + '.png');
    await p.screenshot({ path: img }); await p.close();
    let r = '';
    try { r = execFileSync('python3', ['tools/maze.py', img]).toString(); } catch (e) { r = String(e.stdout || '') + String(e.stderr || ''); }
    const probs = [];
    const m = r.match(/MAZE (\d+)x(\d+)/);
    if (!m || +m[1] !== T.rows || +m[2] !== T.cols) probs.push(`size ${m ? m[1] + 'x' + m[2] : '?'} want ${T.rows}x${T.cols}`);
    const st = r.match(/start r(\d+)c(\d+)/);
    if (!st || +st[1] !== T.start[0] || +st[2] !== T.start[1]) probs.push(`start ${st ? st[1] + ',' + st[2] : (r.match(/no glowing[^\n]*/) || ['?'])[0]} want ${T.start}`);
    const want = T.route.map(([a, c]) => `(${a},${c})`).join(' → ');
    const route = (r.match(/^ROUTE[^\n]*/m) || [''])[0];
    if (!route.includes(want)) probs.push('route ' + (route ? 'differs' : (r.match(/NO WAY[^\n]*/) || ['missing'])[0]));
    if (/WARNING: \d+ reachable/.test(r)) probs.push('extra reachable exits');
    if (T.lit.length && !/LIT tiles: \d+; on the route: 0/.test(r)) probs.push('lit ' + ((r.match(/LIT tiles[^\n]*/) || ['not reported'])[0]));
    if (!probs.length) pass++;
    console.log(`${probs.length ? 'FAIL' : 'PASS'} ${q.padEnd(58)} ${probs.join('; ')}${probs.length ? '  [' + img + ']' : ''}`);
  }
  console.log(`\n${pass}/${n} mazes read and solved`);
  await b.close();
})();
