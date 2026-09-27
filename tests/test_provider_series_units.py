from datetime import date

import httpx
import pytest

from wir_core.cache import TTL_OLD, TTL_RECENT, Cache
from wir_core.errors import WirError
from wir_core.net import HttpClient
from wir_core.providers import get_provider
from wir_core.providers.wikimedia import AQS

ITEMS = {"items": [
    {"project": "cs.wikipedia", "article": "X", "granularity": "daily", "timestamp": "2026092500", "views": 5},
    {"project": "cs.wikipedia", "article": "X", "granularity": "daily", "timestamp": "2026092300", "views": 2}]}


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t


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



def test_series_through_reports_the_end_date_of_the_fetched_series(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=ITEMS))
    assert p.series_through("cs", "X") is None and p.series_through("cs") is None
    p.article_daily("cs", "X")
    p.project_daily("cs")
    assert p.series_through("cs", "X") == date(2026, 9, 26)
    assert p.series_through("cs") == date(2026, 9, 26)
    assert p.series_through("cs", "Y") is None and p.series_through("uk") is None


def test_series_through_offline_reports_the_cached_copy_actually_used(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    first, cache = make(tmp_path, lambda r: httpx.Response(200, json=ITEMS))
    first.article_daily("cs", "X")                     # article cached through 2026-09-26
    monkeypatch.setenv("WIR_TODAY", "2026-09-30")
    later, _ = make(tmp_path, lambda r: httpx.Response(200, json=ITEMS), cache=cache)
    later.project_daily("cs")                          # project cached through 2026-09-29
    monkeypatch.setenv("WIR_TODAY", "2026-10-02")
    offline, _ = make(tmp_path, lambda r: pytest.fail("network used"), offline=True, cache=cache)
    offline.article_daily("cs", "X")
    offline.project_daily("cs")
    assert offline.series_through("cs", "X") == date(2026, 9, 26)
    assert offline.series_through("cs") == date(2026, 9, 29)

def test_countries_skip_unknown(tmp_path):
    body = {"items": [{"project": "uk.wikipedia", "access": "all-access", "year": "2026", "month": "08",
                       "countries": [{"country": "UA", "views": "10000000-99999999", "rank": 1, "views_ceil": 32015000},
                                     {"country": "--", "views": "100-999", "rank": 5, "views_ceil": 999},
                                     {"country": "US", "views": "1000000-9999999", "rank": 2, "views_ceil": 5533000}]}]}
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=body))
    assert p.countries("uk", 2026, 8) == [("UA", 32015000), ("US", 5533000)]


def test_countries_uses_recent_ttl_within_last_13_months(tmp_path, monkeypatch):
    """Spec 5.5: a series touching the last 13 months gets the short TTL_RECENT, because Wikimedia can
    still backfill corrections into it (spec A.5); countries() must follow the same rule, not TTL_OLD
    unconditionally (the current month is well within the last 13 months)."""
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    body = {"items": [{"countries": [{"country": "UA", "views_ceil": 100}]}]}
    clock = Clock()
    cache = Cache(tmp_path / "c.sqlite", clock=clock)
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=body), cache=cache)
    p.countries("uk", 2026, 9)
    key = f"{AQS}/top-by-country/uk.wikipedia/all-access/2026/09"
    clock.t += TTL_RECENT + 1
    assert cache.get(key) is None  # expired: cached with TTL_RECENT, not the much longer TTL_OLD


def test_countries_uses_old_ttl_outside_last_13_months(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    body = {"items": [{"countries": [{"country": "UA", "views_ceil": 100}]}]}
    clock = Clock()
    cache = Cache(tmp_path / "c.sqlite", clock=clock)
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=body), cache=cache)
    p.countries("uk", 2020, 1)
    key = f"{AQS}/top-by-country/uk.wikipedia/all-access/2020/01"
    clock.t += TTL_RECENT + 1
    assert cache.get(key) is not None  # not yet expired: TTL_RECENT alone would have expired it
    clock.t += TTL_OLD - TTL_RECENT
    assert cache.get(key) is None  # expired once the full TTL_OLD window has passed


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


def test_spike_geo_does_not_cache_a_daily_file_that_is_not_published_yet(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_TODAY", "2026-09-27")
    tsv = "Canada\tCA\ten.wikipedia\t26751\tSun\tQ525\t126\n"
    published = {"yes": False}
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=tsv) if published["yes"] else httpx.Response(404, text="Not Found")

    p, cache = make(tmp_path, handler)
    with pytest.raises(WirError) as err:
        p.spike_geo(date(2026, 9, 26), ["Q525"])
    assert err.value.code == "NOT_PUBLISHED"
    assert cache.get_json("dp:2026-09-26:Q525", allow_stale=True) is None
    published["yes"] = True
    assert len(p.spike_geo(date(2026, 9, 26), ["Q525"])["Q525"]) == 1 and len(calls) == 2
