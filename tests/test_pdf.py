import copy

import pytest
from pypdf import PdfReader

from test_charts import analysis as chart_analysis          # reuse the synthetic analysis
from wir_core.charts import render_all
from wir_core.publish.markdown import render_md
from wir_core.publish.notes import LIMITS
from wir_core.publish.pdf import font_covers, render_pdf
from wir_core.summary import summarize


def full_analysis(n_langs=2):
    a = chart_analysis(n_langs=n_langs, ui="uk")
    for lang, res in a["langs"].items():
        if res.get("usable"):
            res.update({"share_per_m": 5.0, "raw_growth": 0.1, "project_growth": -0.1, "supply": "normal",
                        "titles": [{"title": "Астрономія", "role": "main", "views_window": 12000, "share": 0.9},
                                   {"title": "Зоряна наука", "role": "redirect", "views_window": 1300, "share": 0.1}],
                        "article": "Астрономія", "article_url": f"https://{lang}.wikipedia.org/wiki/x",
                        "redirects": {"included": [], "coverage": 1.0, "dominant": None, "unchecked": []},
                        "young": False, "verify": None, "trust": {"level": "medium", "reasons": ["data_incident", "spiky"]}})
            res["spikes"]["episodes"][0]["geo"] = None
        else:
            res["supply"] = "missing"
    a["weights"] = {"level": 0.35, "momentum": 0.35, "size": 0.2, "gap": 0.1}
    a["ranking"] = []
    a["provenance"].update({"endpoints": ["https://wikimedia.org/api/rest_v1/metrics/pageviews/..."],
                            "params": {"agent": "user", "access": "all-access"}, "data_through": "2026-09-26"})
    a["project"].update({"topic": "астрономія", "source": "wikipedia", "qid": "Q333"})
    return a


NOTES = {"conclusion": "Інтерес до астрономії в українській Вікіпедії зростає.",
         "recommendation": "Варто перевірити попит опитуванням.", "next": "Порівняти з російським розділом."}
LONG = {k: ("Довге речення про інтерес до теми. " * 20)[:n] for k, n in LIMITS.items()}


def pdf_text(path):
    reader = PdfReader(str(path))
    return len(reader.pages), "\n".join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize("n_langs", [1, 6])
def test_pdf_is_one_page_with_cyrillic(tmp_path, n_langs):
    a = full_analysis(n_langs)
    charts = render_all(a, tmp_path / "charts", "uk")
    out = tmp_path / "report.pdf"
    assert render_pdf(a, summarize(a, "uk"), NOTES, charts, out, "uk") == 1
    pages, text = pdf_text(out)
    assert pages == 1
    for needle in ("Висновок", "Рекомендація", "Мови коротко", "Припущення та обмеження", "Джерела та метод",
                   "Q333", NOTES["recommendation"][:20]):
        assert needle in text


@pytest.mark.parametrize("n_langs", [1, 6])
def test_pdf_fits_with_longest_notes(tmp_path, n_langs):
    a = full_analysis(n_langs)
    charts = render_all(a, tmp_path / "charts", "uk")
    out = tmp_path / "report.pdf"
    assert render_pdf(a, summarize(a, "uk"), LONG, charts, out, "uk") == 1
    assert "Джерела та метод" in pdf_text(out)[1]


def test_pdf_fits_with_fifteen_languages(tmp_path):
    a = full_analysis(6)
    for i in range(9):
        a["langs"][f"x{i}"] = copy.deepcopy(a["langs"]["uk"])
        a["project"]["langs"].append(f"x{i}")
    charts = render_all(a, tmp_path / "charts", "en")
    out = tmp_path / "r.pdf"
    assert render_pdf(a, summarize(a, "en"), LONG, charts, out, "en") == 1
    pages, text = pdf_text(out)
    assert "more language(s) in report.md" in text and "Assumptions and limitations" in text


def test_offline_analysis_says_data_date(tmp_path):
    a = full_analysis(1)
    a["provenance"]["fetched_at"] = None
    out = tmp_path / "r.pdf"
    assert render_pdf(a, summarize(a, "en"), NOTES, {}, out, "en") == 1
    assert "data through 2026-09-26" in pdf_text(out)[1]


def test_markdown_contains_everything(tmp_path):
    a = full_analysis(2)
    a["ranking"] = [{"lang": "uk", "score": 0.71, "components": {}, "eligible": True},
                    {"lang": "pl", "score": 0.4, "components": {}, "eligible": False}]
    a["langs"]["uk"]["verify"] = {"outcome": "holds", "variants": {}}
    charts = render_all(a, tmp_path / "charts", "uk")
    out = tmp_path / "report.md"
    render_md(a, summarize(a, "uk"), NOTES, charts, out, "uk")
    text = out.read_text()
    for needle in ("# Astronomy", "## Висновок", "## Що перевірити далі", "## Мови коротко", "## Рейтинг аудиторій",
                   "0,71", "## Перевірка стійкості", "## Припущення та обмеження", "(charts/share.png)",
                   "## Метод", "[Астрономія](<https://uk.wikipedia.org/wiki/x>)", "перенаправлення",
                   "wiki/%D0%97%D0%BE%D1%80%D1%8F%D0%BD%D0%B0_%D0%BD%D0%B0%D1%83%D0%BA%D0%B0?redirect=no",
                   "12 000", "https://www.wikidata.org/wiki/Q333", "agent=user", "CC0", "словацька"):
        assert needle in text, needle


def test_font_coverage():
    assert font_covers("Привіт, світ! 12% — «ДІ» … −5 ×") == set()
    assert font_covers("学习") == {"学", "习"}
