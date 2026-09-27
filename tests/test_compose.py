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
            "core": {"say": n_langs + 1, "headlines": n_langs, "caveats": 2}}


def emitted(env):
    out = io.StringIO()
    envelope.emit(env, stream=out)
    return out.getvalue()


def compose(n, extra=()):
    nxt = [{"why": "Перевірити стійкість висновків", "cmd": "wir verify"},
           {"why": "Скопіюйте notes.template.md у notes.md, заповніть і зберіть звіт", "cmd": "wir publish"}]
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
