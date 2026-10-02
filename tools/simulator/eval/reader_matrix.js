// Offline robustness matrix for tools/grid.py on the G9 variant: many sizes / shapes / symbol sets / lit traps.
// No agent involved: renders each config headlessly with ?truth=1, runs `grid.py read`, and checks the reading and
// the solved route against the page's hidden truth.   node tools/simulator/eval/reader_matrix.js   (from the repo root)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const CONFIGS = [];
for (const n of [4, 5, 6, 7, 8, 9, 10]) for (const seed of [1, 2]) CONFIGS.push(`n=${n}&seed=${seed + n * 10}`);
for (const [r, c] of [[5, 8], [8, 5], [6, 9], [4, 7]]) CONFIGS.push(`rows=${r}&cols=${c}&seed=${r * 100 + c}`);
for (const seed of [3, 4, 5, 6]) CONFIGS.push(`n=6&lit=1&seed=${seed}`);
for (const seed of [7, 8]) CONFIGS.push(`n=8&lit=1&seed=${seed}`);

(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'reader-'));
  let pass = 0;
  for (const q of CONFIGS) {
    const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9.html?${q}&truth=1`); await p.waitForTimeout(3300);
    const T = await p.evaluate(() => window.__truth);
    const img = path.join(out, q.replace(/[&=]/g, '_') + '.png');
    await p.screenshot({ path: img }); await p.close();
    const dir = img.replace('.png', '_grid');
    let read = '';
    try { read = execFileSync('python3', ['tools/grid.py', 'read', img, '--out', dir]).toString(); } catch (e) { read = String(e.stdout || ''); }
    const problems = [];
    let J = null;
    try { J = JSON.parse(fs.readFileSync(path.join(dir, 'grid.json'), 'utf8')).find(g => g.cells && !g.text && g.rows === T.rows && g.cols === T.cols); } catch {}
    if (!J) problems.push(`grid ${T.rows}x${T.cols} not found (read: ${(read.match(/GRID 1: [^\n]*/) || ['none'])[0]})`);
    else {
      // class ↔ symbol must be a clean 1:1 mapping
      const bySym = {}, byCls = {}; let wrong = 0;
      for (let r = 0; r < T.rows; r++) for (let c = 0; c < T.cols; c++) {
        const sym = [...T.grid[r]][c], cls = J.cells[r][c].class;
        (bySym[sym] ||= {})[cls] = ((bySym[sym] || {})[cls] || 0) + 1;
        (byCls[cls] ||= {})[sym] = ((byCls[cls] || {})[sym] || 0) + 1;
      }
      for (const cls in byCls) { const counts = Object.values(byCls[cls]); wrong += counts.reduce((a, b) => a + b, 0) - Math.max(...counts); }
      const split = Object.values(bySym).filter(m => Object.keys(m).length > 1).length;
      if (wrong) problems.push(`${wrong} tiles in a mixed class`);
      if (split) problems.push(`${split} symbols split over several classes`);
      // the start must be THE lone marked tile; lit-trap tiles must be reported as a separate lit group
      const st = J.cells.flatMap((row, r) => row.map((c, k) => c.mark === 'start?' ? [r + 1, k + 1] : null)).filter(Boolean);
      if (!(st.length === 1 && st[0][0] === T.start[0] && st[0][1] === T.start[1])) problems.push(`start r${T.start[0]}c${T.start[1]}: lone marked tile(s) = ${st.map(x => 'r' + x[0] + 'c' + x[1]).join(',') || 'none'}`);
      // route: give the TRUE key (class → direction via majority symbol) and compare with the true route
      if (!wrong) {
        const key = Object.entries(byCls).map(([cls, m]) => `${cls}=${T.mapping[Object.keys(m)[0]]}`).join(',');
        let r = '';
        try { r = execFileSync('python3', ['tools/grid.py', 'route', '--json', path.join(dir, 'grid.json'), '--grid', String(JSON.parse(fs.readFileSync(path.join(dir, 'grid.json'), 'utf8')).findIndex(g => g.cells && g.rows === T.rows && g.cols === T.cols && !g.text) + 1), '--key', key, '--start', T.start.join(',')]).toString(); } catch (e) { r = String(e.stdout || ''); }
        const want = T.route.map(([a, c]) => `(${a},${c})`).join(' → ');
        if (!r.includes(want)) problems.push('route differs');
      }
    }
    if (!problems.length) pass++;
    console.log(`${problems.length ? 'FAIL' : 'PASS'} ${q.padEnd(24)} ${problems.join('; ')}`);
  }
  console.log(`\n${pass}/${CONFIGS.length} configs read and routed correctly`);
  await b.close();
})();
