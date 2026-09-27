from datetime import date

import httpx
import pytest

from wir_core.cache import Cache
from wir_core.errors import WirError
from wir_core.net import HttpClient
from wir_core.providers import get_provider

ITEMS = {"items": [
    {"project": "cs.wikipedia", "article": "X", "granularity": "daily", "timestamp": "2026092500", "views": 5},
    {"project": "cs.wikipedia", "article": "X", "granularity": "daily", "timestamp": "2026092300", "views": 2}]}


def make(tmp_path, handler, offline=False, cache=None):
    cache = cache or Cache(tmp_path / "c.sqlite")
    http = HttpClient(cache, transport=httpx.MockTransport(handler), min_interval=0, offline=offline)
    return get_provider("wikipedia", http), cache


def test_article_daily_parses_and_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    seen = []
    p, _ = make(tmp_path, lambda r: seen.append(str(r.url)) or httpx.Response(200, json=ITEMS))
    assert p.article_daily("cs", "Přerušovaný půst") == {date(2026, 9, 25): 5, date(2026, 9, 23): 2}
    assert seen[0].endswith("/per-article/cs.wikipedia/all-access/user/"
                            "P%C5%99eru%C5%A1ovan%C3%BD_p%C5%AFst/daily/20150701/20260926")


def test_article_daily_404_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    p, _ = make(tmp_path, lambda r: httpx.Response(404, json={"title": "Not found."}))
    assert p.article_daily("cs", "Nic") == {}


def test_project_daily_url(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    seen = []
    p, _ = make(tmp_path, lambda r: seen.append(str(r.url)) or httpx.Response(200, json=ITEMS))
    p.project_daily("uk")
    assert seen[0].endswith("/aggregate/uk.wikipedia/all-access/user/daily/2015070100/2026092600")


def test_offline_falls_back_to_latest_cached_series(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    online, cache = make(tmp_path, lambda r: httpx.Response(200, json=ITEMS))
    online.article_daily("cs", "X")
    monkeypatch.setenv("WIR_TODAY", "2026-09-30")      # three days later, offline
    offline, _ = make(tmp_path, lambda r: pytest.fail("network used"), offline=True, cache=cache)
    assert offline.article_daily("cs", "X")[date(2026, 9, 25)] == 5
    with pytest.raises(WirError):
        offline.article_daily("cs", "Never fetched")


def test_countries_skip_unknown(tmp_path):
    body = {"items": [{"project": "uk.wikipedia", "access": "all-access", "year": "2026", "month": "08",
                       "countries": [{"country": "UA", "views": "10000000-99999999", "rank": 1, "views_ceil": 32015000},
                                     {"country": "--", "views": "100-999", "rank": 5, "views_ceil": 999},
                                     {"country": "US", "views": "1000000-9999999", "rank": 2, "views_ceil": 5533000}]}]}
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=body))
    assert p.countries("uk", 2026, 8) == [("UA", 32015000), ("US", 5533000)]


def test_spike_geo_streams_once_and_caches(tmp_path):
    calls = []
    tsv = "Canada\tCA\ten.wikipedia\t26751\tSun\tQ525\t126\nFrance\tFR\tfr.wikipedia\t9\tSoleil\tQ525\t200\n"

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=tsv)

    p, _ = make(tmp_path, handler)
    first = p.spike_geo(date(2026, 9, 26), ["Q525", "Q1"])
    again = p.spike_geo(date(2026, 9, 26), ["Q525", "Q1"])
    assert len(calls) == 1 and calls[0].endswith("/country_project_page/2026-09-26.tsv")
    assert first == again and len(first["Q525"]) == 2 and first["Q1"] == []


def test_spike_geo_before_dataset_start(tmp_path):
    p, _ = make(tmp_path, lambda r: pytest.fail("network used"))
    assert p.spike_geo(date(2022, 1, 1), ["Q525"]) == {"Q525": []}


def test_spike_geo_mid_file_failure_caches_nothing(tmp_path, monkeypatch):
    """HANDOFF open issue #6: iter_lines can raise WirError after already yielding some lines (connection lost
    mid-file). Those partial lines must not be cached or aggregated; a later call must re-download the file."""
    p, cache = make(tmp_path, lambda r: pytest.fail("network used"))

    def broken_iter_lines(url):
        yield "Canada\tCA\ten.wikipedia\t26751\tSun\tQ525\t126"
        raise WirError("NETWORK", "connection lost mid-file")

    monkeypatch.setattr(p.http, "iter_lines", broken_iter_lines)
    with pytest.raises(WirError):
        p.spike_geo(date(2026, 9, 26), ["Q525"])
    assert cache.get_json("dp:2026-09-26:Q525") is None
