import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

import grade  # noqa: E402

WIR = "<work>/.claude/skills/wiki-interest-research/scripts/wir"
PROMPT = "Порівняй інтерес до голодування в pl і cs за два роки."


class Session:
    """Builds a Claude Code session JSONL: user/assistant events with tool_use / tool_result pairs."""

    def __init__(self):
        self.events, self.n = [], 0

    def user(self, text, **extra):
        self.events.append({"type": "user", "message": {"role": "user", "content": text}, **extra})
        return self

    def say(self, text):
        self.events.append({"type": "assistant", "message": {"role": "assistant",
                                                             "content": [{"type": "text", "text": text}]}})
        return self

    def tool(self, name, inp, result, is_error=False):
        self.n += 1
        tid = f"toolu_{self.n}"
        self.events.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        self.events.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": is_error}]}})
        return self

    def wir(self, args, env, code=0):
        out = json.dumps(env, ensure_ascii=False)
        text = f"Exit code {code}\n[wir] progress\n{out}" if code else f"[wir] progress\n{out}"
        return self.tool("Bash", {"command": f"{WIR} {args}"}, text, is_error=bool(code))

    def skill(self):
        return self.tool("Skill", {"skill": "wiki-interest-research"}, "Launching skill: wiki-interest-research")

    def write(self, path):
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in self.events) + "\n", "utf-8")
        return path


ASK = {"ok": True, "state": "input_required", "say": ["польська: статті на цю тему немає."],
       "ask": {"question": "Немає статті. Що робити?", "options": [
           {"label": "Продовжити без мови: польська", "cmd": "wir scope --drop-lang pl"},
           {"label": "Głodówka lecznicza (7 мов)", "cmd": "wir scope --set pl='Głodówka lecznicza'"}]}}
SUMMARY = {"say": ["чеська: 3,04 на мільйон переглядів розділу; рік до року -48% (90% ДІ -62…-28%) — спадає; "
                   "довіра: низька."], "facts": {"cs": {"growth": "-48%"}}, "caveats": ["Інтерес — не попит."]}


def ready(**extra):
    return {"ok": True, "state": "ready", "say": SUMMARY["say"], "caveats": SUMMARY["caveats"],
            "files": {"data": "<work>/wiki-interest-output/p/analysis.json", "notes_template": "x",
                      "charts": "<work>/wiki-interest-output/p/charts"}, **extra}


@pytest.fixture
def workdir(tmp_path):
    proj = tmp_path / "work" / "wiki-interest-output" / "p"
    proj.mkdir(parents=True)
    analysis = {"window": {"start": "2024-09-01", "end": "2026-08-31", "last_day": "2026-09-26"},
                "project": {"period_months": 24, "langs": ["pl", "cs"], "label": "голодування", "topic": "x"},
                "langs": {"cs": {"usable": True, "titles": [{"title": "Přerušovaný půst"}]}},
                "summary": SUMMARY}
    (proj / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), "utf-8")
    return tmp_path / "work"


SPEC = {"id": "E1", "checks": {"commands_in_order": ["scope", "scope", "analyze", "verify"], "must_ask": True,
                               "max_tool_calls": 10, "answer_contains_any": ["чеськ"],
                               "answer_contains_all_groups": [["довір"], ["інтерес"]]}}
DEFAULTS = {"skill_used": True, "must_ask": False, "numbers_grounded": True, "pdf": False, "commands_match": [],
            "answer_contains_any": [], "answer_contains_all_groups": [], "answer_contains_none": [],
            "no_model_language_pick": False}


def good_session():
    return (Session().user(PROMPT).skill()
            .wir("scope 'голодування' --langs pl,cs --ui uk", ASK, code=2)
            .say("Польською статті немає. Що робити?\n1. Продовжити без мови: польська\n2. Głodówka lecznicza (7 мов)")
            .user("Продовжуй без польської.")
            .wir("scope --drop-lang pl", {"ok": True, "state": "ready", "say": ["чеська: стаття."]})
            .wir("analyze", ready()).wir("verify", ready())
            .say("Коротко: чеська -48% (90% ДІ -62…-28%), довіра низька. Це інтерес, 2 роки даних."))


def run_grade(tmp_path, workdir, session, spec=SPEC):
    events = grade.load_events(session.write(tmp_path / "t.jsonl"))
    return grade.grade(grade.extract(events), spec, workdir, defaults=DEFAULTS)


def status(checks, name):
    return next(c.status for c in checks if c.name == name)


def test_passing_run(tmp_path, workdir):
    checks = run_grade(tmp_path, workdir, good_session())
    assert grade.verdict(checks) == "PASS", grade.report(checks)
    run = grade.extract(good_session().events)
    assert [c.wir for c in run.calls if c.wir] == ["scope", "scope", "analyze", "verify"]
    assert run.outputs[0]["state"] == "input_required" and run.replied and not run.analyzed_before_reply


def test_invented_number_fails(tmp_path, workdir):
    s = good_session().say("Коротко: чеська впала на 37%, довіра низька; це інтерес.")
    checks = run_grade(tmp_path, workdir, s)
    assert status(checks, "numbers_grounded") == "FAIL" and grade.verdict(checks) == "FAIL"


def test_ask_not_relayed_fails(tmp_path, workdir):
    s = (Session().user(PROMPT).skill().wir("scope x --langs pl,cs --ui uk", ASK, code=2)
         .wir("scope --drop-lang pl", {"ok": True, "state": "ready"}).wir("analyze", ready()).wir("verify", ready())
         .say("Коротко: чеська -48%, довіра низька; інтерес."))
    assert status(run_grade(tmp_path, workdir, s), "must_ask") == "FAIL"


