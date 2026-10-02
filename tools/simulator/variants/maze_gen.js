// Shared maze generator for the G9 "tunnels" variants ("walk the space between the walls", fragment 8).
// Extracted from game9m.html so game9z (pan/zoom) and game9t (plate artwork) build the same boards.
// game9m.html keeps its own inline copy on purpose: it is the validated reference (eval/maze_matrix.js, 24/24).
//
//   makeMaze({ rows, cols, exits, lit, loops, startMode }) -> {
//     open[r][c]: Set of open sides ('U','D','L','R'), start:[r,c] (0-based), route:[[r,c]...] (start -> exit),
//     routeSet: Set("r,c"), exitC, decoys:[c...], reachable:[c...], lit: Set("r,c"), truth(): export object }
import { R, pick, shuffle } from './common.js';

export const D = { U: [-1, 0], D: [1, 0], L: [0, -1], R: [0, 1] };
export const OPP = { U: 'D', D: 'U', L: 'R', R: 'L' };

export function makeMaze({ rows, cols, exits = 1, lit = false, loops = 0, startMode = 'bottom', litMax = 14 }) {
  const NR = rows, NC = cols;
  const id = (r, c) => r * NC + c, inb = (r, c) => r >= 0 && r < NR && c >= 0 && c < NC;
  const open = Array.from({ length: NR }, () => Array.from({ length: NC }, () => new Set()));
  const link = (r, c, s) => { const [dr, dc] = D[s]; open[r][c].add(s); if (inb(r + dr, c + dc)) open[r + dr][c + dc].add(OPP[s]); };
  const unlink = (r, c, s) => { const [dr, dc] = D[s]; open[r][c].delete(s); if (inb(r + dr, c + dc)) open[r + dr][c + dc].delete(OPP[s]); };

  // perfect maze (randomized DFS)
  { const seen = new Set([0]); const st = [[0, 0]];
    while (st.length) { const [r, c] = st[st.length - 1];
      const nb = shuffle(Object.keys(D)).filter(s => { const [dr, dc] = D[s]; return inb(r + dr, c + dc) && !seen.has(id(r + dr, c + dc)); });
      if (!nb.length) { st.pop(); continue; }
      const s = nb[0], [dr, dc] = D[s]; link(r, c, s); seen.add(id(r + dr, c + dc)); st.push([r + dr, c + dc]); } }

  const neighbours = (r, c) => [...open[r][c]].map(s => [r + D[s][0], c + D[s][1]]).filter(([a, b]) => inb(a, b));
  function bfs(sr, sc) { const prev = new Map([[id(sr, sc), null]]); const q = [[sr, sc]];
    while (q.length) { const [r, c] = q.shift(); for (const [a, b] of neighbours(r, c)) if (!prev.has(id(a, b))) { prev.set(id(a, b), [r, c]); q.push([a, b]); } }
    return prev; }
  const pathTo = (prev, r, c) => { const p = []; let cur = [r, c]; while (cur) { p.push(cur); cur = prev.get(id(cur[0], cur[1])); } return p.reverse(); };

  const start = startMode === 'any' ? [Math.floor(NR / 2 + R() * NR / 2), Math.floor(R() * NC)] : [NR - 1, Math.floor(R() * NC)];
  let prev = bfs(...start);
  const topCells = shuffle([...Array(NC).keys()]);
  const exitC = topCells[0];
  const onTrue = new Set(pathTo(prev, 0, exitC).map(([r, c]) => id(r, c)));
  const NEX = Math.min(NC, exits);
  const decoys = topCells.slice(1).filter(c => !onTrue.has(id(0, c))).slice(0, NEX - 1); // a decoy exit can't sit on the route
  for (let pass = 0; pass < 12; pass++) for (const dc of decoys) { // cut start->decoy edges the true path doesn't use
    const pv = bfs(...start); if (!pv.has(id(0, dc))) continue;
    const p = pathTo(pv, 0, dc);
    for (let i = p.length - 1; i > 0; i--) { const [a, b] = p[i], [x, y] = p[i - 1];
      if (onTrue.has(id(a, b)) && onTrue.has(id(x, y))) continue;
      const s = Object.keys(D).find(k => D[k][0] === a - x && D[k][1] === b - y); unlink(x, y, s); break; }
  }
  // loops: extra openings, kept only while the shortest way out stays unique and no decoy becomes reachable
  function nShortest(sr, sc, tr, tc) { const dist = new Map([[id(sr, sc), 0]]), cnt = new Map([[id(sr, sc), 1]]); const q = [[sr, sc]];
    while (q.length) { const [r, c] = q.shift(); const d = dist.get(id(r, c));
      for (const [a, b] of neighbours(r, c)) { const k = id(a, b);
        if (!dist.has(k)) { dist.set(k, d + 1); cnt.set(k, cnt.get(id(r, c))); q.push([a, b]); }
        else if (dist.get(k) === d + 1) cnt.set(k, cnt.get(k) + cnt.get(id(r, c))); } }
    return cnt.get(id(tr, tc)) || 0; }
  for (let k = 0, added = 0; k < 400 && added < loops * 2; k++) {
    const r = Math.floor(R() * NR), c = Math.floor(R() * NC), s = pick(['R', 'D']); const [dr, dc] = D[s];
    if (!inb(r + dr, c + dc) || open[r][c].has(s)) continue;
    link(r, c, s);
    const pv = bfs(...start);
    if (nShortest(...start, 0, exitC) !== 1 || decoys.some(d => pv.has(id(0, d)))) unlink(r, c, s); else added++;
  }
  open[0][exitC].add('U'); for (const dc of decoys) open[0][dc].add('U');
  prev = bfs(...start);
  const route = pathTo(prev, 0, exitC);
  const routeSet = new Set(route.map(([r, c]) => `${r},${c}`));
  const reachable = [...Array(NC).keys()].filter(c => open[0][c].has('U') && prev.has(id(0, c)));
  if (reachable.length !== 1) console.warn('exits reachable:', reachable);

  // lit decoy corridor: a dead end off the true route, reached from the start ("they light it for you")
  const litSet = new Set();
  if (lit) {
    const cands = [];
    for (const [k] of prev) { const r = Math.floor(k / NC), c = k % NC; if (routeSet.has(`${r},${c}`)) continue;
      const p = pathTo(prev, r, c).filter(([a, b]) => !routeSet.has(`${a},${b}`));
      if (p.length >= 3 && p.length <= Math.max(4, Math.min(litMax, route.length))) cands.push(p); }
    cands.sort((x, y) => y.length - x.length || x[x.length - 1][0] - y[y.length - 1][0]);
    const best = cands[Math.floor(R() * Math.min(3, cands.length))];
    if (best) for (const [r, c] of best) litSet.add(`${r},${c}`);
  }

  return { rows: NR, cols: NC, open, start, route, routeSet, exitC, decoys, reachable, lit: litSet,
    truth: extra => ({ rows: NR, cols: NC, start: [start[0] + 1, start[1] + 1], route: route.map(([r, c]) => [r + 1, c + 1]),
      exits: [exitC + 1, ...decoys.map(c => c + 1)], reachable: reachable.map(c => c + 1),
      lit: [...litSet].map(k => k.split(',').map(x => +x + 1)),
      open: open.map(row => row.map(s => [...s].sort().join('')).join(' ')), ...extra }) };
}
