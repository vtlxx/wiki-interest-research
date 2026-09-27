"""Run the eval scenarios on Claude Haiku 4.5 in headless Claude Code, scrub and grade the transcripts.

Usage:
  uv run python evals/run_evals.py [--only E1,E3] [--attempts 3] [--parallel 3] [--budget-usd 10]
                                   [--out evals/runs/<date>]
  uv run python evals/run_evals.py --grade-only evals/runs/<date>/manual    # transcripts exported by hand

Every session gets its own temporary project folder with the skill installed by install.sh, no user settings,
plugins or MCP servers, and permission only for the skill's `wir` script, reading files and writing notes.md.
Unscrubbed transcripts stay in <out>/raw/ (git-ignored); only scrubbed copies, grades and SUMMARY.md are
written next to it. A scenario that `continues` another runs in the same session right after it.
"""
from __future__ import annotations

import argparse
import getpass
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))

import grade  # noqa: E402
from grade import Check  # noqa: E402,F401  (re-exported for callers and tests)

MODEL = "claude-haiku-4-5-20251001"
TURN_TIMEOUT_S = 600
ALLOWED_TOOLS = ["Bash(*/scripts/wir *)", "Read", "Glob", "Grep", "Skill",
                 "Edit(./wiki-interest-output/**)", "Write(./wiki-interest-output/**)"]
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
LIMIT_HIT = re.compile(r"usage limit|rate limit|limit reached|overloaded|Failed to authenticate", re.I)


# ---- planning -------------------------------------------------------------------------------
@dataclass
class Session:
    attempt: int
    evals: list[dict]

    @property
    def key(self) -> str:
        return "+".join(e["id"] for e in self.evals) + f"-{self.attempt}"


def plan_sessions(evals: list[dict], attempts: int = 3, only: set[str] | None = None) -> list[Session]:
    """One session per chain (a scenario plus the ones that continue it) and attempt; attempt 1 of every
    chain first, so the shared cache is filled before sessions run in parallel."""
    children: dict[str, list[dict]] = {}
    for e in evals:
        if "continues" in e:
            children.setdefault(e["continues"], []).append(e)

    def chain(e):
        return [e] + [x for child in children.get(e["id"], []) for x in chain(child)]

    chains = [chain(e) for e in evals if "continues" not in e]
    if only:
        chains = [c[:max(i for i, e in enumerate(c) if e["id"] in only) + 1]
                  for c in chains if any(e["id"] in only for e in c)]
    return [Session(a, c) for a in range(1, attempts + 1) for c in chains]


def needs_reply(outputs: list[dict]) -> bool:
    """The turn ended waiting for the user: the tool asked (or needs languages), or nothing was analysed yet."""
    return not any((env.get("files") or {}).get("data") for env in outputs)


# ---- scrubbing ------------------------------------------------------------------------------
@dataclass
class Ctx:
    home: str
    work: list[str] = field(default_factory=list)
    user: str = ""
    host: str = ""
    sessions: list[str] = field(default_factory=list)
    contact: str = ""

    @classmethod
    def current(cls, work=(), sessions=()) -> "Ctx":
        return cls(str(Path.home()), sorted({str(w) for w in work}, key=len, reverse=True), getpass.getuser(),
                   socket.gethostname(), list(sessions), os.environ.get("WIR_CONTACT", ""))


def scrub(text: str, ctx: Ctx) -> str:
    for w in ctx.work:
        text = text.replace(w, "<work>")
    for sid in ctx.sessions:
        text = text.replace(sid, "<session>")
    if ctx.contact:
        text = text.replace(ctx.contact, "<contact>")
    text = EMAIL.sub("<email>", text)
    text = text.replace(ctx.home, "<home>")
    text = UUID.sub("<uuid>", text)
    if ctx.host:
        text = re.sub(re.escape(ctx.host), "<host>", text, flags=re.I)
    if ctx.user:
        text = re.sub(re.escape(ctx.user), "<user>", text, flags=re.I)
    return text


def find_leaks(text: str, ctx: Ctx) -> list[str]:
    low = text.lower()
    found = [marker for marker in ("/Users/", "/home/") if marker in text]
    if EMAIL.search(text):
        found.append("email")
    named = {"home": ctx.home, "user": ctx.user, "host": ctx.host, "contact": ctx.contact}
    found += [name for name, value in named.items() if value and value.lower() in low]
    found += ["work" for w in ctx.work if w in text][:1]
    found += ["session" for s in ctx.sessions if s in text][:1]
    return found


