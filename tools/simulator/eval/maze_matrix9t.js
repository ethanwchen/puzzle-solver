// Offline matrix for tools/maze.py on variants/game9t.html (the tunnels as a badly printed plate).
// Same mazes as game9m, so any failure here is a READER failure on the artwork, not a solving failure.
//   node tools/simulator/eval/maze_matrix9t.js [filter]   (from the repo root, sim server on :8777)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const CONFIGS = [];
let s = 1;
for (const tone of ['sepia', 'blueprint', 'xray'])
  for (const [r, c] of [[9, 7], [7, 7], [11, 8]])
    CONFIGS.push(`tone=${tone}&rows=${r}&cols=${c}&exits=${1 + (s % 3)}&lit=${s % 2}&seed=${600 + s++}`);
// the punishing end of the print: heavy grain, heavy bleed, strong vignette, visible press skew
for (const tone of ['sepia', 'blueprint', 'xray']) {
  CONFIGS.push(`tone=${tone}&rows=9&cols=7&grain=0.95&bleed=0.85&vignette=0.85&rot=2.2&lit=1&seed=${650 + s++}`);
  CONFIGS.push(`tone=${tone}&rows=9&cols=7&grain=0.1&bleed=0.1&vignette=0.1&rot=0&seed=${650 + s++}`);
}
const filt = process.argv[2] || '';
(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'maze9t-'));
  let pass = 0, n = 0, unaidedPass = 0, routePass = 0;
  for (const q of CONFIGS.filter(x => x.includes(filt))) {
    n++;
    const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9t.html?${q}&truth=1`); await p.waitForTimeout(3600);
    const T = await p.evaluate(() => window.__truth);
    const img = path.join(out, q.replace(/[&=]/g, '_') + '.png');
    await p.screenshot({ path: img }); await p.close();
    // Two reads. UNAIDED is what maze.py manages on its own. ASSISTED is the live-round fallback: the agent reads
    // the board's size and the glowing start off the screen itself and hands them over, so this measures only
    // whether the WALLS can be read through the print noise.
    const read = extra => { try { return execFileSync('python3', ['tools/maze.py', img, ...extra]).toString(); } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); } };
    const assist = ['--rows', String(T.rows), '--cols', String(T.cols), '--start', T.start.join(',')];
    const unaided = read([]);
    let r = read(assist);
    const probs = [];
    const m = r.match(/MAZE (\d+)x(\d+)/);
    if (!m || +m[1] !== T.rows || +m[2] !== T.cols) probs.push(`size ${m ? m[1] + 'x' + m[2] : '?'} want ${T.rows}x${T.cols}`);
    const st = r.match(/start r(\d+)c(\d+)/);
    if (!st || +st[1] !== T.start[0] || +st[2] !== T.start[1]) probs.push(`start ${st ? st[1] + ',' + st[2] : 'not found'} want ${T.start}`);
    const want = T.route.map(([a, c]) => `(${a},${c})`).join(' → ');
    const route = (r.match(/^ROUTE[^\n]*/m) || [''])[0];
    if (!route.includes(want)) probs.push('route ' + (route ? 'differs' : (r.match(/NO WAY[^\n]*/) || ['missing'])[0]));
    if (/WARNING: \d+ reachable/.test(r)) probs.push('extra reachable exits');
    const routeOk = !probs.length;        // the route IS the answer; lit is only advisory
    if (routeOk) routePass++;
    if (T.lit.length && !/LIT tiles: \d+; on the route: 0/.test(r)) probs.push('lit ' + ((r.match(/LIT tiles[^\n]*/) || ['not reported'])[0]));
    if (!probs.length) pass++;
    const um = unaided.match(/MAZE (\d+)x(\d+)/), ust = unaided.match(/start r(\d+)c(\d+)/);
    const uok = um && +um[1] === T.rows && +um[2] === T.cols && ust && +ust[1] === T.start[0] && +ust[2] === T.start[1]
      && unaided.includes(T.route.map(([a, c]) => `(${a},${c})`).join(' → '));
    if (uok) unaidedPass++;
    console.log(`${probs.length ? 'FAIL' : 'PASS'} ${q.padEnd(72)} ${probs.join('; ')}${probs.length ? '  [' + img + ']' : ''}  · unaided ${uok ? 'ok' : (um ? um[1] + 'x' + um[2] : 'refused')}`);
  }
  console.log(`\n${routePass}/${n} plates ROUTED correctly when given rows/cols/start (the live-round fallback)`);
  console.log(`${pass}/${n} of those also reported the lit decoy correctly`);
  console.log(`${unaidedPass}/${n} plates solved with no help at all`);
  await b.close();
})();
