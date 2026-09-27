"""Grade one Claude Code session transcript (JSONL) of an eval scenario.

Usage: uv run python evals/grade.py <transcript.jsonl> --eval E1 --workdir <dir> [--context parent.jsonl]
                                    [--out report.md]
Checks what the skill promises: the `wir` commands ran in the prescribed order, a tool question reached the
user before anything was decided, every number in the final answer comes from the tool's output (or the user),
and the answer has the required parts. A run polluted by foreign plugins or hooks is INVALID, not failed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

from wir_core.publish.numcheck import Allowed, allowed_values, check, numbers, strings  # noqa: E402

WIR = re.compile(r"scripts/wir\s+(scope|analyze|verify|publish|status)\b([^&|;\n]*)")
POLLUTION = ("EXTREMELY_IMPORTANT", "superpowers:", "using-superpowers")
ENVELOPE_KEYS = ("say", "facts", "caveats", "ask", "next")
SKILL = "wiki-interest-research"


@dataclass
class Call:
    name: str
    input: dict
    result: str = ""
    is_error: bool = False
    wir: str | None = None                  # first wir subcommand of the call


@dataclass
class Run:
    calls: list[Call] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)          # every wir subcommand, in order
    command_lines: list[str] = field(default_factory=list)     # "scope 'x' --langs pl,cs --ui uk", ...
    outputs: list[dict] = field(default_factory=list)          # every wir JSON envelope, in order
    context_outputs: list[dict] = field(default_factory=list)  # envelopes of the scenario this one continues
    user_texts: list[str] = field(default_factory=list)
    final_answer: str = ""
    ask_relay: str = ""                     # the last assistant text before the user's reply
    replied: bool = False
    analyzed_before_reply: bool = False
    scopes_before_reply: list[str] = field(default_factory=list)
    skill_used: bool = False
    raw_text: str = ""


@dataclass
class Check:
    name: str
    status: str                             # PASS | FAIL | INVALID
    detail: str = ""


def load_events(path) -> list[dict]:
    events = []
    for line in Path(path).read_text("utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _blocks(event: dict) -> list[dict]:
    content = (event.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def is_prompt(event: dict) -> bool:
    """A turn typed by the user (not a tool result, not text injected by Claude Code)."""
    if event.get("type") != "user" or event.get("isMeta"):
        return False
    blocks = _blocks(event)
    return bool(blocks) and all(b.get("type") == "text" for b in blocks) and not any(
        b.get("text", "").lstrip().startswith(("<command-", "<local-command", "Caveat:")) for b in blocks)


def envelopes(text: str) -> list[dict]:
    found = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "state" in obj:
                found.append(obj)
    return found


def extract(events: list[dict], context: list[dict] | None = None) -> Run:
    run, by_id, texts = Run(), {}, []
    for e in events:
        if e.get("type") not in ("user", "assistant"):
            continue
        if is_prompt(e):
            if run.user_texts:
                run.replied = True
                run.ask_relay = texts[-1] if texts else ""
            run.user_texts.append(_text(_blocks(e)))
            texts = []
            continue
        for b in _blocks(e):
            kind = b.get("type")
            if e["type"] == "assistant" and kind == "text" and b.get("text", "").strip():
                texts.append(b["text"])
            elif kind == "tool_use":
                call = Call(b.get("name", ""), b.get("input") or {})
                by_id[b.get("id")] = call
                run.calls.append(call)
                inp = json.dumps(call.input, ensure_ascii=False)
                if call.name == "Skill" and SKILL in inp or call.name == "Read" and "SKILL.md" in inp:
                    run.skill_used = True
                found = WIR.findall(str(call.input.get("command", ""))) if call.name == "Bash" else []
                for sub, rest in found:
                    run.commands.append(sub)
                    run.command_lines.append(f"{sub}{rest}".strip())
                    if not run.replied:
                        run.analyzed_before_reply |= sub == "analyze"
                        if sub == "scope":
                            run.scopes_before_reply.append(f"{sub}{rest}")
                call.wir = found[0][0] if found else None
            elif kind == "tool_result" and b.get("tool_use_id") in by_id:
                call = by_id[b["tool_use_id"]]
                call.result, call.is_error = _text(b.get("content")), bool(b.get("is_error"))
                if call.wir:
                    run.outputs.extend(envelopes(call.result))
    run.final_answer = texts[-1] if texts else ""
    run.raw_text = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
    if context:
        run.context_outputs = extract(context).outputs
    return run


# ---- checks ---------------------------------------------------------------------------------
def _in_order(seq: list[str], wanted: list[str]) -> bool:
    it = iter(seq)
    return all(any(x == w for x in it) for w in wanted)


def _resolve(path: str, workdir: Path) -> Path:
    path = path.replace("<work>", str(workdir))
    p = Path(path)
    return p if p.is_absolute() else workdir / p


def _analysis(run: Run, workdir: Path) -> dict | None:
    for env in reversed(run.outputs):
        data = (env.get("files") or {}).get("data")
        if data and _resolve(data, workdir).exists():
            return json.loads(_resolve(data, workdir).read_text("utf-8"))
    return None


def allowed(run: Run, workdir: Path) -> Allowed:
    """The project's own allowed values + numbers of every wir envelope + numbers the user typed."""
    analysis = _analysis(run, workdir)
    base = allowed_values(analysis, analysis["summary"]) if analysis else Allowed()
    toks = [tok for env in run.outputs + run.context_outputs for key in ENVELOPE_KEYS
            for s in strings(env.get(key)) for tok in numbers(s)]
    toks += [tok for text in run.user_texts for tok in numbers(text)]
    out = Allowed(sorted(set(base) | {tok.value for tok in toks}))
    out.percent = sorted(set(getattr(base, "percent", [])) | {tok.value for tok in toks if tok.percent})
    return out


