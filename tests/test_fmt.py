from datetime import date

from wir_core import fmt


def test_pct():
    assert fmt.pct(0.342) == "+34%"
    assert fmt.pct(-0.056) == "-6%"
    assert fmt.pct(0.0) == "0%"
    assert fmt.pct(0.004) == "0%"
    assert fmt.pct(None) == "—"
    assert fmt.pct(0.34, signed=False) == "34%"


def test_ci():
    assert fmt.ci(0.12, 0.58) == "+12…+58%"
    assert fmt.ci(-0.3, -0.1) == "-30…-10%"


def test_integer_and_share_by_ui():
    assert fmt.integer(1234567, "en") == "1,234,567"
    assert fmt.integer(1234567, "uk") == "1 234 567"
    assert fmt.share(123.456, "en") == "123"
    assert fmt.share(12.345, "en") == "12.3"
    assert fmt.share(1.2345, "uk") == "1,23"
    assert fmt.share(None, "en") == "—"
    assert fmt.share(99.96, "en") == "100" and fmt.share(9.996, "en") == "10.0"


def test_day():
    assert fmt.day(date(2026, 3, 14)) == "2026-03-14"