# ---- transcripts ----------------------------------------------------------------------------
def split_turns(events: list[dict], markers: dict[str, str]) -> dict[str, list[dict]]:
    """Cut one session into per-scenario parts at each scenario's first prompt (markers: id -> prompt)."""
    starts, pos = [], 0
    for eid, prompt in markers.items():
        idx = next(i for i in range(pos, len(events))
                   if grade.is_prompt(events[i]) and grade._text(grade._blocks(events[i])).strip() == prompt.strip())
        starts.append((eid, idx))
        pos = idx + 1
    bounds = [idx for _, idx in starts[1:]] + [len(events)]
    return {eid: events[idx:end] for (eid, idx), end in zip(starts, bounds)}


def session_file(sid: str) -> Path | None:
    found = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{sid}.jsonl"))
    return Path(found[0]) if found else None


# ---- results --------------------------------------------------------------------------------
@dataclass
class Result:
    eval_id: str
    attempt: int
    verdict: str
    checks: list
    tool_calls: int = 0
    seconds: float = 0.0
    cost: float = 0.0
    note: str = ""


def summarize(results: list[Result], meta: dict) -> str:
    order = list(dict.fromkeys(r.eval_id for r in results))
    rows = ["| scenario | passed attempts | checks passed | avg tool calls | avg time | avg cost | failed checks |",
            "|---|---|---|---|---|---|---|"]
    valid_all = [r for r in results if r.verdict != "INVALID"]
    for eid in order:
        valid = [r for r in valid_all if r.eval_id == eid]
        if not valid:
            rows.append(f"| {eid} | 0/0 | — | — | — | — | all attempts INVALID |")
            continue
        checks = [c for r in valid for c in r.checks]
        failed: dict[str, int] = {}
        for c in checks:
            if c.status == "FAIL":
                failed[c.name] = failed.get(c.name, 0) + 1
        n = len(valid)
        rows.append(f"| {eid} | {sum(r.verdict == 'PASS' for r in valid)}/{n} | "
                    f"{sum(c.status == 'PASS' for c in checks)}/{len(checks)} | "
                    f"{sum(r.tool_calls for r in valid) / n:.1f} | {sum(r.seconds for r in valid) / n:.0f} s | "
                    f"${sum(r.cost for r in valid) / n:.2f} | "
                    f"{', '.join(f'{k} ×{v}' for k, v in failed.items()) or '—'} |")
    all_checks = [c for r in valid_all for c in r.checks]
    invalid = [f"{r.eval_id}-{r.attempt}" + (f" ({r.note})" if r.note else "") for r in results if r.verdict == "INVALID"]
    lines = [f"# Eval run {meta.get('date', '')}", "",
             f"Model `{meta.get('model', MODEL)}` · Claude Code {meta.get('claude', '?')} · "
             f"{len(results)} scenario attempts", "", *rows, "",
             f"- Scenario attempts passed: {sum(r.verdict == 'PASS' for r in valid_all)}/{len(valid_all)}",
             f"- Checks passed: {sum(c.status == 'PASS' for c in all_checks)}/{len(all_checks)}",
             f"- Total time: {sum(r.seconds for r in results) / 60:.1f} min · "
             f"total cost (API-equivalent): ${sum(r.cost for r in results):.2f}",
             f"- INVALID: {', '.join(invalid) or 'none'}"]
    return "\n".join(lines) + "\n"


# ---- running --------------------------------------------------------------------------------
class Budget:
    def __init__(self, limit: float):
        self.limit, self.spent, self.stop_reason, self.lock = limit, 0.0, "", threading.Lock()

    def add(self, cost: float):
        with self.lock:
            self.spent += cost
            if self.spent > self.limit and not self.stop_reason:
                self.stop_reason = f"budget ${self.limit:.2f} exceeded"

    def stop(self, reason: str):
        with self.lock:
            self.stop_reason = self.stop_reason or reason