def test_numbers_from_an_ask_option_and_the_user_turn_are_allowed(tmp_path, workdir):
    s = good_session().say("Коротко: чеська -48%, довіра низька; інтерес. Glodówka є в 7 мовах; дивились 2 роки.")
    assert status(run_grade(tmp_path, workdir, s), "numbers_grounded") == "PASS"
    s = good_session().say("Коротко: чеська -48%, довіра низька; інтерес. Ви просили 5 років.")
    s.events[0]["message"]["content"] = PROMPT + " А потім за 5 років."
    assert status(run_grade(tmp_path, workdir, s), "numbers_grounded") == "PASS"


def test_unknown_event_types_and_list_content_are_handled(tmp_path, workdir):
    s = good_session()
    s.events[1:1] = [{"type": "summary", "summary": "x"}, {"type": "system", "subtype": "init"},
                     {"type": "attachment", "attachment": {"type": "x"}}]
    s.events[0]["message"]["content"] = [{"type": "text", "text": PROMPT}]
    tid = s.events[-2]["message"]["content"][0]["tool_use_id"]   # verify's result as a list of text blocks
    s.events[-2]["message"]["content"][0]["content"] = [{"type": "text", "text": json.dumps(ready())}]
    assert tid and grade.verdict(run_grade(tmp_path, workdir, s)) == "PASS"


def test_meta_user_text_is_not_a_user_turn():
    s = good_session()
    s.events.insert(2, {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
        {"type": "text", "text": "Base directory for this skill: 100 lines"}]}})
    run = grade.extract(s.events)
    assert run.user_texts == [PROMPT, "Продовжуй без польської."]


def test_polluted_run_is_invalid(tmp_path, workdir):
    s = good_session()
    s.events.insert(1, {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
        {"type": "text", "text": "<EXTREMELY_IMPORTANT>You have superpowers.</EXTREMELY_IMPORTANT>"}]}})
    checks = run_grade(tmp_path, workdir, s)
    assert status(checks, "clean_env") == "INVALID" and grade.verdict(checks) == "INVALID"


def test_model_picking_languages_itself_fails():
    spec = {"id": "E12", "checks": {"commands_in_order": ["scope", "analyze", "verify"], "must_ask": True,
                                    "no_model_language_pick": True, "max_tool_calls": 10}}
    s = (Session().user("Which languages should we launch in? Check interest in meditation.").skill()
         .wir("scope meditation --langs de,fr,es --ui en", {"ok": True, "state": "ready"})
         .wir("analyze", ready()).wir("verify", ready()).say("Launch in German."))
    checks = grade.grade(grade.extract(s.events), spec, Path("/nonexistent"), defaults=DEFAULTS)
    assert status(checks, "no_model_language_pick") == "FAIL" and status(checks, "must_ask") == "FAIL"
    s = (Session().user("Which languages should we launch in? Check interest in meditation.").skill()
         .wir("scope meditation --ui en", {"ok": False, "state": "failed", "error": {"code": "MISSING_LANGS"}}, code=3)
         .say("Which language editions should I compare?").user("German, Polish and Spanish.")
         .wir("scope meditation --langs de,pl,es --ui en", {"ok": True, "state": "ready"})
         .wir("analyze", ready()).wir("verify", ready()).say("German, Polish, Spanish: interest."))
    checks = grade.grade(grade.extract(s.events), spec, Path("/nonexistent"), defaults=DEFAULTS)
    assert status(checks, "no_model_language_pick") == "PASS" and status(checks, "must_ask") == "PASS"


def test_order_match_limits_and_pdf(tmp_path, workdir):
    spec = {"id": "E3", "checks": {"commands_in_order": ["scope", "analyze", "verify", "publish"], "max_tool_calls": 4,
                                   "commands_match": ["--weights"], "pdf": True, "answer_contains_none": ["попит"],
                                   "numbers_grounded": False}}
    s = good_session().say("Коротко: попит є.")
    checks = run_grade(tmp_path, workdir, s, spec)
    assert {c.name for c in checks if c.status == "FAIL"} == {"commands_in_order", "commands_match", "max_tool_calls",
                                                             "pdf", "answer_contains_none"}
    pdf = workdir / "wiki-interest-output" / "p" / "report.pdf"
    pdf.write_bytes(b"%PDF")
    s = good_session().wir("publish", {"ok": True, "state": "ready", "files": {
        "pdf": "<work>/wiki-interest-output/p/report.pdf"}}).say("Звіт: PDF.")
    assert status(run_grade(tmp_path, workdir, s, spec), "pdf") == "PASS"


def test_several_wir_commands_in_one_bash_call():
    s = Session().user(PROMPT).tool("Bash", {"command": f"{WIR} analyze && {WIR} verify"},
                                     json.dumps(ready()) + "\n" + json.dumps(ready(say=["v"])))
    run = grade.extract(s.events)
    assert [c.wir for c in run.calls] == ["analyze"] and run.commands == ["analyze", "verify"]
    assert len(run.outputs) == 2 and run.outputs[1]["say"] == ["v"]


def test_report_table():
    text = grade.report([grade.Check("max_tool_calls", "FAIL", "12 > 10")])
    assert "| check | result | detail |" in text and "| max_tool_calls | FAIL | 12 > 10 |" in text
