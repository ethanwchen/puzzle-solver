#!/usr/bin/env python3
"""Pasteboard: paste a challenge screenshot, get a structured answer. Local only (127.0.0.1), stdlib only.

  python3 tools/pasteboard/server.py            then open http://127.0.0.1:8765  (or double-click solve.command)

Each Solve creates challenges/live-<timestamp>/ (images + notes.md) and runs headless Claude Code (`claude -p`) in the
repo root, so it gets CLAUDE.md and every tool in tools/.
  Fast      1 agent            (~30-60s)
  Verified  3 agents, different lenses, answers compared by canonical form (~45-90s)
It never touches the contest site: you read the answer and submit it yourself.
"""
import base64
import datetime as dt
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PORT = 8765
TIMEOUT_S = 300
JOBS = {}

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "exactly what to type/submit; 'PAGE N; PHRASE' for scan-then-type games"},
        "canonical": {"type": "string", "description": "minimal comparison key: essential tokens only, uppercase"},
        "how_to_enter": {"type": "string"},
        "next_screen": {"type": "string", "description": "prediction for the next screen, or empty"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "check_yourself": {"type": "boolean", "description": "true if anything is unexplained or uncertain"},
        "reasoning": {"type": "string", "description": "3-6 short steps"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "canonical", "how_to_enter", "confidence", "check_yourself", "reasoning", "citations"],
}

LENSES = {
    "literal": "LITERAL: identify the exact scene/fact referenced and answer precisely from the text.",
    "mechanics": "MECHANICS: assume a hidden encoding (book cipher, counted coordinates, mask, substitution, acrostic); test with the tools.",
    "lateral": "LATERAL/VISUAL: focus on visual structure, layout, counts, UI controls; what does each element DO?",
}


def load_patterns():
    """Pull the learned PATTERNS list out of solve-fast.js so the app always uses the current policy."""
    src = (ROOT / ".claude/workflows/solve-fast.js").read_text()
    start = src.index("const PATTERNS = [")
    end = src.index("\n]\n", start) + 2
    js = src[start:end] + "\nconsole.log(JSON.stringify(PATTERNS.map(p => p.text)))"
    try:
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=10).stdout
        return json.loads(out)
    except Exception:
        return []


ROUND_PAGES = {"R3": "249-288", "R4": "289-449", "any": None}


def prompt_for(job_dir, lens, rnd="R3"):
    patterns = "\n".join(f"- {p}" for p in load_patterns())
    return f"""You are solving a LIVE, TIMED puzzle-hunt challenge against a source text (the "corpus"). One submission only: be fast AND right.
LENS: {LENSES[lens]}

1. Open every image and notes file in {job_dir} (Read tool). Transcribe what the screen shows and asks.
2. FIRST run: python3 tools/corpus.py probe "<all screen text>". Then only the tools you need (CLAUDE.md lists them:
   corpus.py search/decode/page/grille/unmask/layout, tools/solvers.py, tools/bars.py, tools/zoom.py).
   {f"Current round's book part first: python3 tools/corpus.py --pages {ROUND_PAGES[rnd]} ... ({rnd}); widen if needed." if ROUND_PAGES.get(rnd) else "Search the whole book."}
3. Stop as soon as the evidence is solid. The answer is the LAST product of the chain, never an input.
   Scan-then-type games: answer "PAGE N; PHRASE". Set check_yourself=true if anything on screen is unexplained.

LEARNED PRIORS (from past rounds and training):
{patterns}

Context: research/ledger.md lists every past answer, fragment and hint (later games may reuse them).
Never open .grading/ or other challenges folders. Return the structured result."""


