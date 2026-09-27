import io
import json

from wir_core import envelope
from wir_core.pipeline import compose_envelope

HEAD = "{n}: 43,0 на мільйон переглядів розділу; рік до року -10% (90% ДІ -14…-5%) — спадає; довіра: середня."


def summary(n_langs):
    langs = [f"мова{i}" for i in range(n_langs)]
    fact = {"share_per_m": "43,0", "growth": "-10%", "growth_ci": "-14…-5%", "verdict": "спадає",
            "trust": "середня", "season": "помірна", "countries": ["PL 87%", "US 2%", "DE 2%"],
            "supply": "звичайна стаття", "verify": "висновок слабшає"}
    say = [HEAD.format(n=l) for l in langs] + ["Аудиторії, які варто дослідити далі: мова0, мова1 (ваги: level=0,35)."]
    say += [f"{l} — чому така довіра: на порівнювані роки припадає відома проблема з даними." for l in langs]
    caveats = ["Перегляди показують цікавість, а не готовність платити.", "Мовний розділ — не країна."]
    caveats += [f"2025-11-01…2025-11-30: застереження номер {i} " + "x" * 80 for i in range(5)]
    return {"say": say, "caveats": caveats, "facts": {l: dict(fact) for l in langs},
            "core": {"say": n_langs + 1, "headlines": n_langs, "reasons": n_langs, "caveats": 2}}


def emitted(env):
    out = io.StringIO()
    envelope.emit(env, stream=out)
    return out.getvalue()


def compose(n, extra=()):
    nxt = [{"why": "Перевірити стійкість висновків", "cmd": "wir verify"},
           {"why": "Зібрати односторінковий PDF-звіт", "cmd": "wir publish"}]
    files = {"data": "wiki-interest-output/2026-09-27-q1860/analysis.json",
             "notes_template": "wiki-interest-output/2026-09-27-q1860/notes.template.md"}
    return compose_envelope("uk", summary(n), list(extra), project="wiki-interest-output/2026-09-27-q1860",
                            next_=nxt, files=files)


def test_core_survives_for_many_languages_and_verify_lines():
    for n in (2, 5, 8):
        extra = [f"мова{i}: перевірка стійкості — висновок слабшає; довіра тепер низька." for i in range(n)]
        text = emitted(compose(n, extra))
        env = json.loads(text)
        assert len(text.encode()) <= envelope.MAX_BYTES and envelope.TRUNCATED_NOTE not in text
        assert env["caveats"][:2] == summary(n)["caveats"][:2]
        assert any(s.startswith("Аудиторії") for s in env["say"])
        assert env["say"][0].startswith("мова0:")
        if n == 5:
            assert all(any(s.startswith(f"мова{i}: 43,0") for s in env["say"]) for i in range(5))


def test_small_projects_keep_full_facts_and_all_lines():
    env = json.loads(emitted(compose(1)))
    assert env["facts"]["мова0"]["countries"] == ["PL 87%", "US 2%", "DE 2%"]


def test_trust_reasons_are_kept_before_verify_and_detail_lines():
    for n in (2, 4):
        s = summary(n)
        extra = [f"мова{i}: перевірка стійкості — висновок слабшає; довіра тепер низька." for i in range(n)]
        env = compose_envelope("uk", s, extra, project="p", next_=[], files={"data": "analysis.json"})
        first_reason = s["say"][s["core"]["say"]]
        assert first_reason in env["say"]
        if extra[0] in env["say"]:
            assert env["say"].index(first_reason) < env["say"].index(extra[0])


def test_a_long_grouped_reason_line_is_kept_even_when_facts_must_shrink():
    s = summary(4)
    long_reason = ("мова0, мова1, мова2, мова3 — чому така довіра: висновок слабшає за альтернативних розрахунків; "
                   "на порівнювані роки припадає відома проблема з даними Wikimedia.")
    s["say"] = s["say"][:5] + [long_reason] + s["say"][9:]
    s["core"]["reasons"] = 1
    s["caveats"][:2] = [  # the real core caveats are long sentences
        "Перегляди показують цікавість, а не готовність платити: сприймайте результати як напрями для подальшої перевірки.",
        "Мовний розділ — не країна: його читачі живуть у різних країнах, а одна країна читає кілька розділів."]
    extra = [f"мова{i}: перевірка стійкості — висновок слабшає; довіра тепер низька." for i in range(4)]
    files = {"data": "/Users/someone/projects/wiki-interest-output/2026-09-27-q1860/analysis.json",
             "notes_template": "/Users/someone/projects/wiki-interest-output/2026-09-27-q1860/notes.template.md",
             "charts": "/Users/someone/projects/wiki-interest-output/2026-09-27-q1860/charts"}
    text = emitted(compose_envelope("uk", s, extra, project="p", next_=[], files=files))
    env = json.loads(text)
    assert len(text.encode()) <= envelope.MAX_BYTES and envelope.TRUNCATED_NOTE not in text
    assert all(any(line.startswith(f"мова{i}: 43,0") for line in env["say"]) for i in range(4))
    assert long_reason in env["say"]


def test_real_four_language_verify_keeps_the_trust_reason_line():
    from pathlib import Path
    case = json.loads((Path(__file__).parent / "fixtures" / "compose" / "q1860_after_verify.json").read_text("utf-8"))
    s = case["summary"]
    base = "wiki-interest-output/2026-09-27-q1860"
    files = {"data": f"{base}/analysis.json", "notes_template": f"{base}/notes.template.md", "charts": f"{base}/charts"}
    nxt = [{"why": "Зібрати односторінковий PDF-звіт", "cmd": "wir publish"}]
    text = emitted(compose_envelope("uk", s, case["extra_say"], project=base, next_=nxt, files=files))
    env = json.loads(text)
    reason = s["say"][s["core"]["say"]]
    assert "чому така довіра" in reason and reason in env["say"]
    assert len(text.encode()) <= envelope.MAX_BYTES and envelope.TRUNCATED_NOTE not in text
    assert all(line in env["say"] for line in s["say"][:s["core"]["say"]])
