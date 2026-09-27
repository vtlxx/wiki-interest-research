from datetime import date

import pytest

from wir_core.cache import Cache
from wir_core.net import HttpClient
from wir_core.providers import get_provider

pytestmark = pytest.mark.live


def test_live_dp_sun_in_canada(tmp_path):
    p = get_provider("wikipedia", HttpClient(Cache(tmp_path / "c.sqlite")))
    rows = p.spike_geo(date(2026, 9, 26), ["Q525"])["Q525"]
    assert any(r.code == "CA" and r.project == "en.wikipedia" and r.views >= 91 for r in rows)
