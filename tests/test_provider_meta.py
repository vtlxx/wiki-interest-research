from datetime import date

from wir_core.providers import get_provider
from wir_core.providers.base import DISAMBIGUATION, FOUND


def wp(recorded_client):
    return get_provider("wikipedia", recorded_client("provider_meta"))


def test_search_intermittent_fasting(recorded_client):
    cands = wp(recorded_client).search("intermittent fasting", "uk")
    assert cands[0].qid == "Q1666254" and cands[0].exact and cands[0].sitelinks >= 20


def test_links_pl_missing_cs_present(recorded_client):
    links = wp(recorded_client).links("Q1666254", ["pl", "cs"])
    assert links["pl"] == (None, [])
    assert links["cs"][0] == "Přerušovaný půst"


def test_entity_label(recorded_client):
    cand = wp(recorded_client).entity("Q1666254", "en")
    assert cand.label.lower() == "intermittent fasting"


def test_inspect_cs_article(recorded_client):
    info = wp(recorded_client).inspect("cs", ["Přerušovaný půst"])["Přerušovaný půst"]
    assert info.status == FOUND and info.qid == "Q1666254"
    assert info.created == date(2020, 10, 28) and info.extract


def test_inspect_disambiguation(recorded_client):
    assert wp(recorded_client).inspect("en", ["Mercury"])["Mercury"].status == DISAMBIGUATION


def test_redirects_include_known_alias(recorded_client):
    reds = wp(recorded_client).redirects("en", "Intermittent fasting")
    titles = {r.title for r in reds}
    assert "5:2 diet" in titles
    assert all(r.views_60d is not None for r in reds)  # ~25 redirects fit in the pageviews budget
    assert any(r.views_60d for r in reds)


def test_move_log_twitter(recorded_client):
    moves = wp(recorded_client).moves("en", ["Twitter"])
    assert any(m.source == "Twitter" and m.target == "X (social network)" and m.when == date(2026, 2, 25)
               for m in moves)
    assert not any(":" in m.target for m in moves)  # the 2026-03-11 move into Draft: space is dropped


def test_search_in_wiki_pl(recorded_client):
    hits = wp(recorded_client).search_in_wiki("pl", "post przerywany")
    assert hits and all(isinstance(t, str) for t, _ in hits)


def test_edits_on_returns_count(recorded_client):
    assert wp(recorded_client).edits_on("en", "Intermittent fasting", date(2025, 12, 5)) == 6
