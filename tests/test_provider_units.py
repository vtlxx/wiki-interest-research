from datetime import date

import httpx
import pytest

from wir_core.cache import Cache
from wir_core.errors import WirError
from wir_core.net import HttpClient
from wir_core.providers import get_provider
from wir_core.providers.base import DISAMBIGUATION, FOUND, MISSING, SECTION, VIA_REDIRECT

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
