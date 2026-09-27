from pathlib import Path

from pypdf import PdfReader

from test_analyze_cli import analyze_until_ready


def prepared(cli_fixtures, run_cli, ui="uk"):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "cs", "--ui", ui)
    code, env = analyze_until_ready(run_cli)
    assert code == 0
    return Path(env["project"]), env


def write_notes(project: Path, conclusion: str, recommendation: str, ui="uk"):
    h = ("Висновок", "Рекомендація") if ui == "uk" else ("Conclusion", "Recommendation")
    (project / "notes.md").write_text(f"## {h[0]}\n{conclusion}\n\n## {h[1]}\n{recommendation}\n", "utf-8")


def test_publish_ok_with_numbers_from_facts(cli_fixtures, run_cli):
    project, env = prepared(cli_fixtures, run_cli)
    growth = env["facts"]["cs"]["growth"]
    write_notes(project, f"Частка переглядів змінилася на {growth} за рік.", "Перевірити попит опитуванням.")
    code, out = run_cli("publish")
    assert code == 0 and out["state"] == "ready"
    assert (project / "report.pdf").exists() and (project / "report.md").exists()
    assert not (project / "report.pdf.tmp").exists()
    reader = PdfReader(str(project / "report.pdf"))
    assert len(reader.pages) == 1 and growth in reader.pages[0].extract_text()
    assert "## Висновок" in (project / "report.md").read_text("utf-8")


def test_publish_rejects_invented_number(cli_fixtures, run_cli):
    project, env = prepared(cli_fixtures, run_cli)
    write_notes(project, "Інтерес виріс у 7,77 раза, а частка впала на 49% і ще раз на 49%.", "Запускати.")
    code, out = run_cli("publish")
    msg = out["error"]["message"]
    assert code == 6 and out["error"]["code"] == "NUMBERS_NOT_IN_DATA" and "notes.md" in out["error"]["fix"]
    assert "Висновок: «Інтерес виріс у 7,77 раза" in msg and "7,77 →" in msg
    growth = env["facts"]["cs"]["growth"].lstrip("+-")          # the nearest percentages come first
    assert msg.count("49% →") == 1 and f"49% → {growth}" in msg and msg.count(" / ") >= 4
    assert not (project / "report.pdf").exists()


def test_publish_requires_notes_and_fresh_analysis(cli_fixtures, run_cli):
    project, _ = prepared(cli_fixtures, run_cli)
    code, out = run_cli("publish")
    assert code == 3 and out["error"]["code"] == "NOTES_MISSING" and "notes.template.md" in out["error"]["fix"]
    write_notes(project, "Так.", "")
    code, out = run_cli("publish")
    assert code == 3 and out["error"]["code"] == "NOTES_INCOMPLETE"
    (project / ".stale").write_text("1")
    write_notes(project, "Так.", "Ні.")
    code, out = run_cli("publish")
    assert code == 5 and out["error"]["code"] == "STALE_ANALYSIS" and "wir analyze" in out["error"]["fix"]


def test_publish_not_analyzed(cli_fixtures, run_cli):
    cli_fixtures("analyze_fasting")
    run_cli("scope", "Q1666254", "--langs", "cs", "--ui", "uk")
    code, out = run_cli("publish")
    assert code == 5 and out["error"]["code"] == "NOT_ANALYZED"


def test_publish_unsupported_script(cli_fixtures, run_cli):
    project, _ = prepared(cli_fixtures, run_cli)
    write_notes(project, "兴趣下降。", "研究。")
    code, out = run_cli("publish")
    assert out["error"]["code"] == "SCRIPT_UNSUPPORTED" and "--ui en" in out["error"]["fix"]
    write_notes(project, "الاهتمام ينخفض.", "بحث.")                  # DejaVu has Arabic glyphs but no shaping
    code, out = run_cli("publish")
    assert out["error"]["code"] == "SCRIPT_UNSUPPORTED"
    write_notes(project, "Interest changed.", "Run a survey.", ui="en")
    code, out = run_cli("publish", "--ui", "en")
    assert code == 0
    assert "Languages at a glance" in PdfReader(str(project / "report.pdf")).pages[0].extract_text()
    assert (project / "charts-en" / "share.png").exists()
