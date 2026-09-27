"""End-to-end scenarios from the spec that the analyze/publish tests do not replay yet."""
import json
from pathlib import Path

from pypdf import PdfReader

from test_analyze_cli import analyze_until_ready, load_analysis
from test_publish_cli import write_notes


def test_astronomy_basket_verify_and_publish(cli_fixtures, run_cli):
    cli_fixtures("e2e_astronomy")
    code, env = run_cli("scope", "астрономія", "--langs", "uk", "--ui", "uk")
    assert code == 0 and "(Q333)" in env["say"][0]
    code, env = run_cli("scope", "--add-article", "uk=Сонячна система", "--add-article", "uk=Чорна діра")
    assert code == 0 and any("кошику теми: 2" in line for line in env["say"])
    code, env = analyze_until_ready(run_cli)
    assert code == 0 and env["state"] == "ready"
    assert set(env["files"]) == {"data", "notes_template", "charts"}
    roles = {t["title"]: t["role"] for t in load_analysis(env)["langs"]["uk"]["titles"]}
    assert roles["Сонячна система"] == roles["Чорна діра"] == "extra"
    code, env = run_cli("verify")
    assert code == 0 and any("перевірка стійкості" in line for line in env["say"])
    assert load_analysis(env)["langs"]["uk"]["verify"]["outcome"] in ("holds", "weakens", "flips")
    project, growth = Path(env["project"]), env["facts"]["uk"]["growth"]
    template = (project / "notes.template.md").read_text("utf-8")
    assert "## Висновок" in template and "перевірка стійкості" in template   # verify lines reach the notes facts
    write_notes(project, f"Частка переглядів теми змінилася на {growth} рік до року.", "Перевірити інтерес опитуванням.")
    code, env = run_cli("publish")
    assert code == 0 and env["state"] == "ready"
    assert len(PdfReader(str(project / "report.pdf")).pages) == 1


def test_twitter_renamed_to_x_counts_the_old_title(cli_fixtures, run_cli):
    cli_fixtures("e2e_twitter")
    code, env = run_cli("scope", "Q918", "--langs", "en", "--period", "12m", "--ui", "en")
    assert code == 0 and "“X (social network)”" in env["say"][1]
    code, env = analyze_until_ready(run_cli)
    assert code == 0
    en = load_analysis(env)["langs"]["en"]
    old = {t["title"]: t for t in en["titles"] if t["role"] == "old_title"}
    # 2026-09-27: en "Twitter" was moved to "X (social network)" on 2026-02-25 (inside the 12-month window)
    assert old["Twitter"]["views_window"] > 0
    assert {"when": "2026-02-25", "source": "Twitter", "target": "X (social network)"} in en["moves"]
    assert "renamed" in en["trust"]["reasons"]
    assert any("renamed on 2026-02-25" in c for c in env["caveats"])
    assert abs(en["growth"]["g"]) < 0.5            # counting both titles: no fake collapse after the rename
    code, env = run_cli("verify")
    assert code == 0 and env["state"] == "ready"


def test_wiktionary_asks_for_a_word_per_language(cli_fixtures, run_cli):
    cli_fixtures("e2e_wiktionary")
    code, env = run_cli("scope", "fasting", "--source", "wiktionary", "--langs", "en,pl", "--ui", "en")
    assert code == 2 and env["state"] == "input_required"
    assert sum("<word>" in o["cmd"] for o in env["ask"]["options"]) == 2
    code, env = run_cli("scope", "--set", "en=fasting", "--set", "pl=post")
    assert code == 0 and env["say"][1:] == ["English: article “fasting”.", "Polish: article “post”."]
    code, env = analyze_until_ready(run_cli)
    assert code == 0 and set(env["facts"]) >= {"en", "pl"}
    project = json.loads((Path(env["project"]) / "project.json").read_text("utf-8"))
    assert project["source"] == "wiktionary"
    code, env = run_cli("verify")
    assert code == 0
