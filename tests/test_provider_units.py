from datetime import date

import httpx
import pytest

from wir_core.cache import Cache
from wir_core.errors import EXIT_NETWORK, WirError
from wir_core.net import HttpClient
from wir_core.providers import get_provider
from wir_core.providers.base import DISAMBIGUATION, FOUND, MISSING, SECTION, VIA_REDIRECT, Move, Redirect
from wir_core.providers.wikimedia import MAX_MOVE_LOOKUPS, MAX_PV_REQUESTS

SITEMATRIX = {"sitematrix": {
    "count": 3,
    "0": {"code": "cs", "name": "čeština", "localname": "Czech", "site": [
        {"url": "https://cs.wikipedia.org", "dbname": "cswiki", "code": "wiki"},
        {"url": "https://cs.wiktionary.org", "dbname": "cswiktionary", "code": "wiktionary"}]},
    "1": {"code": "be-tarask", "name": "тарашкевіца", "localname": "Belarusian (Taraškievica)", "site": [
        {"url": "https://be-tarask.wikipedia.org", "dbname": "be_x_oldwiki", "code": "wiki"}]},
    "2": {"code": "aa", "name": "Qafár af", "localname": "Afar", "site": [
        {"url": "https://aa.wikipedia.org", "dbname": "aawiki", "code": "wiki", "closed": ""}]},
    "specials": []}}


def provider(tmp_path, handler, source="wikipedia"):
    http = HttpClient(Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(handler), min_interval=0)
    return get_provider(source, http)


def sitematrix_or(other):
    def handler(request):
        if request.url.params.get("action") == "sitematrix":
            return httpx.Response(200, json=SITEMATRIX)
        return other(request)
    return handler


def test_resolve_lang_valid_alias_closed_unknown(tmp_path):
    p = provider(tmp_path, sitematrix_or(lambda r: pytest.fail("unexpected")))
    assert p.resolve_lang("cs") == ("cs", None)
    lang, note = p.resolve_lang("CZ")
    assert lang == "cs" and "cz" in note.lower()
    assert p.resolve_lang("be-tarask") == ("be-tarask", None)
    for bad in ("aa", "xx"):
        with pytest.raises(WirError) as e:
            p.resolve_lang(bad)
        assert e.value.code == "UNKNOWN_LANG"
    assert p.lang_name("cs") == "Czech"
    assert p.aqs_project("cs") == "cs.wikipedia"
    assert p.article_url("cs", "Přerušovaný půst") == "https://cs.wikipedia.org/wiki/P%C5%99eru%C5%A1ovan%C3%BD_p%C5%AFst"


def test_wiktionary_has_no_wikidata_capability(tmp_path):
    p = provider(tmp_path, sitematrix_or(lambda r: pytest.fail("unexpected")), source="wiktionary")
    assert "wikidata" not in p.capabilities and p.resolve_lang("cs") == ("cs", None)


QUERY = {"batchcomplete": True, "query": {
    "normalized": [{"fromencoded": False, "from": "astronomy", "to": "Astronomy"}],
    "redirects": [{"from": "Astronomical", "to": "Astronomy"},
                  {"from": "OMAD", "to": "Intermittent fasting", "tofragment": "One meal a day"}],
    "pages": [
        {"pageid": 1, "ns": 0, "title": "Astronomy", "length": 90000,
         "pageprops": {"wikibase_item": "Q333"}, "extract": "Astronomy is a natural science."},
        {"pageid": 2, "ns": 0, "title": "Intermittent fasting", "length": 50000,
         "pageprops": {"wikibase_item": "Q1666254"}, "extract": "Intermittent fasting is ..."},
        {"pageid": 3, "ns": 0, "title": "Mercury", "length": 3000,
         "pageprops": {"disambiguation": "", "wikibase_item": "Q1"}},
        {"ns": 0, "title": "Nope nope", "missing": True}]}}
REVISION = {"query": {"pages": [{"title": "X", "revisions": [{"timestamp": "2020-10-28T12:00:00Z"}]}]}}


def test_inspect_status_mapping(tmp_path):
    def handler(request):
        if request.url.params.get("prop") == "revisions":
            return httpx.Response(200, json=REVISION)
        return httpx.Response(200, json=QUERY)

    p = provider(tmp_path, sitematrix_or(handler))
    info = p.inspect("en", ["astronomy", "Astronomical", "OMAD", "Mercury", "Nope nope"])
    assert info["astronomy"].status == FOUND and info["astronomy"].title == "Astronomy"
    assert info["astronomy"].qid == "Q333" and info["astronomy"].created == date(2020, 10, 28)
    assert info["Astronomical"].status == VIA_REDIRECT and info["Astronomical"].title == "Astronomy"
    assert info["OMAD"].status == SECTION and info["OMAD"].fragment == "One meal a day"
    assert info["Mercury"].status == DISAMBIGUATION
    assert info["Nope nope"].status == MISSING and info["Nope nope"].title is None


def test_mediawiki_error_is_wirerror(tmp_path):
    p = provider(tmp_path, sitematrix_or(lambda r: httpx.Response(200, json={"error": {"code": "badvalue", "info": "bad"}})))
    with pytest.raises(WirError) as e:
        p.search_in_wiki("cs", "x")
    assert e.value.code == "MEDIAWIKI_ERROR"


def test_closed_wiki_says_closed(tmp_path):
    p = provider(tmp_path, sitematrix_or(lambda r: pytest.fail("unexpected")))
    with pytest.raises(WirError) as e:
        p.resolve_lang("aa")
    assert "closed" in e.value.message and "SiteMatrix" in e.value.fix


