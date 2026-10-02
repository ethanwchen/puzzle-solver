// Generic scripted player for the Sidekick test harness (see README.md).
// It knows nothing about the game: it turns on Watch mode (level = Answer), then does exactly what the sidekick's
// <step>s say (hover/click/drag/type/scroll/record) on a headless page, asks "what next?" when the sidekick goes
// quiet, and stops when the page shows the --until text. SOURCE/latest.png is kept fresh as the sidekick's "screen".
//
//   node drive.js URL SOURCE_DIR CDP_PORT [--until REGEX] [--max SECONDS] [--intro SECONDS]
const { chromium } = require('playwright-core');
const fs = require('fs'), os = require('os'), path = require('path'), { execFileSync } = require('child_process');

const argv = process.argv.slice(2);
const [URL, SRC, PORT] = argv;
const opt = (k, d) => { const i = argv.indexOf(k); return i > 0 ? argv[i + 1] : d; };
const UNTIL = new RegExp(opt('--until', 'sample accuracy|TRANSMISSION\\s+COMPLETE'), 'i');
const MAX_S = Number(opt('--max', 900)), INTRO_S = Number(opt('--intro', 4));
const [VW, VH] = opt('--view', '1280x800').split('x').map(Number); // page viewport = the sidekick's "screen"
const T0 = Date.now(), secs = () => ((Date.now() - T0) / 1000).toFixed(1);
const log = m => { const l = `[${secs()}s] ${m}`; console.log(l); fs.appendFileSync(path.join(SRC, 'driver.log'), l + '\n'); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

let ws, id = 0; const pend = {};
async function cdp() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
  ws = new WebSocket(list.find(p => p.type === 'page' && p.title === 'Sidekick').webSocketDebuggerUrl);
  ws.onmessage = e => { const m = JSON.parse(e.data); if (pend[m.id]) { pend[m.id](m.result); delete pend[m.id]; } };
  await new Promise(r => ws.onopen = r);
}
// every call into the panel times out (a hung call used to freeze a run for an hour)
const ev = expr => Promise.race([
  new Promise(r => { pend[++id] = r; ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression: expr, awaitPromise: true, returnByValue: true } })); }).then(r => r.result?.value),
  new Promise(r => setTimeout(() => r(undefined), 20000)),
]);
const panel = async () => JSON.parse(await ev(`JSON.stringify({ busy, steps: currentSteps, a: lastAnswer && { t: lastAnswer.t, lane: lastAnswer.lane } })`));

