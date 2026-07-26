import json
from datetime import date
from decimal import Decimal

import pytest

from llm_org_cost_monitor.ledger import (
    LedgerEntry,
    LedgerError,
    append_entry,
    compute_balance_row,
    find_anchor,
    load_entries,
)
from llm_org_cost_monitor.models import CostRecord

TODAY = date(2026, 7, 25)


def entry(provider="openai", type="set", day="2026-07-01", amount="100.00", currency="USD", note=None):
    return LedgerEntry(
        provider=provider,
        type=type,
        date=date.fromisoformat(day),
        amount=Decimal(amount),
        currency=currency,
        note=note,
    )


def spend(day, amount, currency="USD", provider="openai"):
    return CostRecord(
        provider=provider,
        account_label="OpenAI",
        date=date.fromisoformat(day),
        amount=Decimal(amount),
        currency=currency,
    )


def test_load_missing_file_returns_empty(tmp_path):
    assert load_entries(tmp_path / "missing" / "ledger.json") == []


def test_append_and_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "ledger.json"

    append_entry(path, entry(amount="120.50", note="after top-up"))
    append_entry(path, entry(type="add", day="2026-07-10", amount="25.00"))

    entries = load_entries(path)
    assert [str(e.amount) for e in entries] == ["120.50", "25.00"]
    assert entries[0].note == "after top-up"
    raw = json.loads(path.read_text())
    assert raw["version"] == 1
    assert raw["entries"][0]["amount"] == "120.50"
    assert raw["entries"][1]["amount"] == "25.00"
    assert "note" not in raw["entries"][1]


def test_append_preserves_unknown_keys(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"provider": "openai", "type": "set", "date": "2026-07-01", "amount": "5.00", "source": "console"}
                ],
            }
        )
    )

    append_entry(path, entry(type="add", day="2026-07-02", amount="1.00"))

    raw = json.loads(path.read_text())
    assert raw["entries"][0]["source"] == "console"
    assert len(raw["entries"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"entries": []}),
        json.dumps({"version": 0, "entries": []}),
        json.dumps({"version": 2, "entries": []}),
        json.dumps({"version": 1, "entries": {}}),
        json.dumps({"version": 1, "entries": [{"provider": "google", "type": "set", "date": "2026-07-01", "amount": "1"}]}),
        json.dumps({"version": 1, "entries": [{"provider": "openai", "type": "reset", "date": "2026-07-01", "amount": "1"}]}),
        json.dumps({"version": 1, "entries": [{"provider": "openai", "type": "set", "date": "07/01/2026", "amount": "1"}]}),
        json.dumps({"version": 1, "entries": [{"provider": "openai", "type": "set", "date": "2026-07-01", "amount": 1.0}]}),
        json.dumps({"version": 1, "entries": [{"provider": "openai", "type": "set", "date": "2026-07-01", "amount": "abc"}]}),
    ],
)
def test_load_rejects_invalid_content(tmp_path, payload):
    path = tmp_path / "ledger.json"
    path.write_text(payload)

    with pytest.raises(LedgerError):
        load_entries(path)


def test_load_error_names_path_and_entry_index(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"provider": "openai", "type": "set", "date": "2026-07-01", "amount": "1.00"},
                    {"provider": "openai", "type": "set", "date": "2026-07-02", "amount": "oops"},
                ],
            }
        )
    )

    with pytest.raises(LedgerError) as excinfo:
        load_entries(path)

    assert str(path) in str(excinfo.value)
    assert "entry 1" in str(excinfo.value)


def test_load_wraps_read_oserror_as_ledger_error(tmp_path):
    path = tmp_path / "ledger.json"
    path.mkdir()

    with pytest.raises(LedgerError) as excinfo:
        load_entries(path)

    assert "cannot read" in str(excinfo.value)


def test_append_wraps_write_oserror_as_ledger_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    with pytest.raises(LedgerError) as excinfo:
        append_entry(blocker / "ledger.json", entry())

    assert "cannot write" in str(excinfo.value)


def test_load_tolerates_unknown_entry_keys(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"provider": "openai", "type": "set", "date": "2026-07-01", "amount": "5.00", "source": "console"}
                ],
            }
        )
    )

    entries = load_entries(path)

    assert entries[0].amount == Decimal("5.00")


def test_load_accepts_negative_add_from_hand_edit(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [{"provider": "openai", "type": "add", "date": "2026-07-01", "amount": "-3.00"}],
            }
        )
    )

    entries = load_entries(path)

    assert entries[0].amount == Decimal("-3.00")