def test_transient_mediawiki_error_is_network(tmp_path):
    p = provider(tmp_path, lambda r: httpx.Response(200, json={"error": {"code": "maxlag", "info": "lag"}}))
    with pytest.raises(WirError) as e:
        p.search_in_wiki("cs", "x")
    assert e.value.exit_code == EXIT_NETWORK


def test_inspect_chains_normalization_sections_and_variants(tmp_path):
    answer = {"query": {
        "normalized": [{"from": "astronomical", "to": "Astronomical"}],
        "converted": [{"from": "Астрономиja", "to": "Астрономија"}],
        "redirects": [{"from": "Astronomical", "to": "Astronomy"},
                      {"from": "A", "to": "B"}, {"from": "B", "to": "C", "tofragment": "Part"}],
        "pages": [{"ns": 0, "title": "Astronomy", "length": 1}, {"ns": 0, "title": "C", "length": 1},
                  {"ns": 0, "title": "Intermittent fasting", "length": 1},
                  {"ns": 0, "title": "Астрономија", "length": 1}]}}
    seen = []

    def handler(request):
        if request.url.params.get("prop") == "revisions":
            return httpx.Response(200, json=REVISION)
        seen.append(request.url.params["titles"])
        return httpx.Response(200, json=answer)

    p = provider(tmp_path, sitematrix_or(handler))
    info = p.inspect("en", ["astronomical", "A", "Intermittent fasting#Types", "Астрономиja"])
    assert info["astronomical"].status == VIA_REDIRECT and info["astronomical"].title == "Astronomy"
    assert info["A"].status == SECTION and (info["A"].title, info["A"].fragment) == ("C", "Part")
    sec = info["Intermittent fasting#Types"]
    assert sec.status == SECTION and (sec.title, sec.fragment) == ("Intermittent fasting", "Types")
    assert info["Астрономиja"].status == FOUND and info["Астрономиja"].title == "Астрономија"
    assert "#" not in seen[0]


def pageviews_page(title, views):
    return {"ns": 0, "title": title, "pageviews": views}


def test_views_60d_budget_leaves_unchecked_none(tmp_path):
    titles = [f"T{i}" for i in range(10)]
    calls = []

    def handler(request):
        calls.append(1)
        n = len(calls) - 1
        pages = [pageviews_page(f"T{n}", {"2026-09-01": 3, "2026-09-02": None})]
        return httpx.Response(200, json={"continue": {"pvipcontinue": f"T{n + 1}", "continue": "||"},
                                         "query": {"pages": pages}})

    p = provider(tmp_path, handler)
    views = p.views_60d("en", titles)
    assert len(calls) == MAX_PV_REQUESTS
    assert [views[f"T{i}"] for i in range(MAX_PV_REQUESTS)] == [3] * MAX_PV_REQUESTS
    assert all(views[f"T{i}"] is None for i in range(MAX_PV_REQUESTS, 10))


def test_views_60d_maps_every_spelling_and_keeps_zero(tmp_path):
    answer = {"query": {"normalized": [{"from": "astronomy", "to": "Astronomy"},
                                       {"from": "Astronomy ", "to": "Astronomy"}],
                        "pages": [pageviews_page("Astronomy", {"2026-09-01": 5}),
                                  pageviews_page("Quiet", {"2026-09-01": 0})]}}
    p = provider(tmp_path, lambda r: httpx.Response(200, json=answer))
    assert p.views_60d("en", ["astronomy", "Astronomy ", "Quiet"]) == {"astronomy": 5, "Astronomy ": 5, "Quiet": 0}


def test_redirects_follow_continuation(tmp_path):
    def handler(request):
        params = request.url.params
        if params.get("prop") == "pageviews":
            return httpx.Response(200, json={"query": {"pages": [pageviews_page("R1", {"d": 7})]}})
        if "rdcontinue" not in params:
            return httpx.Response(200, json={"continue": {"rdcontinue": "2|R2", "continue": "||"}, "query": {
                "pages": [{"title": "Main", "redirects": [{"title": "R1"}]}]}})
        return httpx.Response(200, json={"query": {
            "pages": [{"title": "Main", "redirects": [{"title": "R2", "fragment": "Sec"}]}]}})

    reds = provider(tmp_path, handler).redirects("en", "Main")
    assert reds == [Redirect("R1", 7, None), Redirect("R2", None, "Sec")]


def test_moves_keep_only_article_renames(tmp_path, capsys):
    events = {"query": {"logevents": [
        {"ns": 0, "title": "Twitter", "timestamp": "2026-02-25T10:00:00Z",
         "params": {"target_ns": 0, "target_title": "X (social network)"}},
        {"ns": 0, "title": "Twitter", "timestamp": "2026-03-11T10:00:00Z",
         "params": {"target_ns": 118, "target_title": "Draft:Move/Twitter", "suppressredirect": True}},
        {"ns": 2, "title": "User:A/Twitter", "timestamp": "2026-03-12T10:00:00Z",
         "params": {"target_ns": 0, "target_title": "Twitter"}}]}}
    calls = []
    p = provider(tmp_path, lambda r: calls.append(1) or httpx.Response(200, json=events))
    moves = p.moves("en", ["Twitter"] + [f"R{i}" for i in range(MAX_MOVE_LOOKUPS + 5)])
    assert moves == [Move(date(2026, 2, 25), "Twitter", "X (social network)")]
    assert len(calls) == MAX_MOVE_LOOKUPS
    assert f"{MAX_MOVE_LOOKUPS} of {MAX_MOVE_LOOKUPS + 6}" in capsys.readouterr().err