def _env(cache: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not (k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_") and k != "CLAUDE_CODE_OAUTH_TOKEN")}
    env.pop("WIR_OUTPUT_DIR", None)
    env["WIR_CACHE_DIR"] = str(cache)
    return env


def claude_turn(text: str, sid: str, first: bool, work: Path, env: dict, max_turn_usd: float) -> dict:
    cmd = ["claude", "-p", text, "--model", MODEL, "--output-format", "json",
           *(["--session-id", sid] if first else ["--resume", sid]),
           "--setting-sources", "project,local", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED_TOOLS, "--max-budget-usd", str(max_turn_usd)]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=TURN_TIMEOUT_S)
        out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        out = {"is_error": True, "result": f"harness: {type(exc).__name__}"}
    out.setdefault("duration_ms", (time.monotonic() - started) * 1000)
    return out


def run_session(s: Session, out: Path, budget: Budget, max_turn_usd: float) -> list[Result]:
    raw = out / "raw"
    work = Path(tempfile.mkdtemp(prefix="wir-eval-")).resolve()
    sid = str(uuid.uuid4())
    subprocess.run([str(SKILL_DIR / "install.sh"), "--project", str(work), "--agents", "claude"],
                   check=True, capture_output=True)
    env = _env(raw / "cache")
    stats = {e["id"]: {"seconds": 0.0, "cost": 0.0, "notes": []} for e in s.evals}
    first = True
    for e in s.evals:
        for turn in e["turns"]:
            texts = [turn["prompt"]]
            while texts:
                text = texts.pop(0)
                if budget.stop_reason:
                    stats[e["id"]]["notes"].append(f"not run: {budget.stop_reason}")
                    break
                res = claude_turn(text, sid, first, work, env, max_turn_usd)
                first = False
                cost = float(res.get("total_cost_usd") or 0)
                budget.add(cost)
                st = stats[e["id"]]
                st["seconds"] += float(res.get("duration_ms") or 0) / 1000
                st["cost"] += cost
                if res.get("permission_denials"):
                    st["notes"].append(f"{len(res['permission_denials'])} permission denial(s)")
                if res.get("is_error"):
                    msg = str(res.get("result") or res.get("subtype") or "error")[:120]
                    st["notes"].append(msg)
                    if LIMIT_HIT.search(msg):
                        budget.stop(f"stopped: {msg}")
                        st["invalid"] = True
                        break
                if text == turn["prompt"] and turn.get("reply_if_asked"):
                    path = session_file(sid)
                    turn_events = split_turns(grade.load_events(path), {"x": text})["x"] if path else []
                    if needs_reply(grade.extract(turn_events).outputs):
                        texts.append(turn["reply_if_asked"])
    path = session_file(sid)
    events = grade.load_events(path) if path else []
    if path:
        shutil.copy(path, raw / f"{s.key}.jsonl")
    ctx = Ctx.current(work=[work, str(work).replace("/private/", "/", 1)], sessions=[sid])
    try:
        parts = split_turns(events, {e["id"]: e["turns"][0]["prompt"] for e in s.evals})
    except StopIteration:
        parts = {}
    results, defaults = [], json.loads((HERE / "evals.json").read_text("utf-8")).get("check_defaults", {})
    for e in s.evals:
        st, eid = stats[e["id"]], e["id"]
        name = f"{eid}-{s.attempt}"
        part = parts.get(eid)
        if not part or st.get("invalid"):
            results.append(Result(eid, s.attempt, "INVALID", [], note="; ".join(st["notes"]) or "no transcript",
                                  seconds=st["seconds"], cost=st["cost"]))
            continue
        clean = scrub("\n".join(json.dumps(ev, ensure_ascii=False) for ev in part) + "\n", ctx)
        leaks = find_leaks(clean, ctx)
        clean_events = [json.loads(line) for line in clean.splitlines() if line.strip()]
        parent = e.get("continues")
        context = ([json.loads(ln) for ln in scrub("\n".join(json.dumps(ev, ensure_ascii=False)
                                                               for ev in parts[parent]), ctx).splitlines()]
                   if parent and parent in parts else None)
        run = grade.extract(clean_events, context)
        checks = grade.grade(run, e, work, defaults, leaks=leaks)
        verdict = grade.verdict(checks)
        if not leaks:
            (out / f"{name}.jsonl").write_text(clean, "utf-8")
        report = grade.report(checks, f"{name} — {e.get('expected_output', '')}")
        if st["notes"]:
            report += "\nNotes: " + "; ".join(st["notes"]) + "\n"
        (out / f"{name}.grade.md").write_text(report, "utf-8")
        for pdf in (work / "wiki-interest-output").glob("*/report.pdf"):
            shutil.copy(pdf, raw / f"{name}-{pdf.parent.name}.pdf")
        results.append(Result(eid, s.attempt, verdict, checks, len(run.calls), st["seconds"], st["cost"],
                              "; ".join(st["notes"] + (["leaks: " + ", ".join(leaks)] if leaks else []))))
    shutil.rmtree(work, ignore_errors=True)
    return results


def _claude_version() -> str:
    try:
        return subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.split()[0]
    except (OSError, IndexError):
        return "?"


def grade_only(folder: Path) -> str:
    """Scrub and grade transcripts exported by hand into <folder>/raw/<ID>.jsonl."""
    data = json.loads((HERE / "evals.json").read_text("utf-8"))
    specs = {e["id"]: e for e in data["evals"]}
    results = []
    for path in sorted((folder / "raw").glob("*.jsonl")):
        eid = path.stem.split("-")[0]
        events = grade.load_events(path)
        cwd = next((ev["cwd"] for ev in events if ev.get("cwd")), "")
        sids = sorted({ev["sessionId"] for ev in events if ev.get("sessionId")})
        ctx = Ctx.current(work=[cwd, cwd.replace("/private/", "/", 1)] if cwd else [], sessions=sids)
        start = next((i for i, ev in enumerate(events)
                      if grade.is_prompt(ev) and grade._text(grade._blocks(ev)).strip()
                      == specs[eid]["turns"][0]["prompt"].strip()), 0)
        part = events[start:]
        clean = scrub("\n".join(json.dumps(ev, ensure_ascii=False) for ev in part) + "\n", ctx)
        leaks = find_leaks(clean, ctx)
        run = grade.extract([json.loads(ln) for ln in clean.splitlines() if ln.strip()])
        checks = grade.grade(run, specs[eid], Path(cwd or "."), data.get("check_defaults", {}), leaks=leaks)
        if not leaks:
            (folder / f"{path.stem}.jsonl").write_text(clean, "utf-8")
        (folder / f"{path.stem}.grade.md").write_text(grade.report(checks, path.stem), "utf-8")
        stamps = [ev["timestamp"] for ev in part if ev.get("timestamp")]
        secs = 0.0
        if len(stamps) > 1:
            from datetime import datetime
            secs = (datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
                    - datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))).total_seconds()
        results.append(Result(eid, 1, grade.verdict(checks), checks, len(run.calls), secs, 0.0))
    text = summarize(results, {"date": date.today().isoformat(), "claude": _claude_version(), "model": "manual"})
    (folder / "SUMMARY.md").write_text(text, "utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run and grade the Haiku eval scenarios")
    ap.add_argument("--only", help="comma-separated scenario ids (a continued scenario brings its parent)")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--budget-usd", type=float, default=10.0, help="stop starting sessions past this total")
    ap.add_argument("--max-turn-usd", type=float, default=0.75)
    ap.add_argument("--out", default=f"evals/runs/{date.today().isoformat()}")
    ap.add_argument("--grade-only", metavar="FOLDER")
    a = ap.parse_args(argv)
    if a.grade_only:
        print(grade_only(Path(a.grade_only)))
        return 0
    data = json.loads((HERE / "evals.json").read_text("utf-8"))
    only = set(a.only.split(",")) if a.only else None
    sessions = plan_sessions(data["evals"], a.attempts, only)
    out = Path(a.out)
    (out / "raw" / "cache").mkdir(parents=True, exist_ok=True)
    budget, results = Budget(a.budget_usd), []

    def one(s: Session) -> list[Result]:
        if budget.stop_reason:
            return [Result(e["id"], s.attempt, "INVALID", [], note=f"not run: {budget.stop_reason}") for e in s.evals]
        print(f"[eval] {s.key} …", file=sys.stderr, flush=True)
        rs = run_session(s, out, budget, a.max_turn_usd)
        print(f"[eval] {s.key}: {', '.join(r.verdict for r in rs)} · spent ${budget.spent:.2f}", file=sys.stderr,
              flush=True)
        return rs

    for s in [s for s in sessions if s.attempt == 1]:
        results += one(s)
    with ThreadPoolExecutor(max_workers=max(1, a.parallel)) as pool:
        for rs in pool.map(one, [s for s in sessions if s.attempt > 1]):
            results += rs
    results.sort(key=lambda r: ([e["id"] for e in data["evals"]].index(r.eval_id), r.attempt))
    text = summarize(results, {"date": date.today().isoformat(), "claude": _claude_version(), "model": MODEL})
    (out / "SUMMARY.md").write_text(text, "utf-8")
    print(text)
    if budget.stop_reason:
        print(f"[eval] stopped early: {budget.stop_reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
