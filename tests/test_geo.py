import pytest

from wir_core.geo import parse_dp_lines, spike_breakdown, top_countries
from wir_core.providers.base import GeoRow

LINES = [
    "Canada\tCA\ten.wikipedia\t26751\tSun\tQ525\t126",
    "Canada\tCA\tfr.wikipedia\t99\tSoleil\tQ525\t300",
    "France\tFR\tfr.wikipedia\t99\tSoleil\tQ525\t100",
    "broken line",
    "Albania\tAL\ten.wikipedia\t1\tRoblox\tQ692989\t290",
    "X\tXX\ten.wikipedia\t2\tY\tQ525\tnot-a-number",
]


def test_parse_keeps_only_requested_qids():
    rows = parse_dp_lines(LINES, {"Q525", "Q1"})
    assert set(rows) == {"Q525", "Q1"} and rows["Q1"] == []
    assert GeoRow("Canada", "CA", "en.wikipedia", "Sun", "Q525", 126) in rows["Q525"]
    assert len(rows["Q525"]) == 3


def test_spike_breakdown_shares_within_project():
    rows = parse_dp_lines(LINES, {"Q525"})["Q525"]
    assert spike_breakdown(rows, "fr.wikipedia") == [("CA", pytest.approx(0.75)), ("FR", pytest.approx(0.25))]
    assert spike_breakdown(rows, "de.wikipedia") == []


def test_top_countries_sums_months():
    months = [[("UA", 30), ("US", 5), ("PL", 2)], [("UA", 34), ("US", 6), ("DE", 3)]]
    top = top_countries(months, n=2)
    assert [c for c, _ in top] == ["UA", "US"]
    assert top[0][1] == pytest.approx(64 / 80)