function chromePath() {
  if (process.env.CHROME) return process.env.CHROME;
  const cache = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
  const exe = shell && path.join(cache, shell, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell');
  return exe && fs.existsSync(exe) ? exe : undefined;
}
const REAL = argv.includes('--real'); // headed browser on the real screen; the sidekick watches the actual display
let DISPLAY = null, ORIGIN = [0, 0];  // display size in points; page (0,0) in screen points
const center = b => REAL
  ? [(b[0] + b[2]) / 2 * DISPLAY[0] - ORIGIN[0], (b[1] + b[3]) / 2 * DISPLAY[1] - ORIGIN[1]]
  : [(b[0] + b[2]) / 2 * VW, (b[1] + b[3]) / 2 * VH];

(async () => {
  // hard watchdog: whatever hangs, the run ends and is recorded
  setTimeout(() => {
    log(`WATCHDOG: no finish after ${MAX_S + 120}s, aborting`);
    try { fs.appendFileSync(path.join(__dirname, 'results.tsv'), [new Date().toISOString(), URL, 'WATCHDOG ABORT', '', MAX_S + 120].join('\t') + '\n'); } catch {}
    process.exit(2);
  }, (MAX_S + 120) * 1000).unref();
  await cdp();
  let b, p;
  if (REAL) {
    const exe = path.join(os.homedir(), 'Library/Caches/ms-playwright', fs.readdirSync(path.join(os.homedir(), 'Library/Caches/ms-playwright')).filter(d => /^chromium-\d+$/.test(d)).sort().pop(), 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing');
    b = await chromium.launch({ executablePath: exe, headless: false, args: ['--window-position=0,30', `--window-size=${VW},${VH + 90}`] });
    p = await (await b.newContext({ viewport: { width: VW, height: VH } })).newPage();
    const bounds = execFileSync('osascript', ['-e', 'tell application "Finder" to get bounds of window of desktop']).toString().split(',').map(Number);
    DISPLAY = [bounds[2], bounds[3]];
  } else {
    b = await chromium.launch({ executablePath: chromePath() });
    p = await (await b.newContext({ viewport: { width: VW, height: VH } })).newPage();
  }
  let frames = !REAL, recording = false;
  (async () => { while (frames) { if (!recording) { try { await p.screenshot({ path: SRC + '/tmp.png' }); fs.renameSync(SRC + '/tmp.png', SRC + '/latest.png'); } catch {} } await sleep(600); } })();

  // Clip requests from the sidekick (a record step): screencast the page, then encode a constant-rate mp4.
  async function serveRecording() {
    const reqF = path.join(SRC, 'rec_request.json');
    if (!fs.existsSync(reqF)) return false;
    const req = JSON.parse(fs.readFileSync(reqF, 'utf8')); fs.unlinkSync(reqF);
    recording = true;
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'clip-'));
    const client = await p.context().newCDPSession(p);
    const shots = [];
    client.on('Page.screencastFrame', async f => { shots.push({ data: f.data, t: f.metadata.timestamp }); client.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {}); });
    const tStart = Date.now() / 1000;
    await client.send('Page.startScreencast', { format: 'jpeg', quality: 85, everyNthFrame: 1 });
    await sleep(req.seconds * 1000);
    await client.send('Page.stopScreencast');
    const tEnd = Date.now() / 1000;
    recording = false;
    let list = '';
    shots.forEach((s, i) => {
      const f = path.join(dir, `f${String(i).padStart(5, '0')}.jpg`); fs.writeFileSync(f, Buffer.from(s.data, 'base64'));
      const next = i + 1 < shots.length ? shots[i + 1].t : tEnd;
      list += `file '${f}'\nduration ${Math.max(0.001, next - s.t).toFixed(4)}\n`;
    });
    if (shots.length) list += `file '${path.join(dir, `f${String(shots.length - 1).padStart(5, '0')}.jpg`)}'\n`;
    fs.writeFileSync(path.join(dir, 'list.txt'), list);
    execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'list.txt'),
      '-vf', 'fps=25,scale=1280:-2', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', req.out]);
    fs.writeFileSync(req.out + '.done', '');
    log(`recorded ${req.seconds}s clip (${shots.length} frames) → ${path.basename(req.out)}`);
    return true;
  }

  async function doStep(st, i) {
    const at = st.at && center(st.at);
    if (st.do === 'hover' || st.do === 'record') {
      if (at) await p.mouse.move(at[0], at[1], { steps: 6 });
      if (st.record || st.do === 'record') {
        await ev(`sk.stepRecord(${i}); 1`); // marks the step done in the sidekick
        const t = Date.now(); while (!(await serveRecording()) && Date.now() - t < 10000) await sleep(200);
        const t2 = Date.now(); while (await ev(`document.getElementById('rec').classList.contains('on')`) && Date.now() - t2 < 20000) await sleep(200);
      } else await sleep(1500);
    } else if (st.do === 'click' && at) { await p.mouse.click(at[0], at[1]); await sleep(500); }
    else if (st.do === 'drag' && at && st.to) {
      const to = center(st.to);
      await p.mouse.move(at[0], at[1]); await p.mouse.down(); await p.mouse.move(to[0], to[1], { steps: 18 }); await p.mouse.up(); await sleep(600);
    } else if (st.do === 'type') {
      if (at) { await p.mouse.click(at[0], at[1]); await sleep(150); }
      for (const ch of st.text || '') { await p.keyboard.press(ch === ' ' ? 'Space' : ch); await sleep(80); }
      await sleep(300);
    } else if (st.do === 'key') { for (const k of (st.text || '').split(/\s+/).filter(Boolean)) { await p.keyboard.press(k); await sleep(120); } await sleep(300); }
    else if (st.do === 'scroll') { await p.mouse.wheel(0, st.dy || 400); await sleep(800); }
    else { // look: the player presses ⌃⌥S (a fresh screenshot goes to the sidekick)
      await sleep(800);
      await ev(`(async () => { const s = await sk.capture('full'); if (s) { attachments.push(s); submit('Here is the screen now.'); } return 1; })()`);
      await sleep(1500);
    }
    if (!(st.record || st.do === 'record')) await ev(`sk.stepDone(${i}, true); 1`);
    log(`  did step ${i + 1}: ${st.do}${st.text ? ' "' + st.text + '"' : ''} — ${st.say}`);
  }

  await p.goto(URL, { waitUntil: 'networkidle' });
  log('page opened: ' + URL);
  if (REAL) {
    await p.bringToFront();
    ORIGIN = await p.evaluate(() => [window.screenX + (window.outerWidth - window.innerWidth) / 2, window.screenY + (window.outerHeight - window.innerHeight)]);
    log(`real screen ${DISPLAY.join('x')} · page origin ${ORIGIN.map(Math.round).join(',')}`);
  }
  await sleep(INTRO_S * 1000);
  await ev(`sk.setPrefs({ level: 'solve' }).then(x => { prefs = x; syncPrefs(); }); setPref({ follow: true }); 1`);
  log('watch mode ON (level = Answer)');

  let doneTurn = null, lastProgress = Date.now(), asked = 0, firstSteps = null, lastSig = '', sigAt = 0;
  while (Date.now() - T0 < MAX_S * 1000) {
    await sleep(1000);
    const body = await p.innerText('body').catch(() => '');
    if (UNTIL.test(body) || /\/board/.test(p.url())) {
      const m = body.replace(/TRANSMISSION\s+COMPLETE/i, "TRANSMISSION COMPLETE").match(/[^\n]*(sample accuracy|TRANSMISSION COMPLETE|CORRECT)[^\n]*/i);
      log(`FINISHED: ${m ? m[0].trim() : p.url()}`); break;
    }
    let s;
    try { s = await panel(); } catch { continue; }
    if (!s) continue;
    // A person acts on steps as soon as they're on screen, even while the sidekick keeps verifying; just let a new
    // list settle for 2 s first (it may still be streaming in).
    const sig = JSON.stringify((s.steps?.list || []).map(x => [x.do, x.at]));
    if (sig !== lastSig) { lastSig = sig; sigAt = Date.now(); }
    if (s.busy && (!(s.steps?.list || []).some(x => !x.done) || Date.now() - sigAt < 2000)) continue;
    // Like a person with the card in front of them: always do the first unfinished step of the CURRENT list.
    const steps = s.steps?.list || [];
    const i = steps.findIndex(st => !st.done);
    if (i >= 0) {
      if (!firstSteps) firstSteps = secs();
      if (s.steps.turn !== doneTurn) {
        doneTurn = s.steps.turn;
        log(`sidekick gave ${steps.length} step(s) (turn ${doneTurn}, ${steps.filter(x => x.done).length} already done); answer so far: ${s.a ? `"${s.a.t}" (${s.a.lane})` : '—'}`);
      }
      await doStep(steps[i], i);
      lastProgress = Date.now();
      if (i === steps.length - 1) await sleep(2500);
      continue;
    }
    if (Date.now() - lastProgress > 45000) { // quiet: ask like a player would
      asked++; lastProgress = Date.now();
      log(`player asks: what next? (#${asked})`);
      await ev(`submit('What should I do next? Give me the steps.'); 1`);
      if (asked > 6) { log('giving up: sidekick keeps going quiet'); break; }
    }
  }
  log(`time to first steps: ${firstSteps || '—'}s · total ${secs()}s`);
  const fin = fs.readFileSync(path.join(SRC, 'driver.log'), 'utf8').match(/FINISHED: (.*)/);
  fs.appendFileSync(path.join(__dirname, 'results.tsv'),
    [new Date().toISOString(), URL, fin ? fin[1] : 'NOT FINISHED', firstSteps || '', secs()].join('\t') + '\n');
  frames = false;
  await ev(`setPref({ follow: false }); 1`);
  await sleep(500);
  await b.close(); ws.close();
})();
