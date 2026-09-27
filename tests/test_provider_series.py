from datetime import date

from wir_core.providers import get_provider


def wp(recorded_client):
    return get_provider("wikipedia", recorded_client("provider_series"))


def test_article_daily_cs(recorded_client):
    series = wp(recorded_client).article_daily("cs", "Přerušovaný půst")
    assert min(series) >= date(2020, 10, 28) and max(series) <= date(2026, 9, 26)
    sept_2024 = sum(v for d, v in series.items() if d.year == 2024 and d.month == 9)
    assert sept_2024 == 393


def test_project_daily_uk(recorded_client):
    series = wp(recorded_client).project_daily("uk")
    assert min(series) == date(2015, 7, 1) and len(series) > 4000


def test_countries_uk(recorded_client):
    rows = wp(recorded_client).countries("uk", 2026, 8)
    assert rows[0][0] == "UA" and dict(rows)["US"] > 0