def _ok(name: str, good: bool, detail: str = "") -> Check:
    return Check(name, "PASS" if good else "FAIL", detail)


def grade(run: Run, spec: dict, workdir, defaults: dict | None = None, leaks: list[str] | None = None) -> list[Check]:
    c = {**(defaults or {}), **spec["checks"]}
    workdir = Path(workdir)
    answer, low = run.final_answer, run.final_answer.lower()
    out = []
    polluted = [p for p in POLLUTION if p in run.raw_text]
    out.append(Check("clean_env", "INVALID" if polluted else "PASS", ", ".join(polluted)))
    if leaks is not None:
        out.append(Check("scrubbed", "INVALID" if leaks else "PASS", ", ".join(leaks)))
    if c.get("skill_used"):
        out.append(_ok("skill_used", run.skill_used))
    want = c.get("commands_in_order", [])
    out.append(_ok("commands_in_order", _in_order(run.commands, want) and (bool(want) or not run.commands),
                   f"ran {run.commands}, expected {want}"))
    missing = [rx for rx in c.get("commands_match", []) if not any(re.search(rx, ln) for ln in run.command_lines)]
    if c.get("commands_match"):
        out.append(_ok("commands_match", not missing, f"no command matches {missing}" if missing else ""))
    if c.get("must_ask"):
        asked = run.replied and not run.analyzed_before_reply and "?" in run.ask_relay
        out.append(_ok("must_ask", asked, "" if asked else
                       f"replied={run.replied}, analyzed_before_reply={run.analyzed_before_reply}, "
                       f"question in relay={'?' in run.ask_relay}"))
    if c.get("no_model_language_pick"):
        picked = [s for s in run.scopes_before_reply if "--langs" in s]
        out.append(_ok("no_model_language_pick", not picked, "; ".join(picked)))
    if "max_tool_calls" in c:
        out.append(_ok("max_tool_calls", len(run.calls) <= c["max_tool_calls"], f"{len(run.calls)} ≤ {c['max_tool_calls']}"))
    if c.get("numbers_grounded"):
        bad = check(answer, allowed(run, workdir))
        out.append(_ok("numbers_grounded", not bad, ", ".join(t.text for t in bad)))
    if c.get("answer_contains_any"):
        out.append(_ok("answer_contains_any", any(w.lower() in low for w in c["answer_contains_any"]),
                       str(c["answer_contains_any"])))
    groups = [g for g in c.get("answer_contains_all_groups", []) if not any(w.lower() in low for w in g)]
    if c.get("answer_contains_all_groups"):
        out.append(_ok("answer_contains_all_groups", not groups, f"missing {groups}" if groups else ""))
    banned = [w for w in c.get("answer_contains_none", []) if w.lower() in low]
    if c.get("answer_contains_none"):
        out.append(_ok("answer_contains_none", not banned, str(banned) if banned else ""))
    if c.get("pdf"):
        pdfs = [(env.get("files") or {}).get("pdf") for env in run.outputs if env.get("ok")]
        good = any(p and _resolve(p, workdir).exists() for p in pdfs)
        out.append(_ok("pdf", good, "" if good else "no report.pdf from wir publish"))
    out.append(_ok("answered", bool(answer.strip())))
    return out


def verdict(checks: list[Check]) -> str:
    if any(ch.status == "INVALID" for ch in checks):
        return "INVALID"
    return "PASS" if all(ch.status == "PASS" for ch in checks) else "FAIL"


def report(checks: list[Check], title: str = "") -> str:
    def cell(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ")
    lines = [f"# {title}", ""] if title else []
    lines += [f"Verdict: **{verdict(checks)}**", "", "| check | result | detail |", "|---|---|---|"]
    lines += [f"| {ch.name} | {ch.status} | {cell(ch.detail)} |" for ch in checks]
    return "\n".join(lines) + "\n"


def load_spec(eval_id: str) -> tuple[dict, dict]:
    data = json.loads((HERE / "evals.json").read_text("utf-8"))
    return next(e for e in data["evals"] if e["id"] == eval_id), data.get("check_defaults", {})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript")
    ap.add_argument("--eval", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--context")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    spec, defaults = load_spec(a.eval)
    context = load_events(a.context) if a.context else None
    checks = grade(extract(load_events(a.transcript), context), spec, a.workdir, defaults)
    text = report(checks, f"{a.eval} — {Path(a.transcript).name}")
    if a.out:
        Path(a.out).write_text(text, "utf-8")
    print(text)
    return 0 if verdict(checks) == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
