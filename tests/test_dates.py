from datetime import date

from llm_org_cost_monitor.dates import parse_cli_range, range_for_period


def test_mtd_boundaries():
    date_range = range_for_period("mtd", today=date(2026, 7, 5))

    assert date_range.start == date(2026, 7, 1)
    assert date_range.end_exclusive == date(2026, 7, 6)
    assert date_range.openai_start_seconds() == 1782864000
    assert date_range.anthropic_end() == "2026-07-06T00:00:00Z"


def test_last_7d_includes_today():
    date_range = range_for_period("last-7d", today=date(2026, 7, 5))

    assert date_range.start == date(2026, 6, 29)
    assert date_range.end_inclusive == date(2026, 7, 5)


def test_cli_range_treats_end_as_inclusive():
    date_range = parse_cli_range("2026-07-01", "2026-07-05")

    assert date_range.start == date(2026, 7, 1)
    assert date_range.end_exclusive == date(2026, 7, 6)
