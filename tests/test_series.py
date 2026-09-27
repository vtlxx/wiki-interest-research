from datetime import date

import pandas as pd
import pytest

from wir_core import series as sr
from wir_core.providers.base import Move, Redirect


def test_fill_daily_zero_fills_and_clips():
    s = sr.fill_daily({date(2026, 1, 1): 5, date(2026, 1, 3): 2, date(2025, 12, 1): 9},
                      date(2026, 1, 1), date(2026, 1, 4))
    assert list(s.values) == [5, 0, 2, 0]
    assert s.index[0] == pd.Timestamp("2026-01-01") and s.dtype == float


def test_fill_daily_empty():
    assert sr.fill_daily({}, date(2026, 1, 1), date(2026, 1, 2)).tolist() == [0.0, 0.0]


def test_last_complete_day_uses_project_series_and_yesterday():
    assert sr.last_complete_day({date(2026, 9, 25): 1}, date(2026, 9, 27)) == date(2026, 9, 25)
    assert sr.last_complete_day({date(2026, 9, 28): 1}, date(2026, 9, 27)) == date(2026, 9, 26)
    assert sr.last_complete_day({}, date(2026, 9, 27)) == date(2026, 9, 25)


@pytest.mark.parametrize("last_day,expected", [
    (date(2026, 9, 25), (date(2026, 8, 1), date(2026, 8, 31))),
    (date(2026, 8, 31), (date(2026, 8, 1), date(2026, 8, 31))),
    (date(2026, 3, 1), (date(2026, 2, 1), date(2026, 2, 28)))])
def test_month_bounds(last_day, expected):
    assert sr.month_bounds(last_day) == expected


def test_add_months():
    assert sr.add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert sr.add_months(date(2026, 8, 1), -23) == date(2024, 9, 1)


def test_window_bounds_period_and_explicit():
    assert sr.window_bounds(date(2026, 8, 1), 24, None, None) == (date(2024, 9, 1), date(2026, 8, 31))
    assert sr.window_bounds(date(2026, 8, 1), 24, "2025-01", "2025-06") == (date(2025, 1, 1), date(2025, 6, 30))
    assert sr.window_bounds(date(2026, 8, 1), 24, "2025-01", "2027-01") == (date(2025, 1, 1), date(2026, 8, 31))
    assert sr.window_bounds(date(2016, 1, 1), 24, None, None)[0] == date(2015, 7, 1)


def test_young_start():
    assert sr.young_start(date(2020, 10, 28), date(2024, 9, 1)) == (date(2024, 9, 1), False)
    assert sr.young_start(date(2025, 3, 10), date(2024, 9, 1)) == (date(2025, 7, 1), True)
    assert sr.young_start(None, date(2024, 9, 1)) == (date(2024, 9, 1), False)


def test_select_redirects_threshold_moves_unchecked_dominant():
    reds = [Redirect("5:2 diet", 3276, None), Redirect("OMAD", 413, "One meal a day"),
            Redirect("Tiny", 3, None), Redirect("Old title", 0, None), Redirect("Unknown", None, None)]
    sel = sr.select_redirects(reds, main_views_60d=7458, move_sources={"Old title"})
    assert sel.included == ["5:2 diet", "OMAD", "Old title"]
    assert sel.unchecked == ["Unknown"]
    assert sel.coverage == pytest.approx((7458 + 3276 + 413 + 0) / (7458 + 3276 + 413 + 3 + 0))
    assert sel.dominant is None
    big = sr.select_redirects([Redirect("Alias", 9000, None)], main_views_60d=5000, move_sources=set())
    assert big.dominant == "Alias"


def test_select_redirects_no_data():
    sel = sr.select_redirects([], main_views_60d=None, move_sources=set())
    assert sel.included == [] and sel.coverage is None



def test_select_redirects_unknown_main_views_claims_no_coverage_or_dominance():
    reds = [Redirect("Alias", 9000, None), Redirect("Tiny", 3, None), Redirect("Old title", None, None),
            Redirect("Unknown", None, None)]
    sel = sr.select_redirects(reds, main_views_60d=None, move_sources={"Old title"})
    known_zero = sr.select_redirects(reds, main_views_60d=0, move_sources={"Old title"})
    assert sel.included == known_zero.included == ["Alias", "Tiny", "Old title"]
    assert sel.unchecked == ["Unknown"]
    assert sel.coverage is None and sel.dominant is None
    assert known_zero.dominant == "Alias"             # a known zero main article keeps the flag

def test_combine_and_monthly_and_share():
    idx = pd.date_range("2026-01-01", "2026-02-28", freq="D")
    a = pd.Series(1.0, index=idx)
    b = pd.Series(2.0, index=idx[:10])
    topic = sr.combine([a, b])
    assert topic.iloc[0] == 3.0 and topic.iloc[-1] == 1.0
    m = sr.monthly(topic, date(2026, 1, 1), date(2026, 2, 28))
    assert list(m.index) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-02-01")]
    assert list(m.values) == [31 + 20, 28]
    proj = pd.Series([1_000_000.0, 0.0], index=m.index)
    sh = sr.share(m, proj)
    assert sh.iloc[0] == pytest.approx(51.0) and pd.isna(sh.iloc[1])


def test_history_months():
    idx = pd.date_range("2024-01-01", "2026-08-31", freq="D")
    s = pd.Series(0.0, index=idx)
    s[s.index >= "2025-03-15"] = 1.0
    assert sr.history_months(s, None, date(2026, 8, 31)) == 17        # 2025-04 .. 2026-08 complete months
    assert sr.history_months(s, date(2024, 2, 1), date(2026, 8, 31)) == 31


def test_renamed_within():
    moves = [Move(date(2026, 2, 25), "Twitter", "X (social network)"), Move(date(2010, 1, 1), "A", "B")]
    assert sr.renamed_within(moves, date(2024, 9, 1), date(2026, 8, 31)) == [moves[0]]


def test_first_full_month():
    assert sr.first_full_month(date(2024, 3, 1)) == date(2024, 3, 1)
    assert sr.first_full_month(date(2024, 12, 2)) == date(2025, 1, 1)
