// Offline matrix for G9 rule permutations (variants/game9b.html): move rules × exits × start modes × entry.
// No agent: renders each config with ?truth=1, then checks (1) the SOLVER on the true grid (grid.py route with
// the right flags) and (2) the READER (grid.py read → symbol classes → route with the true key).
//   node tools/simulator/eval/reader_matrix9b.js   (from the repo root, sim server on :8777)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const CONFIGS = [];
let s = 1;
for (const move of ['dir', 'diag', 'jump', 'turn', 'pipe'])
  for (const exit of ['top', 'right'])
    for (const starts of [1, 3]) CONFIGS.push(`move=${move}&exit=${exit}&starts=${starts}&entry=${starts === 3 ? 'word' : 'click'}&key=${move === 'pipe' ? 'none' : starts === 1 ? 'legend' : 'panel'}&n=${5 + (s % 3)}&seed=${900 + s++}`);
CONFIGS.push('move=dir&exit=left&starts=1&entry=click&key=legend&rows=5&cols=8&seed=951');
CONFIGS.push('move=turn&exit=bottom&starts=1&entry=click&key=legend&n=6&seed=952');
CONFIGS.push('move=pipe&exit=top&starts=1&entry=click&lit=1&n=7&seed=953');
CONFIGS.push('move=jump&exit=top&starts=3&entry=word&key=legend&n=8&seed=954');

const run = args => { try { return execFileSync('python3', ['tools/grid.py', ...args]).toString(); } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); } };
const flags = T => [...(T.move === 'turn' ? ['--relative', '--heading', T.heading] : []), ...(T.move === 'pipe' ? ['--pipes'] : []), '--exit', T.exit];
const keyOf = T => Object.entries(T.mapping).map(([k, v]) => `${k}=${v}`).join(',');
const want = T => T.route.map(([a, c]) => `(${a},${c})`).join(' → ');

(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'reader9b-'));
  let solverOK = 0, readerOK = 0;
  for (const q of CONFIGS) {
    const p = await b.newPage({ viewport: { width: 1280, height: 860 } });
    await p.goto(`http://127.0.0.1:8777/variants/game9b.html?${q}&truth=1`); await p.waitForTimeout(3300);
    const T = await p.evaluate(() => window.__truth);
    const img = path.join(out, q.replace(/[&=]/g, '_') + '.png');
    await p.screenshot({ path: img }); await p.close();
    const probs = [];
    // (1) solver on the true grid
    const cells = T.grid.map(r => [...r].join(' ')).join('/');
    const st = T.starts.map(x => x.join(',')).join(';');
    const sol = run(['route', '--cells', cells, ...(T.move === 'pipe' ? [] : ['--key', keyOf(T)]), '--start', st, ...flags(T), '--letters', T.letters.join('/')]);
    const solved = sol.includes(want(T)) && (T.starts.length === 1 || /^1 start\(s\) escape/m.test(sol)) && (!T.word || sol.includes('SPELLS: ' + T.word));
    if (solved) solverOK++; else probs.push('SOLVER: ' + sol.split('\n').filter(l => /ROUTE|LOOP|EXIT|escape|SPELLS|not/.test(l)).slice(0, 3).join(' | '));
    // (2) reader
    const dir = img.replace('.png', '_grid');
    run(['read', img, '--out', dir]);
    let G = [], gi = -1;
    try { G = JSON.parse(fs.readFileSync(path.join(dir, 'grid.json'), 'utf8')); gi = G.findIndex(g => g.cells && !g.text && g.rows === T.rows && g.cols === T.cols); } catch {}
    const ROMAN = { 'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV', 'Ⅴ': 'V', 'Ⅵ': 'VI', 'Ⅶ': 'VII', 'Ⅷ': 'VIII' };
    const tg = gi < 0 ? G.findIndex(g => g.cells && g.text && g.rows === T.rows && g.cols === T.cols) : -1;
    if (gi < 0 && tg >= 0) { // letter-like symbols (Roman numerals) come back as a TEXT grid: route on the OCR text
      const key = Object.entries(T.mapping).map(([k, v]) => `${ROMAN[k] || k}=${v}`).join(',');
      const r = run(['route', '--json', path.join(dir, 'grid.json'), '--grid', String(tg + 1), '--key', key, ...flags(T)]);
      if (r.includes(want(T)) && (T.starts.length === 1 || /^1 start\(s\) escape/m.test(r))) readerOK++;
      else probs.push('READER (text grid) route: ' + r.split('\n').filter(l => /ROUTE|LOOP|EXIT|escape|not/.test(l)).slice(0, 2).join(' | '));
    }
    else if (gi < 0) probs.push(`READER: ${T.rows}x${T.cols} grid not found`);
    else {
      const J = G[gi], byCls = {};
      for (let r = 0; r < T.rows; r++) for (let c = 0; c < T.cols; c++) { const sym = [...T.grid[r]][c], cls = J.cells[r][c].class; (byCls[cls] ||= {})[sym] = (byCls[cls][sym] || 0) + 1; }
      let wrong = 0; for (const cls in byCls) { const v = Object.values(byCls[cls]); wrong += v.reduce((a, b) => a + b, 0) - Math.max(...v); }
      if (wrong) probs.push(`READER: ${wrong} tiles in mixed classes`);
      else {
        const PIPES = { '┃': 'UD', '━': 'LR', '┏': 'RD', '┓': 'LD', '┗': 'UR', '┛': 'UL', '╋': 'UDLR' };
        const key = Object.entries(byCls).map(([cls, m]) => { const sym = Object.keys(m)[0]; return `${cls}=${T.move === 'pipe' ? PIPES[sym] : T.mapping[sym]}`; }).join(',');
        const r = run(['route', '--json', path.join(dir, 'grid.json'), '--grid', String(gi + 1), '--key', key, ...flags(T)]);
        if (r.includes(want(T)) && (T.starts.length === 1 || /^1 start\(s\) escape/m.test(r))) readerOK++;
        else probs.push('READER route: ' + r.split('\n').filter(l => /ROUTE|LOOP|EXIT|escape|no --start|not/.test(l)).slice(0, 2).join(' | '));
      }
    }
    console.log(`${probs.length ? 'FAIL' : 'PASS'} ${q.padEnd(80)} ${probs.join('; ')}`);
  }
  console.log(`\nsolver ${solverOK}/${CONFIGS.length} · reader+route ${readerOK}/${CONFIGS.length}`);
  await b.close();
})();
