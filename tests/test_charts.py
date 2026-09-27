from pathlib import Path

import pytest

from wir_core.charts import render_all

PNG = b"\x89PNG\r\n\x1a\n"


def lang_block(level, g, verdict, trust="medium", season=True, countries=True, moves=False):
    months = [f"{2024 + (8 + i) // 12}-{(8 + i) % 12 + 1:02d}" for i in range(24)]
    return {
        "status": "found", "usable": True,
        "monthly": [{"month": m, "views": 1000, "project_views": 10**8, "share": level * (1 + 0.01 * i)}
                    for i, m in enumerate(months)],
        "growth": {"g": g, "lo": g - 0.1, "hi": g + 0.1, "verdict": verdict, "weeks": 52},
        "trust": {"level": trust, "reasons": []},
        "incidents": ["bots_2025_11"],
        "spikes": {"share": 0.1, "episodes": [{"peak": "2025-04-02", "extra_views": 500.0}]},
        "moves": [{"when": "2026-02-25", "source": "A", "target": "B"}] if moves else [],
        "seasonality": {"strength": 0.7, "level": "strong", "peaks": [9, 10],
                        "profile": [0.1 * ((m % 12) - 6) / 6 for m in range(12)]} if season else None,
        "countries": [["UA", 0.7], ["US", 0.1], ["PL", 0.05]] if countries else [],
    }


def analysis(n_langs=2, ui="uk"):
    langs = ["uk", "pl", "cs", "de", "es", "fr"][:n_langs]
    blocks = {lang: lang_block(5.0 * (i + 1), 0.2 - 0.1 * i, ["growing", "stable", "declining"][i % 3], moves=(i == 0))
              for i, lang in enumerate(langs)}
    blocks["sk"] = {"status": "missing", "usable": False}
    return {"project": {"langs": langs + ["sk"], "ui": ui, "period_months": 24, "label": "Astronomy"},
            "window": {"start": "2024-09-01", "end": "2026-08-31", "last_day": "2026-09-26"},
            "langs": blocks, "provenance": {"fetched_at": "2026-09-27T10:00:00+00:00"}}


def test_all_charts_rendered(tmp_path):
    files = render_all(analysis(), tmp_path, "uk")
    assert set(files) == {"share", "index", "growth", "countries", "season"}
    for path in files.values():
        assert Path(path).read_bytes()[:8] == PNG and Path(path).stat().st_size > 10_000


def test_small_multiples_for_many_languages(tmp_path):
    files = render_all(analysis(n_langs=6, ui="en"), tmp_path, "en")
    assert files["share"].exists()


def test_optional_charts_skipped(tmp_path):
    a = analysis(n_langs=1)
    a["langs"]["uk"]["seasonality"] = None
    a["langs"]["uk"]["countries"] = []
    files = render_all(a, tmp_path, "pl")          # unsupported UI -> English labels, must not fail
    assert set(files) == {"share", "index", "growth"}


def test_nothing_usable(tmp_path):
    a = analysis(n_langs=1)
    a["langs"] = {"sk": {"status": "missing", "usable": False}}
    assert render_all(a, tmp_path, "en") == {}


def test_offline_run_without_fetch_time(tmp_path):
    a = analysis()
    a["provenance"] = {"fetched_at": None, "data_through": "2026-09-26"}
    assert set(render_all(a, tmp_path, "en")) == {"share", "index", "growth", "countries", "season"}


@pytest.mark.parametrize("n_langs", [1, 3, 6])
def test_missing_shares_and_growth(tmp_path, n_langs):
    a = analysis(n_langs=n_langs)
    for lang in a["project"]["langs"][:n_langs]:
        block = a["langs"][lang]
        for row in block["monthly"][:5]:
            row["share"] = None                       # young article: no share before it existed
        block["growth"] = None
    files = render_all(a, tmp_path, "uk")
    assert {"share", "index"} <= set(files) and "growth" not in files
