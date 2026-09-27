import json

import httpx
import pytest

from wir_core.cache import Cache
from wir_core.errors import EXIT_NETWORK, EXIT_NODATA, WirError
from wir_core.fixtures import FixtureTransport
from wir_core.net import BudgetExceeded, Deadline, HttpClient, build_url, encode_title


class FakeTime:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_client(tmp_path, handler, **kw):
    ft = FakeTime()
    client = HttpClient(Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(handler),
                        sleep=ft.sleep, clock=ft.clock, **kw)
    return client, ft


def test_encode_title():
    assert encode_title("AC/DC") == "AC%2FDC"
    assert encode_title("Intermittent fasting") == "Intermittent_fasting"
    assert encode_title("What?") == "What%3F"
    assert encode_title("Přerušovaný půst") == "P%C5%99eru%C5%A1ovan%C3%BD_p%C5%AFst"


def test_build_url_sorted_params():
    assert build_url("https://x.org/api", {"b": 2, "a": "q w"}) == "https://x.org/api?a=q%20w&b=2"
    assert build_url("https://x.org/api") == "https://x.org/api"


def test_json_cached_and_user_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("WIR_CONTACT", "me@test")
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, json={"items": [1]})

    client, _ = make_client(tmp_path, handler)
    assert client.get_json("https://x.org/a", ttl=60) == {"items": [1]}
    assert client.get_json("https://x.org/a", ttl=60) == {"items": [1]}
    assert client.requests_made == 1 and "me@test" in seen[0]


def test_404_is_none_and_cached(tmp_path):
    calls = []
    client, _ = make_client(tmp_path, lambda r: calls.append(1) or httpx.Response(404, json={"title": "Not found."}))
    assert client.get_json("https://x.org/none", ttl=60) is None
    assert client.get_json("https://x.org/none", ttl=60) is None
    assert len(calls) == 1


def test_retry_after_honoured(tmp_path):
    answers = [httpx.Response(429, text="You are making too many requests", headers={"retry-after": "7"}),
               httpx.Response(200, json={"ok": 1})]
    client, ft = make_client(tmp_path, lambda r: answers.pop(0))
    assert client.get_json("https://x.org/r", ttl=60) == {"ok": 1}
    assert 7.0 in ft.sleeps


def test_rate_limited_after_retries(tmp_path):
    client, ft = make_client(tmp_path, lambda r: httpx.Response(429, text="slow"), max_retries=2)
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/r", ttl=60)
    assert e.value.code == "RATE_LIMITED" and e.value.exit_code == EXIT_NETWORK
    assert ft.sleeps.count(5.0) == 1 and ft.sleeps.count(10.0) == 1


def test_throttle_spacing(tmp_path):
    client, ft = make_client(tmp_path, lambda r: httpx.Response(200, json={}), min_interval=0.6)
    client.get_json("https://x.org/1", ttl=60)
    client.get_json("https://x.org/2", ttl=60)
    assert ft.sleeps == [pytest.approx(0.6)]


def test_offline_miss_and_stale_hit(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", clock=lambda: 0.0)
    cache.put("https://x.org/s", 200, json.dumps({"v": 1}).encode(), 1)
    offline = HttpClient(Cache(tmp_path / "c.sqlite", clock=lambda: 10_000.0), offline=True,
                         transport=httpx.MockTransport(lambda r: pytest.fail("network used")))
    assert offline.get_json("https://x.org/s", ttl=60) == {"v": 1}
    with pytest.raises(WirError) as e:
        offline.get_json("https://x.org/missing", ttl=60)
    assert e.value.code == "NOT_CACHED" and e.value.exit_code == EXIT_NODATA


def test_deadline_stops_before_network(tmp_path):
    t = {"now": 0.0}
    deadline = Deadline(5, clock=lambda: t["now"])
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, json={}), deadline=deadline)
    t["now"] = 6.0
    with pytest.raises(BudgetExceeded):
        client.get_json("https://x.org/late", ttl=60)


