import pytest

from wir_core.cache import Cache
from wir_core.net import HttpClient, encode_title

AQS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
pytestmark = pytest.mark.live


def test_live_per_article_monthly(tmp_path):
    c = HttpClient(Cache(tmp_path / "c.sqlite"))
    url = f"{AQS}/per-article/cs.wikipedia/all-access/user/{encode_title('Přerušovaný půst')}/monthly/2024090100/2024103100"
    data = c.get_json(url, ttl=60)
    assert [i["timestamp"] for i in data["items"]] == ["2024090100", "2024100100"]
    assert all(i["views"] > 0 for i in data["items"])


def test_live_404_is_none(tmp_path):
    c = HttpClient(Cache(tmp_path / "c.sqlite"))
    url = f"{AQS}/per-article/cs.wikipedia/all-access/user/{encode_title('Zzzz neexistuje 12345')}/daily/20260101/20260105"
    assert c.get_json(url, ttl=60) is None
