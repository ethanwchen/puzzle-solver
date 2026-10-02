// Sidekick: an always-on-top overlay that solves puzzles with you.
//
//   cd tools/sidekick && npm start        (or double-click sidekick.command in the repo root)
//
// Each chat turn runs headless Claude Code (`claude -p`) in the repo root. That gives it CLAUDE.md and every
// deterministic helper in tools/, plus a system prompt built from prompt.md, the learned PATTERNS in solve-fast.js,
// research/ledger.md and book/digest/OVERVIEW.md. Turns resume the same Claude session, so it remembers the puzzle.
// Screens are captured only when you ask (hotkey/button) or, with Watch on, when your screen changes.
// Nothing here touches the contest site: you read the hint and submit yourself.
const { app, BrowserWindow, globalShortcut, ipcMain, screen, desktopCapturer, nativeImage, Tray, Menu, shell, clipboard } = require('electron');
const { spawn, execFile, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const HERE = __dirname;
// Test harness: SIDEKICK_SOURCE=<dir> makes <dir>/latest.png stand in for the screen (a driver script keeps it fresh).
const SOURCE = process.env.SIDEKICK_SOURCE || null;
const ROUNDS = { R3: '249-288', R4: '289-449', any: '1-449' };
const TOOLS = ['Read', 'Glob', 'Grep', 'Bash(python3:*)', 'Bash(ls:*)', 'Bash(cat:*)', 'Bash(head:*)', 'Bash(grep:*)', 'Bash(wc:*)'];
const CORPUS_CMDS = new Set(['search', 'count', 'page', 'line', 'word', 'decode', 'decode-pw', 'chapter', 'toc', 'acrostic',
  'initials', 'anagram', 'grille', 'layout', 'probe', 'unmask', 'numbers', 'caps', 'notes', 'who']);
const ONE_ARG = new Set(['probe', 'decode', 'decode-pw', 'who', 'layout']); // rest of the line is a single argument

let win, tray;
let claudeBin = 'claude';
const S = { // one "puzzle" session
  id: null, dir: null, n: 0, sysFile: null, started: Date.now(),
  pendingNotes: [], lastScreen: null, shots: {}, clips: 0, pre: {}, catchup: [], turnSeq: 0,
  lanes: { quick: { id: null, proc: null }, deep: { id: null, proc: null } },
};
const prefs = { level: 'hint', round: 'R3', model: 'opus', speed: 'balanced', follow: false };

// ---------- environment ----------
function loginPath() {
  // Apps launched from Finder get a bare PATH; borrow the login shell's so `claude`, python3 and node resolve.
  try {
    const p = execFileSync('/bin/zsh', ['-lc', 'echo -n $PATH'], { timeout: 5000 }).toString().trim();
    if (p) process.env.PATH = p + ':' + (process.env.PATH || '');
  } catch {}
  try { claudeBin = execFileSync('/bin/zsh', ['-lc', 'command -v claude'], { timeout: 5000 }).toString().trim() || 'claude'; } catch {}
}

function loadPatterns() {
  try {
    const src = fs.readFileSync(path.join(ROOT, '.claude/workflows/solve-fast.js'), 'utf8');
    const start = src.indexOf('const PATTERNS = [');
    const end = src.indexOf('\n]\n', start) + 2;
    return new Function(src.slice(start, end) + '\nreturn PATTERNS.map(p => p.text);')();
  } catch { return []; }
}

function readOr(rel, fallback = '') {
  try { return fs.readFileSync(path.join(ROOT, rel), 'utf8'); } catch { return fallback; }
}

function buildSystemPrompt(file) {
  const parts = [
    fs.readFileSync(path.join(HERE, 'prompt.md'), 'utf8'),
    '## Learned priors (from past rounds and training; current policy of solve-fast.js)\n' + loadPatterns().map(p => '- ' + p).join('\n'),
    '## Puzzle keys (book/digest/FACTS.md)\n' + readOr('book/digest/FACTS.md'),
    '## Contest ledger (research/ledger.md)\n' + readOr('research/ledger.md'),
    '## Book study guide (book/digest/OVERVIEW.md; open book/ files and use tools/ for exact text and citations)\n' + readOr('book/digest/OVERVIEW.md'),
  ];
  fs.writeFileSync(file, parts.join('\n\n'));
}

// ---------- session ----------
function stamp() {
  const d = new Date(), z = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`;
}

function ensureSession() {
  if (S.dir) return S.dir;
  S.dir = path.join(ROOT, 'challenges', `sidekick-${stamp()}`);
  fs.mkdirSync(S.dir, { recursive: true });
  console.log('SESSION', S.dir);
  if (!S.sysFile) warmUp();
  return S.dir;
}

// Warm-up: build the system prompt and open both lane sessions right away (a one-word turn each). The big system
// prompt gets cached and the sessions exist, so the first real look skips the cold start.
function warmUp() {
  fs.mkdirSync(path.join(HERE, '.cache'), { recursive: true });
  for (const f of fs.readdirSync(path.join(HERE, '.cache'))) { // stale prompts from earlier launches
    const fp = path.join(HERE, '.cache', f);
    if (f !== `system-${process.pid}.md` && Date.now() - fs.statSync(fp).mtimeMs > 3600e3) fs.rmSync(fp, { force: true });
  }
  S.sysFile = path.join(HERE, '.cache', `system-${process.pid}.md`);
  buildSystemPrompt(S.sysFile);
  S.warm = {};
  for (const lane of Object.keys(LANES)) {
    const L = S.lanes[lane];
    const args = ['-p', 'Warm-up only: the session is starting. Reply with the single word: ready', '--output-format', 'json',
      '--append-system-prompt-file', S.sysFile, '--strict-mcp-config', '--model', LANES[lane].model()];
    const effort = LANES[lane].effort(false); if (effort) args.push('--effort', effort);
    S.warm[lane] = new Promise(res => execFile(claudeBin, args, { cwd: ROOT, timeout: 90000, maxBuffer: 4 << 20 }, (e, out) => {
      try { const j = JSON.parse(out || '{}'); if (j.session_id && !L.id) L.id = j.session_id; } catch {}
      res();
    }));
  }
}

function newSession() {
  stopAll();
  Object.assign(S, { lastSolver: null, dir: null, n: 0, sysFile: null, started: Date.now(), pendingNotes: [], lastScreen: null, shots: {}, clips: 0, pre: {}, catchup: [], deepNote: '',
    stopping: false, capturing: false, lanes: { quick: { id: null, proc: null }, deep: { id: null, proc: null } } });
  clearCallouts(); clearStepMarks(); S.steps = null;
  watch.base = null; watch.prev = null; watch.lastOcr = null;
  warmUp();
  send('session', { started: S.started });
  send('steps', null);
}

function log(line) {
  if (S.dir) fs.appendFileSync(path.join(S.dir, 'log.md'), line + '\n\n');
}

function send(ch, data) { if (win && !win.isDestroyed()) win.webContents.send(ch, data); }

// ---------- screen capture ----------
const sleep = ms => new Promise(r => setTimeout(r, ms));
const run = (cmd, args) => new Promise(res => execFile(cmd, args, { timeout: 120000 }, (e, out, err) => res({ e, out, err })));

function targetDisplay() {
  // The display under the cursor, unless the cursor is on the overlay (a button click): then the overlay's display.
  const pt = screen.getCursorScreenPoint();
  const b = win.getBounds();
  const onOverlay = pt.x >= b.x && pt.x <= b.x + b.width && pt.y >= b.y && pt.y <= b.y + b.height;
  return onOverlay ? screen.getDisplayMatching(b) : screen.getDisplayNearestPoint(pt);
}

async function capture(mode, { keepPins = true } = {}) { // 'full' | 'area' -> {path, thumb} | null
  ensureSession();
  const n = ++S.n;
  const full = path.join(S.dir, `screen${n}@full.png`);
  const small = path.join(S.dir, `screen${n}.png`);
  const d = mode === 'full' && watch.on ? watch.display() : targetDisplay();
  if (!keepPins) clearCallouts();
  const b = d.bounds;
  let r = {};
  if (SOURCE && mode === 'full') {
    fs.copyFileSync(path.join(SOURCE, 'latest.png'), full);
  } else {
    // keep the overlay and its pins out of their own screenshots
    const op = win.getOpacity(), pins = [...callouts.values()].flatMap(g => [g.outline, g.card]).filter(w => w && !w.isDestroyed());
    win.setOpacity(0); pins.forEach(w => w.setOpacity(0));
    await sleep(140);
    const args = mode === 'area' ? ['-i', '-x', full] : ['-x', '-R', `${b.x},${b.y},${b.width},${b.height}`, full];
    r = await run('/usr/sbin/screencapture', args);
    win.setOpacity(op); pins.forEach(w => { if (!w.isDestroyed()) w.setOpacity(1); });
  }
  if (!fs.existsSync(full)) {
    if (mode !== 'area') send('perm', true);
    S.n--; return null;
  }
  // Agent-sized copy (the Read tool downsamples huge images anyway); the @full original stays for zoom.py.
  await run('/usr/bin/sips', ['-Z', '2200', full, '--out', small]);
  if (!fs.existsSync(small)) fs.copyFileSync(full, small);
  S.lastScreen = small;
  send('perm', false);
  const size = nativeImage.createFromPath(full).getSize();
  S.shots[small] = { bounds: mode === 'full' ? { ...b } : null, size };
  return { path: small, thumb: nativeImage.createFromPath(small).resize({ width: 360 }).toDataURL() };
}

function saveImageData(dataUrl) { // pasted image -> session file
  ensureSession();
  const n = ++S.n;
  const p = path.join(S.dir, `screen${n}.png`);
  const img = nativeImage.createFromDataURL(dataUrl);
  fs.writeFileSync(p, img.toPNG());
  fs.copyFileSync(p, path.join(S.dir, `screen${n}@full.png`));
  S.lastScreen = p;
  S.shots[p] = { bounds: null, size: img.getSize() }; // pasted: OCR'd, but not tied to a place on screen
  return { path: p, thumb: img.resize({ width: 360 }).toDataURL() };
}

// ---------- overlays: outlines + answer cards on the real screen ----------
// The agent writes <place box="x0,y0,x1,y1" n="1">TEXT</place> (fractions of the full-screen screenshot) or
// px="x0,y0,x1,y1" (pixels of screenN@full.png). We map that to screen points using the display bounds recorded when
// the screenshot was taken, draw a click-through outline on the target, and float a draggable/resizable/closable
// answer card next to it. kind="label" pins are just a small tag on the outline (for naming items: ②, A, ...).
const callouts = new Map(); // id -> { lane, outline, card }
let calloutSeq = 0;

function overlayWindow(opts) {
  const w = new BrowserWindow({
    frame: false, transparent: true, backgroundColor: '#00000000', hasShadow: false, alwaysOnTop: true, focusable: false,
    skipTaskbar: true, type: 'panel', show: false, fullscreenable: false,
    webPreferences: { preload: path.join(HERE, 'preload.js'), contextIsolation: true }, ...opts,
  });
  w.setAlwaysOnTop(true, 'screen-saver');
  w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (!process.env.SIDEKICK_VISIBLE_IN_SHOTS) w.setContentProtection(true);
  w.once('ready-to-show', () => w.showInactive());
  return w;
}

function closeCallout(id) {
  const g = callouts.get(id); if (!g) return;
  callouts.delete(id);
  for (const w of [g.outline, g.card]) if (w && !w.isDestroyed()) w.close();
  send('callouts', callouts.size);
}

function clearCallouts(lane) {
  for (const [id, g] of [...callouts]) if (!lane || g.lane === lane) closeCallout(id);
  send('callouts', callouts.size);
}

function parsePlaces(text) {
  const out = [];
  const re = /<place\s+([^>]*)>([\s\S]*?)<\/place>/g; let m;
  while ((m = re.exec(text))) {
    const attrs = {}; m[1].replace(/(\w+)="([^"]*)"/g, (_, k, v) => { attrs[k] = v; });
    const nums = (attrs.box || attrs.px || '').split(/[\s,]+/).map(Number);
    if (nums.length !== 4 || nums.some(isNaN)) continue;
    out.push({ text: m[2].trim(), nums, px: !attrs.box, n: attrs.n || '', label: attrs.kind === 'label' });
  }
  return out;
}

function shiftCallouts(dx, dy) {
  if (SOURCE && S.dir) fs.appendFileSync(path.join(S.dir, 'pins.jsonl'), JSON.stringify({ t: Date.now(), shift: [dx, dy] }) + '\n');
  for (const g of callouts.values()) for (const w of [g.outline, g.card]) {
    if (!w || w.isDestroyed()) continue;
    const [x, y] = w.getPosition(); w.setPosition(x + dx, y + dy);
  }
}

function showCallout(place, shot, open, lane, turnId) {
  if (!shot) return;
  // Pins reflect the latest turn that pinned: the first pin of a turn clears earlier turns' pins; same n/label replaces.
  for (const [cid, g] of [...callouts]) {
    if (g.turn !== turnId || (place.n && g.n === place.n && g.label === place.label) || (place.label && g.label && g.text === place.text)) closeCallout(cid);
  }
  let [x0, y0, x1, y1] = place.nums;
  if (place.px) { x0 /= shot.size.width; x1 /= shot.size.width; y0 /= shot.size.height; y1 /= shot.size.height; }
  const clamp = v => Math.max(0, Math.min(1, v));
  [x0, x1] = [clamp(Math.min(x0, x1)), clamp(Math.max(x0, x1))];
  [y0, y1] = [clamp(Math.min(y0, y1)), clamp(Math.max(y0, y1))];
  const b = shot.bounds;
  const box = { x: Math.round(b.x + x0 * b.width), y: Math.round(b.y + y0 * b.height), w: Math.max(12, Math.round((x1 - x0) * b.width)), h: Math.max(12, Math.round((y1 - y0) * b.height)) };
  const id = ++calloutSeq;
  if (SOURCE) { // harness: record where the pin would go instead of drawing on the real screen
    fs.appendFileSync(path.join(S.dir, 'pins.jsonl'), JSON.stringify({ t: Date.now(), turn: turnId, lane, n: place.n, label: place.label, text: place.text, frac: [x0, y0, x1, y1], shot: S.lastScreen }) + '\n');
    callouts.set(id, { lane, turn: turnId, n: place.n, label: place.label, text: place.text });
    return send('callouts', callouts.size);
  }
  const outline = overlayWindow({ x: box.x - 3, y: box.y - 3, width: box.w + 6, height: box.h + 6, resizable: false, movable: false });
  outline.setIgnoreMouseEvents(true);
  outline.loadFile(path.join(HERE, 'outline.html'), { hash: encodeURIComponent(JSON.stringify({ tag: place.label ? place.text : '', n: place.label ? '' : place.n })) });
  let card = null;
  if (!place.label) {
    const wa = screen.getDisplayMatching({ x: box.x, y: box.y, width: box.w, height: box.h }).workArea;
    const cw = Math.max(150, Math.min(460, 110 + place.text.length * 12)), ch = 70;
    const above = box.y - ch - 8 >= wa.y;
    const cx = Math.max(wa.x, Math.min(box.x, wa.x + wa.width - cw));
    card = overlayWindow({ x: cx, y: above ? box.y - ch - 8 : Math.min(box.y + box.h + 8, wa.y + wa.height - ch), width: cw, height: ch,
      minWidth: 100, minHeight: 46, resizable: true, movable: true });
    card.loadFile(path.join(HERE, 'card.html'), { hash: encodeURIComponent(JSON.stringify({ id, text: place.text, n: place.n, open, lane })) });
    card.on('closed', () => closeCallout(id));
  }
  callouts.set(id, { lane, outline, card, turn: turnId, n: place.n, label: place.label, text: place.text });
  send('callouts', callouts.size);
}

ipcMain.handle('callout', (_, action, id) => {
  if (action === 'clear') return clearCallouts();
  if (action === 'close') return closeCallout(id);
});

// ---------- steps: the next actions for the player, marked on screen ----------
// <step do="hover|click|drag|type|scroll|record|look" at="x0,y0,x1,y1" to="x0,y0,x1,y1" text="…" record="12" dy="400">
// human text</step>. Boxes are fractions of the latest full screenshot. Each target gets a numbered marker on screen,
// drags get an arrow, record steps get a one-click ⏺ button in the panel. A new set of steps replaces the old one.
const stepWins = [];
function parseSteps(text) {
  const out = [];
  const re = /<step\s+([^>]*)>([\s\S]*?)<\/step>/g; let m;
  const box = v => { const n = (v || '').split(/[\s,]+/).map(Number); return n.length === 4 && !n.some(isNaN) ? n : null; };
  while ((m = re.exec(text))) {
    const a = {}; m[1].replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { a[k] = v; });
    out.push({ do: (a.do || 'look').toLowerCase(), at: box(a.at), to: box(a.to), text: a.text || '', record: a.record ? Number(a.record) : 0,
      dy: a.dy ? Number(a.dy) : 0, unit: a.unit ? Number(a.unit) : 0, expect: a.expect || '', say: m[2].trim() });
  }
  return out;
}
function clearStepMarks() { while (stepWins.length) { const w = stepWins.pop(); if (!w.isDestroyed()) w.close(); } }
function toScreen(fr, shot) {
  const b = shot.bounds;
  return { x: Math.round(b.x + fr[0] * b.width), y: Math.round(b.y + fr[1] * b.height), w: Math.max(10, Math.round((fr[2] - fr[0]) * b.width)), h: Math.max(10, Math.round((fr[3] - fr[1]) * b.height)) };
}
const sameStep = (a, b) => a.do === b.do && (!a.at || !b.at ? a.say === b.say : Math.abs(a.at[0] - b.at[0]) + Math.abs(a.at[1] - b.at[1]) < 0.03);
function showSteps(steps, turnId, keepDone = false) {
  clearStepMarks();
  if (keepDone) for (const st of steps) if ((S.steps?.list || []).some(o => o.done && sameStep(o, st))) st.done = true;
  // A new list often repeats recordings the player already made: keep those ticked (re-recording is wasted time).
  // Actions (click/drag/type) are NOT carried over: if the sidekick lists one again, it's a deliberate retry.
  const old = S.steps?.list || [];
  for (const st of steps) if ((st.record || st.do === 'record') && old.some(o => o.done && sameStep(o, st))) st.done = true;
  const shot = S.placeShot;
  S.steps = { turn: turnId, list: steps, shot: shot && { bounds: shot.bounds } };
  S.stepsSkips = 0;
  S.stepsAt = Date.now();
  send('steps', S.steps);
  if (SOURCE) { fs.appendFileSync(path.join(S.dir, 'steps.jsonl'), JSON.stringify({ t: Date.now(), turn: turnId, steps }) + '\n'); return; }
  if (!shot?.bounds) return;
  steps.forEach((st, i) => {
    if (!st.at) return;
    const r = toScreen(st.at, shot);
    const P = 16; // room outside the target for the number badge, so it never covers the target's own label
    const w = overlayWindow({ x: r.x - P, y: r.y - P, width: r.w + P + 4, height: r.h + P + 4, resizable: false, movable: false });
    w.setIgnoreMouseEvents(true);
    w.loadFile(path.join(HERE, 'outline.html'), { hash: encodeURIComponent(JSON.stringify({ tag: String(i + 1), step: true, pad: P })) });
    stepWins.push(w);
    if (st.to) { // arrow from the source to the destination
      const t = toScreen(st.to, shot);
      const a = { x: r.x + r.w / 2, y: r.y + r.h / 2 }, c = { x: t.x + t.w / 2, y: t.y + t.h / 2 }, P = 24;
      const x0 = Math.min(a.x, c.x) - P, y0 = Math.min(a.y, c.y) - P;
      const aw = overlayWindow({ x: Math.round(x0), y: Math.round(y0), width: Math.round(Math.abs(a.x - c.x) + 2 * P), height: Math.round(Math.abs(a.y - c.y) + 2 * P), resizable: false, movable: false });
      aw.setIgnoreMouseEvents(true);
      aw.loadFile(path.join(HERE, 'arrow.html'), { hash: encodeURIComponent(JSON.stringify({ a: [a.x - x0, a.y - y0], c: [c.x - x0, c.y - y0], n: i + 1 })) });
      stepWins.push(aw);
      const tw = overlayWindow({ x: t.x - 3, y: t.y - 3, width: t.w + 6, height: t.h + 6, resizable: false, movable: false });
      tw.setIgnoreMouseEvents(true);
      tw.loadFile(path.join(HERE, 'outline.html'), { hash: encodeURIComponent(JSON.stringify({ tag: `${i + 1}→`, step: true })) });
      stepWins.push(tw);
    }
  });
}
function recordStep(i) { // start the clip for step i (from its ⏺ button, or ⌃⌥R while hovering the item)
  const st = S.steps?.list?.[i]; if (!st) return;
  st.done = true; send('steps', S.steps);
  if (rec.proc) return send('toast', 'Already recording: wait for it to finish.');
  rec.start(st.say, { seconds: clipSeconds(st), box: st.at, unit: st.unit, expect: st.expect });
}
ipcMain.handle('step-record', (_, i) => recordStep(i));
ipcMain.handle('step-done', (_, i, done = true) => { const st = S.steps?.list?.[i]; if (st) { st.done = done; send('steps', S.steps); } });
// Clip length: long enough for the longest possible message once (countdown + Morse + margin), not a guess.
const MORSE_CODE = { A: '.-', B: '-...', C: '-.-.', D: '-..', E: '.', F: '..-.', G: '--.', H: '....', I: '..', J: '.---', K: '-.-', L: '.-..',
  M: '--', N: '-.', O: '---', P: '.--.', Q: '--.-', R: '.-.', S: '...', T: '-', U: '..-', V: '...-', W: '.--', X: '-..-', Y: '-.--', Z: '--..' };
function morseUnits(word) {
  const letters = word.toUpperCase().replace(/[^A-Z]/g, '').split('').map(ch => MORSE_CODE[ch] || '');
  const inLetter = l => l.split('').reduce((t, sym) => t + (sym === '-' ? 3 : 1), 0) + Math.max(0, l.length - 1);
  return letters.reduce((t, l) => t + inLetter(l), 0) + 3 * Math.max(0, letters.length - 1);
}
function clipSeconds(st) {
  const asked = st.record || 12;
  if (!st.expect || !st.unit) return asked;
  const longest = Math.max(...st.expect.split(/[,\s]+/).filter(Boolean).map(morseUnits));
  const need = 2.5 /* countdown + hover */ + longest * st.unit / 1000 + 1.5 /* margin */;
  return Math.max(6, Math.min(asked, Math.ceil(need)));
}
function nextRecordStep() { return (S.steps?.list || []).findIndex(st => (st.record || st.do === 'record') && !st.done); }
ipcMain.handle('steps-clear', () => { clearStepMarks(); S.steps = null; send('steps', null); });

// ---------- instant pre-pass: native OCR + book probe, before any model runs ----------
const OCR_BIN = path.join(ROOT, 'tools', 'ocr', 'ocr');
function ensureOcr() {
  if (fs.existsSync(OCR_BIN)) return;
  execFile('swiftc', ['-O', OCR_BIN + '.swift', '-o', OCR_BIN], { timeout: 180000 }, e => { if (e) console.warn('OCR build failed:', e.message); });
}
async function ocrLines(img) { // cached per image: ["x0 y0 x1 y1\ttext", ...]
  S.ocr = S.ocr || {};
  if (S.ocr[img]) return S.ocr[img];
  if (!fs.existsSync(OCR_BIN)) return [];
  const full = img.replace(/\.png$/, '@full.png');
  const o = await run(OCR_BIN, [fs.existsSync(full) ? full : img]);
  return (S.ocr[img] = (o.out || '').trim().split('\n').filter(Boolean));
}
async function prepass(img) {
  S.pre = S.pre || {};
  if (S.pre[img]) return S.pre[img];
  const lines = await ocrLines(img);
  if (!lines.length) return (S.pre[img] = '');
  const text = lines.map(l => l.split('\t')[1] || '').join(' ').slice(0, 1500);
  const probe = await new Promise(res => execFile('python3', ['tools/corpus.py', '--pages', ROUNDS[prefs.round], 'probe', text],
    { cwd: ROOT, timeout: 20000, maxBuffer: 4 << 20 }, (e, out) => res((out || '').trim())));
  // Board reader: tile grids (with symbol classes + highlighted cells) and marker tiles, with exact cell boxes.
  const full = img.replace(/\.png$/, '@full.png');
  const src = fs.existsSync(full) ? full : img;
  // Maze reader (tunnels / "walk between the walls"): only when the screen talks about a route out
  const mazey = /\b(walls?|maze|tunnels?|way out|top edge|escape|route)\b/i.test(text);
  const [gridOut, mazeOut] = await Promise.all([
    new Promise(res => execFile('python3', ['tools/grid.py', 'read', src, '--out', img.replace(/\.png$/, '_grid')],
      { cwd: ROOT, timeout: 20000, maxBuffer: 4 << 20 }, (e, out) => res((out || '').trim()))),
    mazey ? new Promise(res => execFile('python3', ['tools/maze.py', src],
      { cwd: ROOT, timeout: 20000, maxBuffer: 4 << 20 }, (e, out, err) => res(((out || '') + (err || '')).trim()))) : Promise.resolve(''),
  ]);
  const gridUseful = /GRID \d+: (\d+) rows × (\d+) cols/.test(gridOut) && gridOut.match(/GRID \d+: (\d+) rows × (\d+) cols/).slice(1).reduce((x, y) => x * y, 1) >= 9 || /MARKERS:|INPUT FIELDS/.test(gridOut);
  return (S.pre[img] = `PRE-PASS for ${path.basename(img)} (already done, don't repeat it):\n` +
    (gridUseful ? `Board reader (tools/grid.py read; boxes are image fractions, usable in <step at=…>):\n${gridOut.slice(0, 9000)}\n` : '') +
    (/MAZE \d+x\d+/.test(mazeOut) ? `Maze reader (tools/maze.py; CHECK its MAP against the screenshot before trusting the ROUTE):\n${mazeOut.slice(0, 12000)}\n` : '') +
    `OCR lines (x0 y0 x1 y1 as fractions of the screenshot, then text; use these boxes for <place>):\n${lines.slice(0, 90).join('\n')}\n` +
    `corpus.py --pages ${ROUNDS[prefs.round]} probe on that text:\n${probe.slice(0, 2500) || '(nothing)'}`);
}

// ---------- the agent: a quick lane and a deep lane ----------
// Balanced (default): every manual turn runs a fast Sonnet "quick take" and a thorough Opus "verify" in parallel,
// each in its own resumed Claude session. Watch-mode auto turns use only the quick lane (snappy, cheap); the deep
// lane is caught up on those at its next turn (a brand-new screen in Watch mode gets both lanes). Fast = quick lane
// only; Deep = deep lane only.
const LANES = {
  quick: { model: () => 'sonnet', effort: () => 'low',
    note: 'LANE=quick: you are the fast lane. Reply within ~15 seconds: open the screenshots first (OCR misses layout, icons and blanks), use the PRE-PASS, at most 2 more tool calls, then lead with your best current read and a confidence. A deep lane may be verifying in parallel. NEVER guess book facts: before any <answer> naming a person, place, page, number or quote, run one corpus.py search (e.g. of a phrase from an earlier stage). If you could not check it, give no <answer> tag and say the verified lane is checking.' },
  deep: { model: () => prefs.model, effort: () => process.env.SIDEKICK_DEEP_EFFORT || null,
    note: 'LANE=deep: you are the verification lane; a quick lane answered in parallel with a first read. Be right: check the chain, run the tools, test alternatives. Keep the reply short; if the answer is simple, say "✓" plus the answer tag.' },
};
function lanesFor(auto) {
  if (prefs.speed === 'fast') return ['quick'];
  if (prefs.speed === 'deep') return ['deep'];
  return auto ? ['quick'] : ['quick', 'deep'];
}
const busy = () => !!(S.capturing || S.lanes.quick.proc || S.lanes.deep.proc);

function toolLabel(name, input = {}) {
  if (name === 'Bash') return (input.command || '').replace(/\s+/g, ' ').slice(0, 140);
  if (name === 'Read') return 'read ' + path.relative(ROOT, input.file_path || '');
  if (name === 'Grep') return 'grep ' + (input.pattern || '');
  if (name === 'Glob') return 'glob ' + (input.pattern || '');
  return name;
}

// Deterministic results that are safe to show before any model has looked: currently the maze reader
// (tools/maze.py) when it reports exactly one reachable exit, no tied routes and no warnings.
function solverSteps(pre) {
  let name = 'maze solver';
  let m = pre.match(/Maze reader[^\n]*\n([\s\S]*?)(?=\n[A-Z][^\n]*\(tools\/|\nOCR lines|$)/);
  let out = m && m[1];
  if (!out || !/^ROUTE →/m.test(out)) { // the board reader matched a visible key card and walked it
    const k = pre.match(/^\s*KEY ROUTE →[^\n]*\n((?:\s*<step[^\n]*\n?)+)/m);
    if (!k) return null;
    out = k[0].replace(/^\s*KEY /m, ''); name = 'key matcher';
  }
  out = out.replace(/^\s+/gm, '');
  if (!/^ROUTE →/m.test(out) || /WARNING|NO WAY|^ALT /m.test(out)) return null;
  const steps = parseSteps(out).slice(1); // the start tile is pre-marked
  const cellsN = Number((out.match(/^ROUTE[^(]*\((\d+) cells/m) || [])[1] || 0);
  if (!steps.length || steps.length !== cellsN - 1) return null; // truncated or odd output: let the models handle it
  // finish with the submit button if the OCR saw one (so the player never waits on a model for the last click)
  const ocr = (pre.match(/OCR lines[^\n]*\n([\s\S]*?)(?=\ncorpus\.py|$)/) || [])[1] || '';
  const btn = ocr.split('\n').map(l => l.split('\t')).find(([b, t]) => b && /^\s*(continue|submit|done|confirm|check|enter)\s*$/i.test(t || ''));
  if (btn) {
    const v = btn[0].trim().split(/[\s,]+/).map(Number);
    if (v.length === 4 && !v.some(isNaN)) steps.push({ do: 'click', at: v, to: null, text: '', record: 0, dy: 0, unit: 0, expect: '', say: `Click ${btn[1].trim()}` });
  }
  return { name, steps, summary: (out.match(/^ROUTE[^\n]*/m) || [''])[0].slice(0, 300) };
}
function sameTargets(a, b) { // same click cells (box centres within half a cell), order-insensitive
  const ctr = st => { const v = String(st.at || '').split(',').map(Number); return v.length === 4 ? [(v[0] + v[2]) / 2, (v[1] + v[3]) / 2, Math.abs(v[2] - v[0])] : null; };
  const A = a.filter(x => x.do === 'click').map(ctr).filter(Boolean), B = b.filter(x => x.do === 'click').map(ctr).filter(Boolean);
  if (!A.length || !B.length) return false;
  const hit = (p, Q) => Q.some(q => Math.hypot(p[0] - q[0], p[1] - q[1]) < Math.max(p[2], q[2]) / 2);
  return B.every(q => hit(q, A));
}

async function agentTurn({ text, images = [], level, auto = false, lanes: laneOverride = null, trustQuick = false }) {
  if (busy()) return send('toast', 'Still thinking. Press Stop first.');
  ensureSession();
  S.capturing = true;
  try {
    if (!images.length && !S.lastScreen) { // nothing to look at yet: grab the screen instead of letting the agent go hunting
      const shot = await capture('full');
      if (!shot) return;
      images = [shot.path];
      send('user-msg', { text: '(current screen)', thumbs: [shot.thumb] });
    }
    send('thinking', true);
    var pre = (await Promise.all(images.filter(p => /\.png$/.test(p) && S.shots[p]).map(prepass))).filter(Boolean);
  } finally { S.capturing = false; }
  S.stopping = false;
  level = level || prefs.level;
  const header = `[level=${level} round=${prefs.round} pages=${ROUNDS[prefs.round]} auto=${auto ? 1 : 0}]`;
  let body = text || (images.length ? 'What is this screen? Help me at my level.' : '');
  if (S.pendingNotes.length) body += '\n\nPlayer ran:\n' + S.pendingNotes.join('\n\n');
  if (images.length) body += '\n\nScreenshots (open each with Read):\n' + images.map(p => {
    const m = S.shots[p]; return '- ' + p + (m ? ` (${m.bounds ? 'full screen' : 'pasted/close-up: not tied to the screen, cannot hold <place> boxes'}; @full is ${m.size.width}x${m.size.height}px)` : '');
  }).join('\n');
  if (pre.length) body += '\n\n' + pre.join('\n\n');
  const fullShots = images.filter(p => S.shots[p]?.bounds);
  if (fullShots.length) S.placeShot = S.shots[fullShots[fullShots.length - 1]];
  S.pendingNotes = [];
  log(`### ${auto ? 'auto' : 'player'} ${header}\n${text || ''}${images.length ? '\n' + images.map(p => path.basename(p)).join(', ') : ''}`);

  const lanes = laneOverride ? laneOverride.filter(l => lanesFor(false).includes(l)) : lanesFor(auto);
  const turn = { id: ++S.turnSeq, level, auto, lanes, t0: Date.now(), pending: new Set(lanes), deepPinned: false, replies: {}, trustQuick };
  S.turn = turn;
  send('turn-start', { turn: turn.id, lanes, auto, level });
  // DECISION LAYER: a deterministic solver whose result is self-consistent (one way out, no ties, no warnings) goes
  // straight to the screen. The LLM lanes still run: they confirm it, or override it with their own steps.
  const solved = solverSteps(pre.join('\n'));
  // once per route: re-showing the same route after the player marked some tiles would make them toggle marks off
  if (solved && level !== 'nudge' && level !== 'hint' && S.lastSolver !== solved.summary) {
    S.lastSolver = solved.summary;
    turn.solver = solved;
    showSteps(solved.steps, turn.id);
    send('toast', `⚡ ${solved.name}: route ready (${solved.steps.length} clicks), verifying…`);
    log(`**solver** (${solved.name}, ${((Date.now() - turn.t0) / 1000).toFixed(1)}s): ${solved.summary}`);
    body += `\n\nDECISION LAYER: the ${solved.name} result above was self-consistent and its ${solved.steps.length} click steps are ALREADY on the player's screen. ` +
      'Check its MAP against the screenshot once (no zoom/crop tools unless something looks wrong). If it is right, reply "✓" with the answer tag and no tile steps (at most one <step> for the submit button). ' +
      'Only if it is wrong, explain in one line and give the corrected <step>s (they replace the solver\'s).';
  }
  for (const lane of lanes) {
    let prompt = `${header}\n${LANES[lane].note}\n\n${body}`;
    if (lane === 'quick' && S.deepNote) // the lanes are separate sessions: keep the fast one in sync with verified findings
      prompt = `${header}\n${LANES.quick.note}\n\nVERIFIED LANE'S LATEST (trust it unless the screen now contradicts it):\n${S.deepNote}\n\n${body}`;
    if (lane === 'deep' && S.catchup.length) {
      prompt = `${header}\n${LANES.deep.note}\n\nSince your last turn (quick lane only, for context):\n${S.catchup.join('\n')}\n\nNow:\n${body}`;
      S.catchup = [];
    }
    runLane(lane, prompt, turn);
  }
  if (!lanes.includes('deep')) S.catchup.push(`- [${auto ? 'auto' : 'player'}] ${(text || '').slice(0, 200)} ${images.map(p => path.basename(p)).join(', ')}`);
}

async function runLane(lane, prompt, turn) {
  const L = S.lanes[lane];
  if (S.warm?.[lane]) await S.warm[lane];
  const args = ['-p', prompt, '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
    '--append-system-prompt-file', S.sysFile, '--strict-mcp-config', '--add-dir', '/tmp/puzzle_zoom',
    '--allowedTools', ...TOOLS, '--model', LANES[lane].model()];
  const effort = LANES[lane].effort(turn.auto);
  if (effort) args.push('--effort', effort);
  if (L.id) args.push('--resume', L.id);
  fs.mkdirSync('/tmp/puzzle_zoom', { recursive: true });
  const proc = spawn(claudeBin, args, { cwd: ROOT, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
  L.proc = proc;
  send('lane-start', { turn: turn.id, lane });
  let buf = '', full = '', stderr = '', placed = 0, ended = false; const tools = [];
  const end = info => {
    if (ended) return; ended = true;
    if (L.proc === proc) L.proc = null;
    send('lane-end', { turn: turn.id, lane, secs: ((Date.now() - turn.t0) / 1000).toFixed(1), ...info });
    turn.pending.delete(lane);
    if (!turn.pending.size) send('turn-end', { turn: turn.id });
  };
  proc.stdout.on('data', chunk => {
    buf += chunk;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      if (!line.trim()) continue;
      let m; try { m = JSON.parse(line); } catch { continue; }
      if (m.session_id && !L.id) L.id = m.session_id;
      if (m.type === 'stream_event') {
        const ev = m.event || {};
        if (ev.type === 'content_block_start' && ev.content_block?.type === 'text' && full) { full += '\n\n'; send('delta', { lane, turn: turn.id, t: '\n\n' }); }
        if (ev.type === 'content_block_delta' && ev.delta?.type === 'text_delta') {
          full += ev.delta.text; send('delta', { lane, turn: turn.id, t: ev.delta.text });
          const places = parsePlaces(full); // pin each one the moment its tag is complete
          while (placed < places.length) {
            const p = places[placed++];
            if (lane === 'deep' && !turn.deepPinned) { turn.deepPinned = true; clearCallouts('quick'); } // verified pins replace quick ones
            if (lane === 'quick' && turn.deepPinned) continue;
            showCallout(p, S.placeShot, turn.level === 'solve', lane, turn.id);
          }
        }
      } else if (m.type === 'assistant') {
        for (const c of m.message?.content || []) if (c.type === 'tool_use') { const t = toolLabel(c.name, c.input); tools.push(t); send('tool', { lane, turn: turn.id, label: t }); }
      } else if (m.type === 'result') {
        if (m.session_id) L.id = m.session_id;
        turn.replies[lane] = full.trim();
        if (lane === 'deep' && full.trim()) {
          const ans = (full.match(/<answer[^>]*>([\s\S]*?)<\/answer>/) || [])[1];
          const prose = full.replace(/<(step|place)[^>]*>[\s\S]*?<\/\1>/g, '').replace(/<answer[^>]*>[\s\S]*?<\/answer>/g, '').replace(/\s+/g, ' ').trim();
          const st = parseSteps(full).map((x, i) => `${i + 1}. ${x.say}`).join('; ');
          S.deepNote = (ans ? `Answer: ${ans.trim()}\n` : '') + `Said: ${prose.slice(0, 700)}` + (st ? `\nSteps given: ${st.slice(0, 600)}` : '');
        }
        const steps = parseSteps(full);
        // Steps that ENTER a solution (drag/type/click at level=solve) wait for the verified lane when one is running;
        // information-gathering steps (hover/record/look/scroll) from the quick lane can go out right away.
        // opening a key / drawer / transmission is looking, not answering: it needn't wait for the verified lane
        const looking = st => st.do === 'click' && /\b(key|view|open|show|expand|reveal|transmission|legend|help)\b/i.test(st.say) && !/\b(mark|continue|submit|yes|confirm|row \d)/i.test(st.say);
        const entering = steps.some(st => ['drag', 'type', 'click'].includes(st.do) && !looking(st));
        const agrees = turn.solver && steps.length && sameTargets(steps, turn.solver.steps);
        const deepPending = turn.lanes.includes('deep') && turn.pending.has('deep') && lane === 'quick' && !turn.trustQuick && !agrees;
        if (turn.solver && steps.length && (agrees || steps.length <= 2)) {
          // the solver's tiles are already on screen (maybe half clicked): keep them and their progress, add what's new
          const cur = S.steps?.list || [];
          const extra = steps.filter(st => !cur.some(o => sameStep(o, st)) && !(agrees && st.do === 'click' && sameTargets([st], turn.solver.steps)));
          if (extra.length) showSteps([...cur.map(o => ({ ...o })), ...extra], turn.id, true);
        } else if (steps.length && !(entering && deepPending) && (lane === 'deep' || !turn.lanes.includes('deep') || !turn.deepSteps)) {
          if (lane === 'deep') turn.deepSteps = true;
          showSteps(steps, turn.id);
        }
        if (lane === 'quick' && !turn.lanes.includes('deep') && S.catchup.length) S.catchup[S.catchup.length - 1] += `\n  quick lane said: ${full.trim().replace(/\s+/g, ' ').slice(0, 500)}`;
        const error = S.stopping ? 'stopped' : m.is_error ? (m.result || m.subtype || 'error') : null;
        log(`**${lane}** (${((Date.now() - turn.t0) / 1000).toFixed(1)}s · $${(m.total_cost_usd || 0).toFixed(3)} · ${tools.length} tools)${tools.length ? '\n<!-- tools: ' + tools.join(' ; ').replace(/-->/g, '') + ' -->' : ''}\n${full.trim()}`);
        end({ ok: !error, cost: m.total_cost_usd, error });
        const q = S.lanes.quick;
        if (lane === 'deep' && !error && q.proc && turn.pending.has('quick')) { q.superseded = true; q.proc.kill('SIGINT'); } // verified answer is in; the quick take is moot
      }
    }
  });
  proc.stderr.on('data', d => { stderr += d; });
  proc.on('close', code => {
    if (L.superseded) { L.superseded = false; end({ ok: false, error: 'superseded' }); }
    else if (S.stopping || code === null) end({ ok: false, error: 'stopped' });
    else if (code !== 0) end({ ok: false, error: (stderr || `claude exited with code ${code}`).slice(-600) });
    else end({ ok: true });
  });
  proc.on('error', e => end({ ok: false, error: `could not start claude (${e.message}). Is Claude Code installed and logged in?` }));
}

function stopAll() {
  S.stopping = true;
  for (const L of Object.values(S.lanes)) if (L.proc) L.proc.kill('SIGINT');
}

// ---------- deterministic commands (/probe, /search, ...) ----------
function splitArgs(s) {
  const out = []; const re = /"([^"]*)"|'([^']*)'|(\S+)/g; let m;
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

function commandArgs(line) {
  const sub = line.replace(/\$LAST/g, S.lastScreen ? S.lastScreen.replace(/\.png$/, '@full.png') : '$LAST');
  let [cmd, ...rest] = splitArgs(sub.slice(1));
  const tail = sub.slice(1).trim().slice(cmd.length).trim();
  const unq = t => t.replace(/^(["'])(.*)\1$/s, '$2');
  let pages = [];
  if (rest[0] === '--pages') { pages = ['--pages', rest[1]]; rest = rest.slice(2); }
  if (cmd === 'r') { pages = ['--pages', ROUNDS[prefs.round]]; [cmd, ...rest] = rest; } // /r search ... = current round only
  if (cmd === 'anagram') { // /anagram SOME LETTERS --lengths "4 3" -> tools/anagram.py (book-first, multi-word)
    const i = rest.findIndex(t => t.startsWith('--'));
    const letters = (i < 0 ? rest : rest.slice(0, i)).join('');
    return ['tools/anagram.py', letters, ...(i < 0 ? [] : rest.slice(i))];
  }
  if (CORPUS_CMDS.has(cmd)) {
    if (ONE_ARG.has(cmd)) rest = [unq(tail.replace(/^(r\s+\S+\s+)?(--pages\s+\S+\s+)?/, ''))];
    if (cmd === 'search') { // "/search some phrase --letters" -> phrase stays one argument
      const flags = [], words = [];
      for (let i = 0; i < rest.length; i++) {
        if (rest[i] === '-C') flags.push(rest[i], rest[++i]);
        else if (rest[i].startsWith('-')) flags.push(rest[i]);
        else words.push(rest[i]);
      }
      rest = [words.join(' '), ...flags];
    }
    return ['tools/corpus.py', ...pages, cmd, ...rest];
  }
  const scripts = { solvers: 'tools/solvers.py', zoom: 'tools/zoom.py', bars: 'tools/bars.py', corpus: 'tools/corpus.py' };
  if (scripts[cmd]) return [scripts[cmd], ...rest];
  return null;
}

function runCommand(line) {
  const args = commandArgs(line);
  if (!args) return Promise.resolve({ ok: false, out: `Unknown command. Try /probe, /search, /decode, /page, /r <cmd> (current round), /solvers, /gaz, /zoom, /bars.` });
  return new Promise(res => execFile('python3', args, { cwd: ROOT, timeout: 60000, maxBuffer: 8 << 20 }, (e, out, err) => {
    const text = (out || '') + (err ? '\n' + err : '');
    const clipped = text.length > 4000 ? text.slice(0, 4000) + '\n…(truncated)' : text;
    S.pendingNotes.push(`$ python3 ${args.join(' ')}\n${clipped.trim()}`);
    if (S.dir) log(`$ python3 ${args.join(' ')}\n\`\`\`\n${clipped.trim()}\n\`\`\``);
    res({ ok: !e || !!out, out: text.trim() || (e ? e.message : '(no output)') });
  }));
}

// ---------- Watch mode: follow the player's screen and give feedback as they work ----------
// Every TICK_MS a small thumbnail of the watched display is compared, block by block, with the screen the sidekick
// last saw. When something changed (even a small area: a typed letter, a moved tile) and the screen has held still
// for SETTLE_TICKS ticks, it grabs a full screenshot and sends an auto turn describing where the change happened.
// Changes made while the agent is talking are not lost: the baseline only moves when a screen is actually sent.
// If nothing changes for STUCK_MS after feedback, it offers one gentle nudge for that screen.
const TICK_MS = 1200, SETTLE_TICKS = 2, MIN_GAP_MS = 4000, STUCK_MS = 60000;
const GX = 24, GY = 14; // comparison grid
const CHURN_NOISY = 0.35; // cells that change on their own this often (timers, pulsing icons) are ignored
const FEEDBACK_RE = /\b(no|wrong|incorrect|not quite|try again|look again|correct|complete|completed|solved|well done|success|stage \d|level \d|accuracy)\b/i;
const TIME_RE = /^[\s\d:.,/]*$|\b\d{1,2}:\d{2}(:\d{2})?\b/; // OCR lines that are just clocks/counters ticking
const watch = {
  on: false, timer: null, base: null, prev: null, stable: 0, lastSent: 0, lastChange: 0, stuckSent: false,
  displayId: null, looks: 0, ticking: false, churn: new Float32Array(GX * GY), lastOcr: null, scrolledSinceBase: 0,

  display() {
    // Follow the cursor between displays, but ignore it while it's over the overlay itself.
    const pt = screen.getCursorScreenPoint(), b = win.getBounds();
    const onOverlay = pt.x >= b.x && pt.x <= b.x + b.width && pt.y >= b.y && pt.y <= b.y + b.height;
    if (!onOverlay || !this.displayId) this.displayId = screen.getDisplayNearestPoint(pt).id;
    return screen.getAllDisplays().find(d => d.id === this.displayId) || screen.getPrimaryDisplay();
  },

  async grab() {
    const d = this.display();
    let img;
    if (SOURCE) { // test harness: a frame file stands in for the whole display
      const f = path.join(SOURCE, 'latest.png');
      if (!fs.existsSync(f)) return null;
      img = nativeImage.createFromPath(f).resize({ width: 480 });
    } else {
      const size = { width: 480, height: Math.round(480 * d.bounds.height / d.bounds.width) };
      const srcs = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: size });
      const src = srcs.find(s => String(s.display_id) === String(d.id)) || srcs[0];
      if (!src) return null;
      img = src.thumbnail;
    }
    if (img.isEmpty()) return null;
    const sz = img.getSize(), bmp = img.toBitmap();
    // Mask: outside the work area (menu-bar clock, Dock) and the overlay's own rectangle don't count.
    const sx = sz.width / d.bounds.width, sy = sz.height / d.bounds.height, wb = win.getBounds(), wa = d.workArea;
    const [mx0, my0] = [(wb.x - d.bounds.x) * sx, (wb.y - d.bounds.y) * sy], [mx1, my1] = [mx0 + wb.width * sx, my0 + wb.height * sy];
    const [ax0, ay0] = SOURCE ? [0, 0] : [(wa.x - d.bounds.x) * sx, (wa.y - d.bounds.y) * sy];
    const [ax1, ay1] = SOURCE ? [sz.width, sz.height] : [ax0 + wa.width * sx, ay0 + wa.height * sy];
    const masked = (x, y) => x < ax0 || x >= ax1 || y < ay0 || y >= ay1 || (!SOURCE && win.isVisible() && x >= mx0 && x <= mx1 && y >= my0 && y <= my1);
    const cells = new Float32Array(GX * GY * 3), counts = new Uint32Array(GX * GY), edges = new Float32Array(GX * GY);
    const rows = new Float32Array(sz.height), rowN = new Uint32Array(sz.height);
    for (let y = 0; y < sz.height; y++) {
      const cy = Math.min(GY - 1, Math.floor(y * GY / sz.height));
      for (let x = 0; x < sz.width; x++) {
        if (masked(x, y)) continue;
        const c = cy * GX + Math.min(GX - 1, Math.floor(x * GX / sz.width)), i = (y * sz.width + x) * 4;
        cells[c * 3] += bmp[i]; cells[c * 3 + 1] += bmp[i + 1]; cells[c * 3 + 2] += bmp[i + 2]; counts[c]++;
        if (x > 0) edges[c] += Math.abs(bmp[i + 1] - bmp[i - 3]); // fine detail: text edits barely move the mean colour
        rows[y] += (bmp[i] + bmp[i + 1] + bmp[i + 2]) / 3; rowN[y]++;
      }
    }
    for (let c = 0; c < GX * GY; c++) if (counts[c]) { cells[c * 3] /= counts[c]; cells[c * 3 + 1] /= counts[c]; cells[c * 3 + 2] /= counts[c]; edges[c] /= counts[c]; }
    for (let y = 0; y < sz.height; y++) rows[y] = rowN[y] ? rows[y] / rowN[y] : NaN;
    return { cells, edges, counts, rows, h: sz.height, scaleY: d.bounds.height / sz.height, displayId: d.id };
  },

  cellChanged(a, b, c) {
    const col = (Math.abs(a.cells[c * 3] - b.cells[c * 3]) + Math.abs(a.cells[c * 3 + 1] - b.cells[c * 3 + 1]) + Math.abs(a.cells[c * 3 + 2] - b.cells[c * 3 + 2])) / 3;
    return col > 4 || Math.abs(a.edges[c] - b.edges[c]) > 1.5;
  },

  // -> { changed: fraction of (non-noisy) cells that changed, n: count, box: bounding box of changed cells as screen fractions }
  compare(a, b) {
    if (!a || !b || a.displayId !== b.displayId) return { changed: 1, n: GX * GY, box: null };
    let n = 0, total = 0, x0 = GX, x1 = -1, y0 = GY, y1 = -1;
    for (let c = 0; c < GX * GY; c++) {
      if (!a.counts[c] || !b.counts[c] || this.churn[c] > CHURN_NOISY) continue;
      total++;
      if (this.cellChanged(a, b, c)) {
        n++;
        const x = c % GX, y = Math.floor(c / GX);
        x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
      }
    }
    return { changed: total ? n / total : 0, n, box: n ? { x0: x0 / GX, x1: (x1 + 1) / GX, y0: y0 / GY, y1: (y1 + 1) / GY } : null };
  },

  learnNoise(a, b) { // exponential average of "this cell changed since last tick"
    if (!a || !b || a.displayId !== b.displayId) return;
    for (let c = 0; c < GX * GY; c++) if (a.counts[c] && b.counts[c]) this.churn[c] = this.churn[c] * 0.85 + (this.cellChanged(a, b, c) ? 0.15 : 0);
  },

  // Vertical scroll between two grabs, from row-brightness profiles: content moved by dy thumbnail px (0 = no scroll).
  scrollShift(a, b) {
    if (!a || !b || a.h !== b.h) return 0;
    const h = a.h, err = s => {
      let sum = 0, n = 0;
      for (let y = Math.max(0, -s); y < h && y + s < h; y++) {
        const u = a.rows[y], v = b.rows[y + s];
        if (Number.isNaN(u) || Number.isNaN(v)) continue;
        sum += Math.abs(u - v); n++;
      }
      return n > h * 0.35 ? sum / n : Infinity;
    };
    const e0 = err(0);
    if (e0 < 1) return 0;
    let best = 0, be = e0;
    for (let s = -Math.floor(h * 0.6); s <= Math.floor(h * 0.6); s++) { if (!s) continue; const e = err(s); if (e < be) { be = e; best = s; } }
    return be < e0 * 0.35 && be < 3 ? best : 0;
  },

  status(state) { send('watch', { on: this.on, state, looks: this.looks, lastSent: this.lastSent }); },

  // What text appeared/disappeared since the last look (clock ticks ignored).
  textDiff(prev, cur) {
    const norm = l => (l.split('\t')[1] || '').trim();
    const a = new Set((prev || []).map(norm).filter(t => t && !TIME_RE.test(t)));
    const b = new Set(cur.map(norm).filter(t => t && !TIME_RE.test(t)));
    return { added: [...b].filter(t => !a.has(t)), removed: [...a].filter(t => !b.has(t)) };
  },

  async look(reason, text, { box, fresh = false, cur = null } = {}) {
    if (fresh) { clearCallouts(); clearStepMarks(); } // a different screen: old pins and step marks point at nothing
    const shot = await capture('full', { keepPins: !fresh });
    if (!shot) return false;
    const lines = await ocrLines(shot.path);
    const diff = this.lastOcr ? this.textDiff(this.lastOcr, lines) : null;
    this.lastOcr = lines;
    // A small visual change with no text change (hover glow, cursor blink) isn't worth a turn.
    if (cur && !fresh && diff && !diff.added.length && !diff.removed.length && (cur.n || 0) < 3 && !this.scrolledSinceBase) {
      this.status('watching');
      return false;
    }
    this.looks++; this.lastSent = Date.now(); this.stuckSent = false;
    send('user-msg', { text: reason, thumbs: [shot.thumb], auto: true });
    let what = '';
    if (box) what += `\nChange region (fractions of the screen): x ${box.x0.toFixed(2)}–${box.x1.toFixed(2)}, y ${box.y0.toFixed(2)}–${box.y1.toFixed(2)}.`;
    if (this.scrolledSinceBase) what += `\nThe player scrolled: content moved ${this.scrolledSinceBase > 0 ? 'down' : 'up'} ~${Math.abs(Math.round(this.scrolledSinceBase))}px (your pins were moved to follow).`;
    if (diff && (diff.added.length || diff.removed.length)) {
      what += '\nWHAT CHANGED (OCR text):' + diff.added.slice(0, 20).map(t => `\n+ ${t}`).join('') + diff.removed.slice(0, 20).map(t => `\n- ${t}`).join('');
    }
    this.scrolledSinceBase = 0;
    // Escalate to the verified lane when solving is needed: a new screen/stage, several lines of text changing, or the
    // page giving feedback on an entry. Small changes (typing in progress) get the quick lane only.
    const nChanged = diff ? diff.added.length + diff.removed.length : 99;
    const feedback = diff && diff.added.some(t => FEEDBACK_RE.test(t));
    const significant = fresh || nChanged >= 3 || feedback;
    // The player is working through the step list: small changes are the steps' own effects. Don't re-plan on each
    // one (it churns the list); allow about one skipped look per pending step, then look again.
    const pending = (S.steps?.list || []).filter(st => !st.done).length;
    if (!fresh && !feedback && pending > 0) {
      S.stepsSkips = (S.stepsSkips || 0) + 1;
      if (S.stepsSkips <= pending) { this.status('watching'); return false; }
    }
    S.stepsSkips = 0;
    if (feedback) what += '\nThe page just gave feedback on an entry. If it says wrong, re-check your chain from scratch (and the corpus) before suggesting anything new.';
    agentTurn({ text: text + what, images: [shot.path], auto: true, lanes: significant ? ['quick', 'deep'] : null });
    return true;
  },

  async tick() {
    if (!this.on || this.ticking || rec.proc || rec.batch?.length) return; // paused while recording / clips pending
    this.ticking = true;
    try {
      const cur = await this.grab();
      if (!cur) return this.status('no-signal');
      // Scrolling: move pinned cards with the content right away, before anything else.
      const dy = this.scrollShift(this.prev, cur);
      if (dy) { shiftCallouts(0, Math.round(dy * cur.scaleY)); this.scrolledSinceBase += dy * cur.scaleY; }
      this.learnNoise(this.prev, cur);
      const vsPrev = this.compare(cur, this.prev);
      this.prev = cur;
      this.stable = vsPrev.n === 0 ? this.stable + 1 : 0;
      if (!this.base) { this.base = cur; return; }
      const vsBase = this.compare(cur, this.base);
      const isBusy = busy();
      if (vsBase.n > 0) {
        this.lastChange = Date.now();
        if (this.stable < SETTLE_TICKS) return this.status('changing');
        // Just gave the player steps: let them act before looking again (a look mid-action sees a stale screen and
        // re-issues steps that are already happening). The change isn't lost; the base stays until we look.
        const pendingN = (S.steps?.list || []).filter(st => !st.done).length;
        if (S.stepsAt && pendingN && Date.now() - S.stepsAt < Math.min(20000, 3000 + 1500 * pendingN)) return this.status('watching');
        // the fast path's steps are all done and the screen moved on (e.g. a confirm dialog): the lanes are only
        // double-checking an answer the player already entered, so stop them and look at the new screen now
        if (isBusy && S.turn?.solver && !pendingN && (S.steps?.list || []).length) { stopAll(); return this.status('queued'); }
        if (isBusy || Date.now() - this.lastSent < MIN_GAP_MS) return this.status('queued');
        this.status('looking');
        const fresh = vsBase.changed > 0.35 && !this.scrolledSinceBase;
        this.base = cur;
        await this.look(fresh ? '↻ new screen' : this.scrolledSinceBase ? '↻ you scrolled' : '↻ you changed something',
          fresh ? 'WATCH: new screen: the page changed completely (new stage, dialog or page). Solve what is on it now.'
            : 'WATCH: something changed on this screen. React to what the player did (check anything they entered against your solution).',
          { box: fresh ? null : vsBase.box, fresh, cur: vsBase });
        return;
      }
      if (!isBusy && this.lastSent && !this.stuckSent && Date.now() - Math.max(this.lastSent, this.lastChange) > STUCK_MS) {
        this.stuckSent = true;
        this.status('looking');
        send('user-msg', { text: '⏳ no progress for a minute', auto: true });
        agentTurn({ text: 'WATCH: the screen has not changed for a minute since your last feedback. If the player looks stuck, give the next small step at their level (1–2 lines). If they are clearly just reading, reply ·', auto: true, lanes: ['quick', 'deep'] });
        return;
      }
      this.status(isBusy ? 'thinking' : 'watching');
    } catch (e) {
      send('perm', true);
      send('toast', 'Watch stopped: ' + e.message);
      this.stop();
    } finally { this.ticking = false; }
  },

  async start() {
    if (this.on) return;
    Object.assign(this, { on: true, base: null, prev: null, stable: 0, looks: 0, stuckSent: false, displayId: null, lastChange: Date.now(),
      churn: new Float32Array(GX * GY), lastOcr: null, scrolledSinceBase: 0 });
    prefs.follow = true; send('prefs', prefs);
    this.display();
    this.status('looking');
    this.timer = setInterval(() => this.tick(), TICK_MS);
    // First look right away, so clicking Watch gives feedback immediately.
    if (!busy()) {
      this.base = await this.grab();
      await this.look('◉ watching your screen', 'WATCH: the player just turned on Watch mode. Say what this screen is and what to do first (at their level). From now on you will get their screen whenever it changes.', { fresh: true });
    }
  },

  stop() {
    this.on = false; clearInterval(this.timer); this.timer = null;
    prefs.follow = false; send('prefs', prefs);
    this.status('off');
  },

  toggle() { this.on ? this.stop() : this.start(); },
};

// Batch assignment for clip readings: each expected word belongs to at most one item, all items share one polarity.
// costs[i] = { WORD: cost } per clip; a clip may stay unassigned (decoy / unclear) at SKIP cost.
// Decoy vocabulary scored alongside the clue's words: an item that reads as one of these is probably a decoy.
const BG_WORDS = ['ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'TEN', 'ELEVEN', 'TWELVE',
  'NORTH', 'SOUTH', 'EAST', 'WEST', 'RED', 'BLUE', 'GREEN', 'BLACK', 'WHITE', 'YES', 'NO',
  // Roster names from your corpus go here: a clip that reads as one of these is probably a decoy.
  'ASHBY', 'BRENNER', 'CALLOW', 'DUNMORE', 'ELSWORTH', 'FAIRBAIRN', 'GRANT', 'HOLLIS', 'IVERS', 'KEANE',
  'LOWELL', 'MERCER', 'NORTH', 'OAKES', 'RIVERA', 'OKONKWO', 'DELACROIX', 'SAAD', 'HOST'];
// skip[i]: cost of leaving clip i unassigned (its best background-word fit, capped).
// Minimum-cost assignment (Hungarian algorithm): rows = clips, columns = words + one "skip" column per clip.
function assignWords(costs, SKIP = 0.32, skip = null) {
  const words = [...new Set(costs.flatMap(c => Object.keys(c)))];
  const n = costs.length; if (!n) return null;
  const m = words.length + n, BIG = 1e6;
  const C = costs.map((c, i) => [...words.map(w => (c[w] === undefined ? BIG : c[w])),
    ...Array.from({ length: n }, (_, j) => (j === i ? (skip ? Math.min(SKIP, skip[i]) : SKIP) : BIG))]);
  // Hungarian (Jonker-style potentials), n rows <= m columns
  const u = Array(n + 1).fill(0), v = Array(m + 1).fill(0), p = Array(m + 1).fill(0), way = Array(m + 1).fill(0);
  for (let i = 1; i <= n; i++) {
    p[0] = i; let j0 = 0; const minv = Array(m + 1).fill(Infinity), used = Array(m + 1).fill(false);
    do {
      used[j0] = true; const i0 = p[j0]; let delta = Infinity, j1 = 0;
      for (let j = 1; j <= m; j++) if (!used[j]) {
        const cur = C[i0 - 1][j - 1] - u[i0] - v[j];
        if (cur < minv[j]) { minv[j] = cur; way[j] = j0; }
        if (minv[j] < delta) { delta = minv[j]; j1 = j; }
      }
      for (let j = 0; j <= m; j++) if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta;
      j0 = j1;
    } while (p[j0] !== 0);
    do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
  }
  const pick = Array(n).fill(null); let total = 0;
  for (let j = 1; j <= m; j++) if (p[j]) { const i = p[j] - 1; total += C[i][j - 1]; if (j <= words.length) pick[i] = { word: words[j - 1], cost: C[i][j - 1] }; }
  return { total, pick };
}

// ---------- recording: for things a screenshot can't catch (blinks, flashes, animations, sequences) ----------
// ffmpeg records the display (with the cursor) until you press Stop or REC_MAX_S passes; tools/motion.py then
// finds what moved, times every on/off change, tries Morse, and writes keyframe/region/plot images for the agent.
const REC_MAX_S = 30;
const rec = {
  proc: null, file: null, t0: 0, timer: null, note: '', display: null,
  avIndex(d) { // avfoundation numbers screens main-first
    const prim = screen.getPrimaryDisplay();
    if (d.id === prim.id) return 0;
    const others = screen.getAllDisplays().filter(x => x.id !== prim.id).sort((a, b) => a.bounds.x - b.bounds.x || a.bounds.y - b.bounds.y);
    return 1 + others.findIndex(x => x.id === d.id);
  },
  toggle(note, opts) { return this.proc ? this.stop() : this.start(note, opts); },
  // opts.seconds: auto-stop; opts.box: [x0,y0,x1,y1] screen fractions of the item being watched (analysis is cropped to it)
  start(note = '', { seconds = REC_MAX_S, box = null, unit = 0, expect = '' } = {}) {
    if (this.proc) return;
    ensureSession();
    clearTimeout(this.batchTimer); // another clip is coming: hold the analysis turn
    this.note = note; this.box = box; this.unit = unit; this.expect = expect; this.seconds = Math.min(REC_MAX_S, seconds);
    this.display = watch.on ? watch.display() : targetDisplay();
    this.file = path.join(S.dir, `clip${++S.clips}.mp4`);
    this.t0 = Date.now();
    this.timer = setInterval(() => send('rec', { on: true, secs: Math.round((Date.now() - this.t0) / 1000), max: this.seconds }), 500);
    send('rec', { on: true, secs: 0, max: this.seconds });
    if (SOURCE) { // harness: the driver records the page and drops the clip where we ask
      const id = S.clips;
      fs.writeFileSync(path.join(SOURCE, 'rec_request.json'), JSON.stringify({ id, seconds: this.seconds, out: this.file }));
      this.proc = { harness: true };
      const file = this.file;
      (async () => { const t = Date.now(); while (!fs.existsSync(file + '.done') && Date.now() - t < (this.seconds + 30) * 1000) await sleep(300); this.finish(''); })();
      return;
    }
    const args = ['-hide_banner', '-loglevel', 'error', '-f', 'avfoundation', '-capture_cursor', '1', '-framerate', '30', '-pixel_format', 'nv12',
      '-i', `Capture screen ${this.avIndex(this.display)}:none`, '-t', String(this.seconds), '-vf', 'scale=1280:-2',
      '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22', '-pix_fmt', 'yuv420p', '-y', this.file];
    let err = '';
    const proc = spawn('ffmpeg', args, { stdio: ['pipe', 'ignore', 'pipe'] });
    this.proc = proc;
    proc.stderr.on('data', d => { err += d; });
    proc.on('error', e => { send('toast', 'Recording needs ffmpeg (brew install ffmpeg): ' + e.message); this.reset(); });
    proc.on('close', () => this.finish(err));
  },
  stop() { if (this.proc && !this.proc.harness) { try { this.proc.stdin.write('q'); } catch { this.proc.kill('SIGINT'); } } },
  reset() { clearInterval(this.timer); this.proc = null; send('rec', { on: false }); },
  async finish(err) {
    const secs = ((Date.now() - this.t0) / 1000).toFixed(1), file = this.file, note = this.note, d = this.display, box = this.box;
    const unit = this.unit, expect = this.expect;
    this.reset();
    if (!fs.existsSync(file) || fs.statSync(file).size < 1000) {
      return send('toast', 'Recording failed. Allow Screen Recording for this app, then relaunch.\n' + err.split('\n').filter(l => !/NSKVONotifying/.test(l)).slice(-3).join('\n'));
    }
    send('user-msg', { text: `⏺ recorded ${secs}s${note ? ': ' + note : ''}`, auto: true });
    const outDir = file.replace(/\.mp4$/, '_motion');
    const margs = ['tools/motion.py', file, '--out', outDir];
    if (unit) margs.push('--unit', String(unit));
    if (expect) margs.push('--expect', [...new Set([...expect.toUpperCase().split(/[,\s]+/).filter(Boolean), ...BG_WORDS])].join(','));
    let cropNote = '';
    if (box) { // analyze just the watched item (plus a margin), in video pixels
      const vs = await new Promise(res => execFile('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', file], (e, o) => res((o || '').trim().split(',').map(Number))));
      if (vs.length === 2 && vs[0]) {
        const [W, H] = vs, m = 0.01;
        const c = [Math.max(0, box[0] - m) * W, Math.max(0, box[1] - m) * H, Math.min(1, box[2] + m) * W, Math.min(1, box[3] + m) * H].map(Math.round);
        margs.push('--crop', ...c.map(String), '--regions', '1');
        cropNote = ` Analysis is cropped to the watched item (video px ${c.join(',')}).`;
      }
    }
    const r = await new Promise(res => execFile('python3', margs, { cwd: ROOT, timeout: 120000, maxBuffer: 8 << 20 },
      (e, out, se) => res((out || '') + (e ? '\n(motion.py error: ' + (se || e.message).slice(-400) + ')' : ''))));
    const imgs = ['regions.png', 'sheet.png'].map(f => path.join(outDir, f)).filter(f => fs.existsSync(f));
    for (const f of imgs) S.shots[f] = { bounds: { ...d.bounds }, size: nativeImage.createFromPath(f).getSize() };
    this.batch = this.batch || [];
    this.batch.push({ file, secs, note, cropNote, report: r.trim(), imgs: box ? [] : imgs, box, unit, expect });
    // Several clips in a row (one per eye) are analyzed in ONE turn: wait briefly for the next recording to start.
    clearTimeout(this.batchTimer);
    this.batchWait = 0;
    this.batchTimer = setTimeout(() => this.flush(), 6000);
  },
  async flush() {
    if (this.proc || !this.batch?.length) return;
    // More record steps still pending: the player is moving to the next item. Wait (up to ~30 s) before analyzing.
    if (nextRecordStep() >= 0 && (this.batchWait = (this.batchWait || 0) + 1) <= 6) { this.batchTimer = setTimeout(() => this.flush(), 5000); return; }
    const clips = this.batch; this.batch = [];
    while (busy()) await sleep(500); // let a running turn finish first
    const one = c => `CLIP ${path.basename(c.file)}: recorded ${c.secs}s${c.note ? ` for step "${c.note}"` : ''}.${c.box ? ` Watched item box (screen fractions): ${c.box.map(v => v.toFixed(3)).join(',')}.` : ''}\n` +
      `Motion analysis (python3 tools/motion.py${c.unit ? ' --unit ' + c.unit : ''}${c.expect ? ' --expect ' + c.expect : ''}):${c.cropNote}\n${c.report}`;
    // One line per clip up front, so the agent can decide without reading every report.
    // Batch assignment across all clips, per polarity; keep the cheaper polarity.
    let assignment = null;
    for (const pol of ['dark', 'bright']) {
      const all = clips.map(c => {
        const m = c.report.match(new RegExp(`EXPECT_COSTS ${pol}: ([^\\n]*)`));
        return m ? Object.fromEntries(m[1].split(',').map(kv => { const [w, v] = kv.split('='); return [w, Number(v)]; })) : null;
      });
      if (all.some(r => !r)) continue;
      const targets = new Set(clips.flatMap(c => (c.expect || '').toUpperCase().split(/[,\s]+/).filter(Boolean)));
      const rows = all.map(r => Object.fromEntries(Object.entries(r).filter(([w]) => targets.has(w))));
      // decoy evidence: only 4+ letter background words (short ones fit inside anything), and they must win by a margin
      const skip = all.map(r => Math.min(...Object.entries(r).filter(([w]) => !targets.has(w) && w.length >= 4).map(([, v]) => v + 0.08), 9));
      const a = assignWords(rows, 0.32, skip);
      // for unassigned clips, the closest word outside the expect list (so a missing candidate can't hide)
      const other = all.map(r => Object.entries(r).filter(([w]) => !targets.has(w) && w.length >= 4).sort((x, y) => x[1] - y[1])[0] || null);
      if (a && (!assignment || a.total < assignment.total)) assignment = { ...a, pol, other };
    }
    let clean = true; const owners = new Set();
    const summary = clips.map((c, i) => {
      const exp = (c.report.match(/EXPECTED-WORD MATCH[^:]*: ([^\n]*)/) || [])[1] || '';
      const best = (c.report.match(/BEST MORSE READING: (\S[^\[]*)/) || [])[1] || '';
      const top = exp.split(';')[0].trim();
      const mm = top.match(/^(\S+) ([\d.]+)/);
      if (c.expect) { if (!mm || Number(mm[2]) > 0.15) { /* ambiguous or decoy: fine unless nothing matches */ } else if (owners.has(mm[1])) clean = false; else owners.add(mm[1]); }
      return `${i + 1}. ${c.note || path.basename(c.file)} → ${top ? 'match ' + top : 'no expected match'}${best ? ` · reading ${best.trim()}` : ''}`;
    }).join('\n');
    let assignText = '', assignOK = false;
    if (assignment) {
      const picked = assignment.pick.filter(Boolean);
      assignText = `BATCH ASSIGNMENT (${assignment.pol === 'dark' ? 'blinks = closures' : 'blinks = flashes'} for all clips; each word used once; — = decoy or unclear):\n` +
        clips.map((c, i) => {
          const p = assignment.pick[i], o = assignment.other?.[i];
          const unl = !p && o && o[1] <= 0.08 ? ` (reads ${o[0]} ${o[1].toFixed(2)}, which is NOT in your expect list: check whether the clue could mean it)` : !p && o ? ` (closest other word: ${o[0]} ${o[1].toFixed(2)})` : '';
          return `${i + 1}. ${c.note || path.basename(c.file)} → ${p ? `${p.word} (${p.cost.toFixed(2)})` : '—' + unl}`;
        }).join('\n') + '\n' +
        'This is usually the answer: consistent polarity + distinct words is much stronger than any single reading. ' +
        'Verified lane: only check items that are unassigned or cost > 0.2 (at most 3 tool calls), then commit.\n';
      const costs = picked.map(p => p.cost);
      assignOK = picked.length > 0 && Math.max(...costs) <= 0.3 && costs.reduce((a, b) => a + b, 0) / costs.length <= 0.2;
    }
    agentTurn({
      text: `CLIPS: the player recorded ${clips.length} clip${clips.length > 1 ? 's' : ''} (the cursor is visible in each).\n` + assignText +
        `SUMMARY (one line per clip; match cost = edits per symbol, ≤ 0.15 is solid):\n${summary}\n` +
        'If every item you need has a solid, distinct match, answer and give the next steps now, without re-running tools. ' +
        'Only dig into the full reports below for items that are ambiguous.\n\n' + clips.map(one).join('\n\n') + '\n\n' +
        'Readings: trust EXPECTED-WORD MATCH (cost ≤ 0.15) when present, then BEST MORSE READING; the polarity (flash vs blink) that matched is shown. ' +
        'If a reading is ambiguous, re-run motion.py on that clip (with --unit/--expect/--window) or ask for that one item again.\n' +
        'Plots (signal_N.png) show whether a reading is clean. Region boxes in cropped analyses are relative to the crop, not the display.',
      images: clips.flatMap(c => c.imgs).slice(0, 4),
      // a confident batch assignment: the quick lane may act on it right away (the verified lane still checks)
      trustQuick: assignOK,
    });
  },
};

// ---------- window ----------
function createWindow() {
  const wa = screen.getPrimaryDisplay().workArea;
  win = new BrowserWindow({
    width: 420, height: 700, x: wa.x + wa.width - 440, y: wa.y + 20, minWidth: 320, minHeight: 64,
    frame: false, transparent: true, vibrancy: 'hud', visualEffectState: 'active', backgroundColor: '#00000000',
    alwaysOnTop: true, type: 'panel', skipTaskbar: true, fullscreenable: false, hasShadow: true,
    webPreferences: { preload: path.join(HERE, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (!process.env.SIDEKICK_VISIBLE_IN_SHOTS) win.setContentProtection(true); // hide the overlay from screen shares/recordings where macOS honours it
  win.loadFile(path.join(HERE, 'index.html'));
  win.webContents.on('console-message', (e) => { if (e.level === 'error' || e.level === 'warning') console.log('[ui]', e.message); });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

let ghost = false;
function toggleVisible() { if (win.isVisible()) win.hide(); else { win.showInactive(); } }
function toggleGhost() {
  ghost = !ghost;
  win.setIgnoreMouseEvents(ghost, { forward: true });
  win.setOpacity(ghost ? 0.55 : 1);
  send('ghost', ghost);
}

async function snapAndAsk(mode = 'full', text) {
  if (!win.isVisible()) win.showInactive();
  const shot = await capture(mode);
  if (!shot) return;
  send('user-msg', { text: text || '', thumbs: [shot.thumb] });
  agentTurn({ text, images: [shot.path] });
}

function registerShortcuts() {
  const keys = {
    'Control+Alt+Space': toggleVisible,
    'Control+Alt+S': () => snapAndAsk('full'),
    'Control+Alt+A': () => snapAndAsk('area', 'Look at this area closely.'),
    'Control+Alt+H': () => { send('user-msg', { text: 'Next hint' }); agentTurn({ text: 'Next hint: one step further than before.' }); },
    'Control+Alt+G': toggleGhost,
    'Control+Alt+R': () => { // keep the pointer on the item: records the next pending record step, else a plain clip
      if (!win.isVisible()) win.showInactive();
      const i = rec.proc ? -1 : nextRecordStep();
      if (i >= 0) recordStep(i); else rec.toggle();
    },
    'Control+Alt+W': () => watch.toggle(),
    'Control+Alt+F': () => watch.toggle(),
  };
  for (const [k, fn] of Object.entries(keys)) if (!globalShortcut.register(k, fn)) console.warn('shortcut taken:', k);
}

function createTray() {
  tray = new Tray(nativeImage.createEmpty());
  tray.setTitle('◎');
  tray.setToolTip('Sidekick');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show / hide   ⌃⌥Space', click: toggleVisible },
    { label: 'Watch my screen   ⌃⌥W', click: () => watch.toggle() },
    { label: 'Record a clip   ⌃⌥R', click: () => rec.toggle() },
    { label: 'See-through (click-through)   ⌃⌥G', click: toggleGhost },
    { label: 'New puzzle', click: newSession },
    { label: 'Open session folder', click: () => S.dir && shell.openPath(S.dir) },
    { type: 'separator' },
    { label: 'Quit Sidekick', role: 'quit' },
  ]));
}

// ---------- IPC ----------
ipcMain.handle('init', () => ({ prefs, rounds: ROUNDS, started: S.started, root: ROOT }));
ipcMain.handle('set-prefs', (_, p) => {
  const { follow: f, ...rest } = p;
  Object.assign(prefs, rest);
  if (f !== undefined && f !== watch.on) watch.toggle();
  return prefs;
});
ipcMain.handle('capture', (_, mode) => capture(mode));
ipcMain.handle('record', (_, note, opts) => rec.toggle(note, opts));
ipcMain.handle('save-image', (_, dataUrl) => saveImageData(dataUrl));
ipcMain.handle('ask', (_, msg) => agentTurn(msg));
ipcMain.handle('command', (_, line) => runCommand(line));
ipcMain.handle('stop', () => stopAll());
ipcMain.handle('new-session', () => newSession());
ipcMain.handle('open-folder', () => S.dir && shell.openPath(S.dir));
ipcMain.handle('open-permissions', () => shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'));
ipcMain.handle('copy', (_, t) => clipboard.writeText(t));
ipcMain.handle('window', (_, action, arg) => {
  if (action === 'hide') win.hide();
  if (action === 'ghost') toggleGhost();
  if (action === 'opacity') win.setOpacity(arg);
  if (action === 'height') { const b = win.getBounds(); win.setBounds({ ...b, height: arg }, true); }
  if (action === 'focus') win.focus();
});

app.whenReady().then(() => {
  loginPath();
  ensureOcr();
  warmUp(); // open both lane sessions now, so the first look doesn't pay the cold start
  if (process.platform === 'darwin') app.dock.hide(); // lets the panel float over full-screen apps
  createWindow();
  if (SOURCE) { // harness: keep painting (for UI snapshots) but invisible and click-through, so the real screen is untouched
    win.setOpacity(0); win.setIgnoreMouseEvents(true); win.setOpacity = () => {}; win.setIgnoreMouseEvents = () => {};
  }
  else { createTray(); registerShortcuts(); }
});
app.on('will-quit', () => { globalShortcut.unregisterAll(); stopAll(); rec.stop(); clearCallouts(); });
app.on('window-all-closed', () => app.quit());

module.exports = { commandArgs, runCommand, agentTurn, buildSystemPrompt, S, prefs }; // for the headless test