def test_transport_error_is_network_error(tmp_path):
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    client, _ = make_client(tmp_path, boom, max_retries=1)
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/down", ttl=60)
    assert e.value.code == "NETWORK"


def test_bad_request_raises_usage(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(400, json={"detail": "bad date"}))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/bad", ttl=60)
    assert e.value.code == "BAD_REQUEST" and "bad date" in e.value.message


def test_record_then_replay(tmp_path):
    rec = tmp_path / "rec"
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, json={"n": 5}), record_dir=rec)
    client.get_json("https://x.org/rec", {"q": "é"}, ttl=60)
    replay = HttpClient(Cache(tmp_path / "other.sqlite"), transport=FixtureTransport([rec]))
    assert replay.get_json("https://x.org/rec", {"q": "é"}, ttl=60) == {"n": 5}


def test_iter_lines_stream_and_404(tmp_path):
    def handler(request):
        if request.url.path.endswith("missing.tsv"):
            return httpx.Response(404)
        return httpx.Response(200, text="a\tb\nc\td\n")

    client, _ = make_client(tmp_path, handler)
    assert list(client.iter_lines("https://x.org/day.tsv")) == ["a\tb", "c\td"]
    assert list(client.iter_lines("https://x.org/missing.tsv")) == []


# -- review follow-ups ---------------------------------------------------------------------------

class ChunkedStream(httpx.SyncByteStream):
    """Yields the given chunks, then raises the given exception (a connection dropped mid-file)."""

    def __init__(self, chunks, exc=None):
        self.chunks = chunks
        self.exc = exc

    def __iter__(self):
        yield from self.chunks
        if self.exc:
            raise self.exc


@pytest.mark.parametrize("title", ["Інтервальне голодування", "AC/DC", "What?", "Intermittent fasting", "50% + 1 & #"])
def test_record_then_replay_encoded_titles(tmp_path, title):
    rec = tmp_path / "rec"
    url = f"https://x.org/per-article/{encode_title(title)}/daily/20260101/20260105"
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, json={"t": title}), record_dir=rec)
    client.get_json(url, ttl=60)
    replay = HttpClient(Cache(tmp_path / "other.sqlite"), transport=FixtureTransport([rec]))
    assert replay.get_json(url, ttl=60) == {"t": title}


def test_redirect_recorded_under_requested_url(tmp_path):
    def handler(request):
        if request.url.path == "/astronomy":
            return httpx.Response(301, headers={"location": "https://x.org/Astronomy"})
        return httpx.Response(200, json={"v": 22451})

    rec = tmp_path / "rec"
    client, _ = make_client(tmp_path, handler, record_dir=rec)
    assert client.get_json("https://x.org/astronomy", ttl=60) == {"v": 22451}
    replay = HttpClient(Cache(tmp_path / "other.sqlite"), transport=FixtureTransport([rec]))
    assert replay.get_json("https://x.org/astronomy", ttl=60) == {"v": 22451}


def test_default_is_four_attempts(tmp_path):
    calls = []
    client, ft = make_client(tmp_path, lambda r: calls.append(1) or httpx.Response(503))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/busy", ttl=60)
    assert len(calls) == 4 and client.requests_made == 4
    assert e.value.code == "UPSTREAM_ERROR" and e.value.exit_code == EXIT_NETWORK
    assert [s for s in ft.sleeps if s >= 5] == [5.0, 10.0, 20.0]


@pytest.mark.parametrize("header, expected", [("600", 60.0), ("-5", 5.0), ("nan", 5.0), ("soon", 5.0)])
def test_retry_after_is_sane(tmp_path, header, expected):
    answers = [httpx.Response(429, headers={"retry-after": header}), httpx.Response(200, json={})]
    client, ft = make_client(tmp_path, lambda r: answers.pop(0))
    client.get_json("https://x.org/r", ttl=60)
    assert ft.sleeps == [expected]


