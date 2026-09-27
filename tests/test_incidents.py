from datetime import date

from wir_core import incidents


def test_load_parses_dates():
    items = incidents.load()
    assert all(i.start <= i.end for i in items)
    assert {i.severity for i in items} <= {"low", "medium", "high"}


def test_overlap_all_projects_and_specific():
    ids = {i.id for i in incidents.overlapping("cs", date(2024, 9, 1), date(2026, 8, 31))}
    assert {"bots_2025_11", "bots_2025_brazil"} <= ids and "language_shift_2022" not in ids
    uk = {i.id for i in incidents.overlapping("uk", date(2021, 1, 1), date(2022, 6, 30))}
    assert {"undercount_2021", "language_shift_2022"} <= uk


def test_overlap_severity_filter_and_none():
    high = incidents.overlapping("pl", date(2024, 9, 1), date(2026, 8, 31), severities={"high"})
    assert [i.id for i in high] == ["bots_2025_11"]
    assert incidents.overlapping("pl", date(2023, 1, 1), date(2023, 12, 31)) == []
