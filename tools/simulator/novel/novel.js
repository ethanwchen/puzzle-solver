// Shared scaffold for the "novel" practice puzzles: one or more answer fields, CONTINUE → YES → a score.
import { sha, $, frame, onSubmit } from '../variants/common.js';
export async function puzzle({ code, title, clue, hint, body, fields, answers }) {
  frame({ code, title, clue, hint });
  document.getElementById('stage').innerHTML = body + fields.map((f, i) =>
    `<div style="display:flex;gap:10px;align-items:center"><span style="width:160px;text-align:right;color:#9b8f86;font:13px Arial">${f}</span>
     <input id="f${i}" autocomplete="off" style="width:300px;background:#1a1213;border:1.5px solid var(--tan);color:var(--ink);border-radius:10px;padding:9px 12px;font:700 20px Georgia;letter-spacing:.08em;text-align:center"></div>`).join('');
  const norm = v => v.toUpperCase().replace(/[^A-Z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
  const H = await Promise.all(answers.map(a => sha(norm(a))));
  $('progress').textContent = `${fields.length} ANSWER${fields.length > 1 ? 'S' : ''}`;
  onSubmit(() => fields.every((_, i) => $('f' + i).value.trim()), async () => {
    const ok = await Promise.all(fields.map(async (_, i) => (await sha(norm($('f' + i).value))) === H[i]));
    return { pct: Math.round(100 * ok.filter(Boolean).length / ok.length), notes: ok.map((o, i) => `${o ? '✓' : '✗'} ${fields[i]}`) };
  });
}