@pytest.mark.parametrize("status", [400, 404])
def test_client_errors_not_retried(tmp_path, status):
    calls = []
    client, _ = make_client(tmp_path, lambda r: calls.append(1) or httpx.Response(status, json=["not", "a", "dict"]))
    try:
        client.get_json("https://x.org/e", ttl=60)
    except WirError as e:
        assert e.code == "BAD_REQUEST"
    assert len(calls) == 1


def test_forbidden_mentions_contact(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(403, text="Please set a user-agent"))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/f", ttl=60)
    assert e.value.code == "FORBIDDEN" and e.value.exit_code == EXIT_NETWORK and "WIR_CONTACT" in e.value.fix


def test_unretried_5xx_is_upstream_error(tmp_path):
    calls = []
    client, _ = make_client(tmp_path, lambda r: calls.append(1) or httpx.Response(501))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/u", ttl=60)
    assert e.value.code == "UPSTREAM_ERROR" and e.value.exit_code == EXIT_NETWORK and len(calls) == 1


def test_non_json_200_says_so(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(200, text="<html>captive portal</html>"))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/html", ttl=60)
    assert e.value.code == "UPSTREAM_ERROR" and "not JSON" in e.value.message


def test_redirect_loop_is_network_error(tmp_path):
    client, _ = make_client(tmp_path, lambda r: httpx.Response(302, headers={"location": str(r.url)}))
    with pytest.raises(WirError) as e:
        client.get_json("https://x.org/loop", ttl=60)
    assert e.value.code == "NETWORK" and e.value.exit_code == EXIT_NETWORK


def test_backoff_does_not_overrun_deadline(tmp_path):
    ft = FakeTime()
    deadline = Deadline(8, clock=ft.clock)
    client = HttpClient(Cache(tmp_path / "c.sqlite"), transport=httpx.MockTransport(lambda r: httpx.Response(429)),
                        sleep=ft.sleep, clock=ft.clock, deadline=deadline)
    with pytest.raises(BudgetExceeded):
        client.get_json("https://x.org/r", ttl=60)
    assert ft.t <= 8


def test_build_url_appends_to_existing_query():
    assert build_url("https://x.org/api?a=1", {"b": 2}) == "https://x.org/api?a=1&b=2"


def test_iter_lines_retries_then_streams(tmp_path, capsys):
    answers = [httpx.Response(503), httpx.Response(200, text="x\ny\n")]
    client, ft = make_client(tmp_path, lambda r: answers.pop(0))
    assert list(client.iter_lines("https://x.org/day.tsv")) == ["x", "y"]
    assert 5.0 in ft.sleeps and client.requests_made == 2
    assert capsys.readouterr().out == ""


def test_iter_lines_connect_error_is_network(tmp_path):
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    client, _ = make_client(tmp_path, boom, max_retries=1)
    with pytest.raises(WirError) as e:
        list(client.iter_lines("https://x.org/day.tsv"))
    assert e.value.code == "NETWORK" and e.value.exit_code == EXIT_NETWORK


def test_iter_lines_drop_mid_stream_is_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, stream=ChunkedStream([b"a\tb\n"], httpx.ReadError("reset", request=request)))

    client, _ = make_client(tmp_path, handler)
    got = []
    with pytest.raises(WirError) as e:
        for line in client.iter_lines("https://x.org/day.tsv"):
            got.append(line)
    assert got == ["a\tb"] and len(calls) == 1 and e.value.code == "NETWORK"


def test_iter_lines_offline(tmp_path):
    client = HttpClient(Cache(tmp_path / "c.sqlite"), offline=True,
                        transport=httpx.MockTransport(lambda r: pytest.fail("network used")))
    with pytest.raises(WirError) as e:
        list(client.iter_lines("https://x.org/day.tsv"))
    assert e.value.code == "NOT_CACHED" and e.value.exit_code == EXIT_NODATA


def test_nothing_on_stdout(tmp_path, capsys):
    answers = [httpx.Response(429), httpx.Response(200, json={})]
    client, _ = make_client(tmp_path, lambda r: answers.pop(0))
    client.get_json("https://x.org/q", ttl=60)
    captured = capsys.readouterr()
    assert captured.out == "" and "429" in captured.err
