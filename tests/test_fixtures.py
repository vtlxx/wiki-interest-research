import json

import httpx
import pytest

from wir_core.fixtures import FixtureTransport, fixture_name


def test_fixture_name_stable():
    url = "https://wikimedia.org/api/rest_v1/metrics/x"
    assert fixture_name(url) == fixture_name(url)
    assert fixture_name(url).endswith(".json") and len(fixture_name(url)) == 21


def test_replay_hit_and_miss(tmp_path):
    url = "https://example.org/a?b=1"
    (tmp_path / fixture_name(url)).write_text(json.dumps({"url": url, "status": 200, "body": '{"x": 1}'}))
    client = httpx.Client(transport=FixtureTransport([tmp_path]))
    assert client.get(url).json() == {"x": 1}
    with pytest.raises(AssertionError, match="no fixture"):
        client.get("https://example.org/other")


def test_non_strict_miss_is_404(tmp_path):
    t = FixtureTransport([tmp_path], strict=False)
    resp = httpx.Client(transport=t).get("https://example.org/zzz")
    assert resp.status_code == 404 and t.misses == ["https://example.org/zzz"]