def run_agent(job, lens):
    rec = job["runs"][lens]
    rec["status"] = "running"
    claude = shutil.which("claude") or "claude"
    cmd = [
        claude, "-p", prompt_for(job["dir"], lens, job.get("round", "R3")),
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
        "--allowedTools", "Read", "Glob", "Grep", "Bash(python3:*)", "Bash(ls:*)", "Bash(cat:*)",
    ]
    if job.get("model"):
        cmd += ["--model", job["model"]]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S)
        rec["seconds"] = round(time.time() - t0, 1)
        data = json.loads(p.stdout or "{}")
        result = data.get("structured_output")
        if result is None:
            txt = data.get("result", "")
            m = re.search(r"\{.*\}", txt, re.S)
            result = json.loads(m.group(0)) if m else {"answer": txt.strip()[:300], "confidence": 0, "check_yourself": True}
        rec["result"] = result
        rec["status"] = "done"
    except subprocess.TimeoutExpired:
        rec["status"], rec["error"] = "timeout", f"no answer after {TIMEOUT_S}s"
    except Exception as e:  # surface CLI/auth errors in the UI
        rec["status"], rec["error"] = "error", str(e)[:400]
    aggregate(job)


def canon(r):
    t = (r.get("canonical") or r.get("answer") or "")
    m = re.search(r"(-?\d{1,3}\.\d+)[^\d-]+(-?\d{1,3}\.\d+)", t)
    if m:
        return f"PIN{float(m.group(1)):.2f},{float(m.group(2)):.2f}"
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def aggregate(job):
    done = [r for r in job["runs"].values() if r.get("result")]
    groups = {}
    for r in done:
        groups.setdefault(canon(r["result"]), []).append(r)
    if not groups:
        return
    best_key = max(groups, key=lambda k: (len(groups[k]), sum(x["result"].get("confidence", 0) for x in groups[k])))
    best = groups[best_key]
    top = max(best, key=lambda x: x["result"].get("confidence", 0))["result"]
    total = len(job["runs"])
    job["summary"] = {
        **top,
        "agreement": f"{len(best)}/{len(done)} answered" + (f" ({total - len(done)} still running)" if len(done) < total else ""),
        "check_yourself": bool(top.get("check_yourself")) or len(groups) > 1,
        "alternatives": [g[0]["result"].get("answer") for k, g in groups.items() if k != best_key],
    }
    if all(r["status"] in ("done", "error", "timeout") for r in job["runs"].values()):
        job["finished"] = round(time.time() - job["t0"], 1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path.startswith("/status/"):
            job = JOBS.get(self.path.split("/")[-1])
            if not job:
                return self._send(404, {"error": "unknown job"})
            view = {k: v for k, v in job.items() if k not in ("t0",)}
            view["elapsed"] = round(time.time() - job["t0"], 1)
            return self._send(200, view)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/solve":
            return self._send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        images = body.get("images") or []
        if not images:
            return self._send(400, {"error": "paste at least one image"})
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        job_dir = ROOT / "challenges" / f"live-{stamp}"
        job_dir.mkdir(parents=True, exist_ok=True)
        for i, url in enumerate(images, 1):
            raw = base64.b64decode(url.split(",", 1)[1])
            (job_dir / f"screen{i}.png").write_bytes(raw)
        if body.get("notes", "").strip():
            (job_dir / "notes.md").write_text("Notes / hints from the player:\n" + body["notes"].strip() + "\n")
        lenses = ["mechanics"] if body.get("mode") == "fast" else list(LENSES)
        jid = uuid.uuid4().hex[:8]
        job = {"id": jid, "dir": str(job_dir), "t0": time.time(), "mode": body.get("mode", "fast"),
               "model": body.get("model") or None, "round": body.get("round", "R3"), "runs": {l: {"lens": l, "status": "queued"} for l in lenses},
               "summary": None, "finished": None}
        JOBS[jid] = job
        for l in lenses:
            threading.Thread(target=run_agent, args=(job, l), daemon=True).start()
        self._send(200, {"id": jid, "dir": str(job_dir.relative_to(ROOT))})


if __name__ == "__main__":
    if not shutil.which("claude"):
        print("warning: `claude` CLI not found on PATH; start this from a shell where `claude` works")
    print(f"Pasteboard running: http://127.0.0.1:{PORT}   (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