def test_compute_set_only():
    row, warnings = compute_balance_row(
        "openai", "OpenAI", [entry(amount="100.00")], [spend("2026-07-02", "10.50")], TODAY
    )

    assert warnings == []
    assert row.anchor_date == date(2026, 7, 1)
    assert row.anchor_amount == Decimal("100.00")
    assert row.purchases_since == Decimal("0")
    assert row.spend_since == Decimal("10.50")
    assert row.estimated_balance == Decimal("89.50")
    assert row.currency == "USD"
    assert row.as_of == TODAY


def test_compute_set_plus_adds():
    entries = [
        entry(amount="100.00"),
        entry(type="add", day="2026-07-05", amount="20.00"),
        entry(type="add", day="2026-07-10", amount="5.00"),
    ]

    row, warnings = compute_balance_row("openai", "OpenAI", entries, [spend("2026-07-02", "10.00")], TODAY)

    assert warnings == []
    assert row.purchases_since == Decimal("25.00")
    assert row.estimated_balance == Decimal("115.00")


def test_compute_ignores_add_before_set():
    entries = [
        entry(type="add", day="2026-06-20", amount="50.00"),
        entry(day="2026-07-01", amount="100.00"),
    ]

    row, _ = compute_balance_row("openai", "OpenAI", entries, [], TODAY)

    assert row.purchases_since == Decimal("0")
    assert row.estimated_balance == Decimal("100.00")


def test_compute_latest_set_wins():
    entries = [
        entry(day="2026-06-01", amount="500.00"),
        entry(type="add", day="2026-06-15", amount="100.00"),
        entry(day="2026-07-01", amount="80.00"),
        entry(type="add", day="2026-07-10", amount="20.00"),
    ]

    row, _ = compute_balance_row("openai", "OpenAI", entries, [], TODAY)

    assert row.anchor_date == date(2026, 7, 1)
    assert row.anchor_amount == Decimal("80.00")
    assert row.purchases_since == Decimal("20.00")
    assert row.estimated_balance == Decimal("100.00")


def test_compute_same_day_tie_keeps_file_order():
    entries = [
        entry(type="add", day="2026-07-01", amount="30.00"),
        entry(day="2026-07-01", amount="100.00"),
        entry(type="add", day="2026-07-01", amount="10.00"),
    ]

    row, _ = compute_balance_row("openai", "OpenAI", entries, [], TODAY)

    assert row.anchor_amount == Decimal("100.00")
    assert row.purchases_since == Decimal("10.00")


def test_compute_preserves_negative_estimate():
    row, _ = compute_balance_row("openai", "OpenAI", [entry(amount="10.00")], [spend("2026-07-02", "25.00")], TODAY)

    assert row.estimated_balance == Decimal("-15.00")


def test_compute_without_spend_records_leaves_estimate_none():
    row, warnings = compute_balance_row("openai", "OpenAI", [entry()], None, TODAY)

    assert warnings == []
    assert row.spend_since is None
    assert row.estimated_balance is None
    assert row.anchor_amount == Decimal("100.00")


def test_compute_excludes_non_anchor_currency_spend_with_warning():
    records = [spend("2026-07-02", "10.00"), spend("2026-07-03", "7.00", currency="EUR")]

    row, warnings = compute_balance_row("openai", "OpenAI", [entry(amount="100.00")], records, TODAY)

    assert row.spend_since == Decimal("10.00")
    assert row.estimated_balance == Decimal("90.00")
    assert len(warnings) == 1
    assert "EUR" in warnings[0]


def test_compute_no_entries_returns_none_without_warning():
    row, warnings = compute_balance_row("openai", "OpenAI", [], None, TODAY)

    assert row is None
    assert warnings == []


def test_compute_without_set_anchor_warns():
    row, warnings = compute_balance_row("openai", "OpenAI", [entry(type="add", amount="5.00")], None, TODAY)

    assert row is None
    assert len(warnings) == 1
    assert "balance set" in warnings[0]


def test_compute_only_uses_matching_provider_entries():
    entries = [entry(amount="100.00"), entry(provider="anthropic", amount="50.00")]

    row, _ = compute_balance_row("anthropic", "Anthropic", entries, [], TODAY)

    assert row.anchor_amount == Decimal("50.00")


def test_find_anchor_returns_latest_set():
    entries = [
        entry(day="2026-06-01", amount="500.00"),
        entry(day="2026-07-01", amount="80.00"),
        entry(type="add", day="2026-07-10", amount="20.00"),
    ]

    anchor = find_anchor(entries, "openai")

    assert anchor.date == date(2026, 7, 1)
    assert find_anchor(entries, "anthropic") is None
