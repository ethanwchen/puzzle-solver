// Shared bits for the variant practice games: seeded RNG, hashing, intro, clue panel, clock, confirm dialog, result.
// Answers are only ever compared as SHA-256 hashes, so neither the player nor the solver can read them from the page.
export const params = new URLSearchParams(location.search);
export const seed = Number(params.get('seed') || 1);
export function rng(s = seed) { // mulberry32
  let a = s >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
export const R = rng();
export const pick = a => a[Math.floor(R() * a.length)];
export function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
export const sha = async s => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)))].map(b => b.toString(16).padStart(2, '0')).join('');
export const $ = id => document.getElementById(id);

export function frame({ code, title, clue, hint }) {
  document.body.insertAdjacentHTML('afterbegin', `
    <div class="badge">OFFLINE EDITION · VARIANT ${seed}</div>
    <div id="intro">${code}: ${title.toUpperCase()}</div>
    <aside id="panel"><div class="kicker">${code} &nbsp;${title.toUpperCase()}</div><h1>${title}</h1><p id="clue">${clue}</p>
      <div class="row"><span id="progress"></span><span id="clock">00:00:00</span></div></aside>
    <div class="hint" id="hint">${hint}</div>
    <button class="pill primary" id="continue">CONTINUE</button>
    <div id="modal"><div class="box"><h2>IS THIS YOUR ANSWER?</h2><p>Save this practice answer?</p><button class="pill" id="yes">YES</button> <button class="pill" id="no">NO</button></div></div>
    <div id="result"></div>`);
  const t0 = Date.now();
  setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); $('clock').textContent = `00:${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }, 1000);
  setTimeout(() => { $('intro').style.opacity = 0; setTimeout(() => $('intro').remove(), 700); }, 2500);
}

// CONTINUE → confirm → score(): Promise<{ pct, notes[] }>
export function onSubmit(ready, score) {
  $('continue').onclick = () => { if (!ready()) { document.body.classList.add('flash'); setTimeout(() => document.body.classList.remove('flash'), 400); return; } $('modal').classList.add('on'); };
  $('no').onclick = () => $('modal').classList.remove('on');
  $('yes').onclick = async () => {
    $('modal').classList.remove('on');
    const r = await score();
    $('result').innerHTML = `<div class="box"><h2>${r.pct}% sample accuracy</h2>${r.notes.map(n => `<p>${n}</p>`).join('')}<button class="pill" onclick="location.reload()">TRY AGAIN</button></div>`;
    $('result').classList.add('on');
  };
}
