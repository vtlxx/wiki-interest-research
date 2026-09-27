from wir_core.cache import TTL_404, Cache


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_put_get_roundtrip(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put("k", 200, b'{"a": 1}', 60)
    assert c.get("k") == (200, b'{"a": 1}')


def test_ttl_expiry_and_allow_stale(tmp_path):
    clock = Clock()
    c = Cache(tmp_path / "c.sqlite", clock=clock)
    c.put("k", 404, b"", TTL_404)
    clock.t += TTL_404 + 1
    assert c.get("k") is None
    assert c.get("k", allow_stale=True) == (404, b"")


def test_json_helpers_and_persistence(tmp_path):
    path = tmp_path / "c.sqlite"
    c = Cache(path)
    c.put_json("geo:2026-01-01:Q1", [{"country": "UA", "views": 120}], 60)
    c.close()
    again = Cache(path)
    assert again.get_json("geo:2026-01-01:Q1") == [{"country": "UA", "views": 120}]
    assert again.fetched_at("geo:2026-01-01:Q1") is not None
    assert again.get_json("missing") is None


def test_overwrite_updates_value(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.put("k", 200, b"1", 60)
    c.put("k", 200, b"2", 60)
    assert c.get("k") == (200, b"2")


def test_latest_by_prefix(tmp_path):
    clock = Clock(100.0)
    c = Cache(tmp_path / "c.sqlite", clock=clock)
    c.put("https://a/x/20260101", 200, b"old", 1)
    clock.t = 200.0
    c.put("https://a/x/20260102", 200, b"new", 1)
    c.put("https://a/y/20260103", 200, b"other", 1)
    assert c.latest("https://a/x/") == ("https://a/x/20260102", 200, b"new")
    assert c.latest("https://a/z/") is None
