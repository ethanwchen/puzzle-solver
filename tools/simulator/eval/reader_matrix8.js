// Offline robustness matrix for tools/grid.py on the G8 variant (keyed coordinate cipher), across grid sizes,
// notations and key types. Checks the board (row/column MARKERS found with the right counts) and the open
// transmission (one answer box per coordinate).   node tools/simulator/eval/reader_matrix8.js   (from the repo root)
const { chromium } = require('../node_modules/playwright-core');
const { execFileSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const CONFIGS = [];
for (const [rn, cn] of [[3, 3], [3, 4], [4, 4], [4, 5], [5, 5], [5, 4]])
  for (const [rows, notation] of [['explicit', 'cards'], ['number', 'words'], ['loss', 'cards']])
    if (!(rows === 'loss' && rn > 5)) CONFIGS.push(`rn=${rn}&cn=${cn}&rows=${rows}&cols=explicit&notation=${notation}&entry=boxes&move=swap&seed=${rn * 10 + cn}`);
CONFIGS.push('rn=4&cn=4&rows=number&cols=games&notation=words&entry=boxes&move=insert&seed=44');
CONFIGS.push('rn=3&cn=4&rows=loss&cols=games&notation=cards&entry=boxes&move=carry&seed=34');

(async () => {
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const sh = fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const b = await chromium.launch({ executablePath: path.join(cache, sh, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell') });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'reader8-'));
  let pass = 0;
  const read = img => { try { return execFileSync('python3', ['tools/grid.py', 'read', img, '--out', img.replace('.png', '_grid')]).toString(); } catch (e) { return String(e.stdout || ''); } };
  for (const q of CONFIGS) {
    const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
    await p.goto(`http://127.0.0.1:8777/variants/game8b.html?${q}&truth=1`); await p.waitForTimeout(3300);
    const T = await p.evaluate(() => window.__truth);
    const base = path.join(out, q.replace(/[&=]/g, '_').slice(0, 60));
    await p.screenshot({ path: base + '_board.png' });
    await p.click('#open'); await p.waitForTimeout(400);
    await p.screenshot({ path: base + '_tx.png' });
    await p.close();
    const problems = [];
    const board = read(base + '_board.png');
    // labels: either a HEADERED GRID (labels in the grid's first row/column) or separate MARKERS lines
    const hr = (board.match(/row labels \(current order, top→bottom\): ([^\n]*)/) || [])[1];
    const hc = (board.match(/column labels \(current order\): ([^\n]*)/) || [])[1];
    const cols = [...board.matchAll(/MARKERS: row of (\d+) tiles/g)].map(m => +m[1]);
    const rows = [...board.matchAll(/MARKERS: column of (\d+) tiles/g)].map(m => +m[1]);
    const rowN = hr ? hr.split(', ').length : null, colN = hc ? hc.split(', ').length : null;
    if (rowN !== T.rows && !rows.includes(T.rows)) problems.push(`row labels: want ${T.rows}, got ${rowN ?? (rows.join('/') || 'none')}`);
    if (colN !== T.cols && !cols.includes(T.cols)) problems.push(`column labels: want ${T.cols}, got ${colN ?? (cols.join('/') || 'none')}`);
    if (hr && !hr.split(', ').every((l, i) => l.includes(T.rowLabels[i]))) problems.push(`row label text ${hr} ≠ ${T.rowLabels.join(', ')}`);
    const tx = read(base + '_tx.png');
    // answer boxes: empty same-size tiles, possibly wrapped over several rows → count filled cells of empty grids
    let boxesFound = 0;
    try {
      const J = JSON.parse(fs.readFileSync(base + '_tx_grid/grid.json', 'utf8'));
      for (const g of J) if (g.cells && !g.text) boxesFound = Math.max(boxesFound, g.cells.flat().filter(c => c.empty).length);
    } catch {}
    if (boxesFound < T.coords) problems.push(`answer boxes: want ${T.coords}, found ${boxesFound}`);
    if (!problems.length) pass++;
    console.log(`${problems.length ? 'FAIL' : 'PASS'} ${T.rows}x${T.cols} ${q.split('&').slice(2, 4).join(' ').padEnd(28)} ${problems.join('; ')}`);
  }
  console.log(`\n${pass}/${CONFIGS.length} G8 configs: markers and answer boxes found`);
  await b.close();
})();
