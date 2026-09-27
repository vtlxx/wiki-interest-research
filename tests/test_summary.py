from wir_core.summary import summarize


def analysis(ui="en"):
    return {
        "project": {"ui": ui, "langs": ["cs", "pl"], "period_months": 12},
        "weights": {"level": 0.35, "momentum": 0.35, "size": 0.2, "gap": 0.1},
        "langs": {
            "cs": {"status": "found", "usable": True, "share_per_m": 5.123, "median_monthly_views": 380.0,
                   "growth": {"g": -0.47, "lo": -0.55, "hi": -0.38, "verdict": "declining", "weeks": 52},
                   "raw_growth": -0.54, "project_growth": -0.126,
                   "seasonality": {"strength": 0.7, "level": "strong", "peaks": [1, 4], "profile": []},
                   "countries": [["CZ", 0.93], ["SK", 0.02]], "supply": "normal",
                   "trust": {"level": "medium", "reasons": ["data_incident"]},
                   "incidents": ["bots_2025_11"], "young": False, "moves": [],
                   "redirects": {"included": [], "coverage": 1.0, "dominant": None, "unchecked": []},
                   "spikes": {"share": 0.05, "episodes": [{"peak": "2025-04-02", "geo": {
                       "countries": [["CZ", 0.9], ["SK", 0.1]], "other_projects": [["en.wikipedia", 120]]}}]},
                   "verify": None},
            "pl": {"status": "missing", "usable": False, "supply": "missing"}},
        "ranking": [],
    }


def test_say_lines_and_numbers_are_formatted():
    out = summarize(analysis(), "en")
    text = " ".join(out["say"])
    assert "Czech: 5.12 views per million" in text and "-47%" in text and "-55…-38%" in text
    assert "declining" in text and "trust: medium" in text
    assert "Polish: no article" in text
    assert "strong seasonality, peaks in Jan, Apr" in text
    assert "CZ 93%" in text and "2025-04-02" in text


def test_facts_compact_and_reasons_localised():
    facts = summarize(analysis(), "uk")["facts"]
    assert facts["cs"]["growth"] == "-47%" and facts["cs"]["trust"] == "середня"
    assert facts["cs"]["share_per_m"] == "5,12"
    assert facts["pl"] == {"status": "missing", "supply": "статті немає"}


def test_caveats_always_include_core_limits_and_incidents():
    cav = summarize(analysis(), "en")["caveats"]
    assert cav[0].startswith("Pageviews show curiosity") and cav[1].startswith("A language edition is not a country")
    assert any("Undetected bots" in c for c in cav)
    assert any("even when a shorter period" in c for c in cav)     # period_months=12 < 24


def test_ranking_comes_before_spike_geography_and_skipped_steps_are_explained():
    a = analysis()
    a["langs"]["pl"] = {**a["langs"]["cs"], "share_per_m": 2.0}
    a["ranking"] = [{"lang": "cs", "score": 0.8, "components": {}, "eligible": True},
                    {"lang": "pl", "score": 0.2, "components": {}, "eligible": False}]
    a["geo_skipped"] = a["countries_skipped"] = True
    out = summarize(a, "en")
    ranking = next(i for i, s in enumerate(out["say"]) if s.startswith("Audiences to explore next: Czech"))
    geo = next(i for i, s in enumerate(out["say"]) if "spike on 2025-04-02" in s)
    assert ranking < geo and "Polish" not in out["say"][ranking]
    assert any("country breakdown of spikes was skipped" in c for c in out["caveats"])
    assert any("Readers by country were skipped" in c for c in out["caveats"])


def test_young_article_without_growth():
    a = analysis()
    a["langs"]["cs"].update(growth=None, young=True, created="2025-06-10", effective_start="2025-10-01")
    out = summarize(a, "en")
    assert any("yearly change cannot be measured" in s for s in out["say"])
    assert out["facts"]["cs"]["growth"] == "—"
    assert any("created on 2025-06-10" in c for c in out["caveats"])


def test_headlines_first_reasons_grouped_and_global_incidents_unprefixed():
    a = analysis()
    a["langs"]["pl"] = {**a["langs"]["cs"], "share_per_m": 2.0, "incidents": ["bots_2025_brazil", "bots_2025_11"]}
    a["ranking"] = [{"lang": "cs", "score": 0.8, "components": {}, "eligible": True},
                    {"lang": "pl", "score": 0.2, "components": {}, "eligible": True}]
    out = summarize(a, "en")
    say, cav = out["say"], out["caveats"]
    assert say[0].startswith("Czech: 5.12") and say[1].startswith("Polish: 2.00") and say[2].startswith("Audiences")
    assert out["core"] == {"say": 3, "caveats": 2}
    assert sum("why this trust level" in s for s in say) == 1
    assert any(s.startswith("Czech, Polish — why this trust level") for s in say)
    bots = [c for c in cav if "Undetected bots" in c]
    assert len(bots) == 1 and not bots[0].startswith("Czech")        # a Wikimedia-wide incident: no language prefix
    backfill = next(i for i, c in enumerate(cav) if "removed retroactively" in c)
    assert cav.index(bots[0]) < backfill                              # high severity before low


def test_incidents_are_dated_and_comparison_span_incidents_are_captioned():
    a = analysis()
    a["langs"]["cs"].update(incidents=[], incidents_high=["bots_2025_11"])   # only in the compared year
    a["langs"]["cs"]["spikes"]["episodes"].append({"peak": "2026-08-30", "geo": {"unpublished": True}})
    cav = summarize(a, "uk")["caveats"]
    assert any(c.startswith("2025-11-01…2025-11-30: ") for c in cav)
    assert any("2026-08-30" in c and "ще не опубліковано" in c for c in cav)


def test_weights_use_the_ui_number_format():
    a = analysis("uk")
    a["langs"]["pl"] = {**a["langs"]["cs"]}
    a["ranking"] = [{"lang": "cs", "score": 0.8, "components": {}, "eligible": True},
                    {"lang": "pl", "score": 0.2, "components": {}, "eligible": True}]
    assert any("level=0,35" in s for s in summarize(a, "uk")["say"])
