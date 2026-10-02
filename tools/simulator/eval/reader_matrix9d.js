// Offline matrix for grid.py on variants/game9d.html (fragment cards with near-miss decoys, key card image).
//   node tools/simulator/eval/reader_matrix9d.js   (from the repo root, sim server on :8777)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const CONFIGS = [];
let s = 1;
for (const set of ['arcs', 'letters', 'runes']) for (const [r, c] of [[7, 5], [6, 6], [9, 7]]) CONFIGS.push(`set=${set}&rows=${r}&cols=${c}&lit=${s % 2}&seed=${700 + s++}`);
CONFIGS.push('set=arcs&rows=7&cols=5&nearmiss=0.5&lit=1&seed=790');
(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'r9d-'));
  let pass = 0;
  for (const q of CONFIGS) {
    const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9d.html?${q}&truth=1`); await p.waitForTimeout(3600);
    const T = await p.evaluate(() => window.__truth);
    const img = path.join(out, q.replace(/[&=]/g, '_') + '.png'); await p.screenshot({ path: img }); await p.close();
    const dir = img.replace('.png', '_grid'); let read = '';
    try { read = execFileSync('python3', ['tools/grid.py', 'read', img, '--out', dir]).toString(); } catch (e) { read = String(e.stdout || ''); }
    const probs = []; let G = []; try { G = JSON.parse(fs.readFileSync(path.join(dir, 'grid.json'), 'utf8')); } catch {}
    const gi = G.findIndex(g => g.cells && g.rows === T.rows && g.cols === T.cols);
    if (gi < 0) probs.push(`grid ${T.rows}x${T.cols} not found (${(read.match(/GRID 1: [^\n]*/) || ['none'])[0]})`);
    else {
      const J = G[gi], byCls = {};
      for (let r = 0; r < T.rows; r++) for (let c = 0; c < T.cols; c++) { const g = T.grid[r].split(' ')[c], cls = J.cells[r][c].class || J.cells[r][c].text; (byCls[cls] ||= {})[g] = (byCls[cls][g] || 0) + 1; }
      let wrong = 0; for (const k in byCls) { const v = Object.values(byCls[k]); wrong += v.reduce((a, b) => a + b, 0) - Math.max(...v); }
      if (wrong) probs.push(`${wrong} tiles in mixed classes`);
      const st = J.cells.flatMap((row, r) => row.map((c, k) => c.mark === 'start?' ? [r + 1, k + 1] : null)).filter(Boolean);
      if (!(st.length === 1 && st[0][0] === T.start[0] && st[0][1] === T.start[1])) probs.push(`start ${JSON.stringify(st)} want ${T.start}`);
      if (!wrong) {
        const key = Object.entries(byCls).map(([cls, m]) => { const g = Object.keys(m)[0]; return T.moves[g] ? `${cls}=${T.moves[g]}` : null; }).filter(Boolean).join(',');
        let r = ''; try { r = execFileSync('python3', ['tools/grid.py', 'route', '--json', path.join(dir, 'grid.json'), '--grid', String(gi + 1), '--key', key, '--start', T.start.join(',')]).toString(); } catch (e) { r = String(e.stdout || ''); }
        if (!r.includes(T.route.map(([a, c]) => `(${a},${c})`).join(' → '))) probs.push('route differs');
      }
    }
    if (!probs.length) pass++;
    console.log(`${probs.length ? 'FAIL' : 'PASS'} ${q.padEnd(46)} ${probs.join('; ')}`);
  }
  console.log(`\n${pass}/${CONFIGS.length} fragment boards read and routed`);
  await b.close();
})();
