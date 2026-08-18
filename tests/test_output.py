import json
from datetime import date
from decimal import Decimal
from io import StringIO

from rich.console import Console as RichConsole

from llm_org_cost_monitor import output
from llm_org_cost_monitor.models import BalanceRow, SummaryRow


def render_table(monkeypatch, rows):
    buffer = StringIO()

    monkeypatch.setattr(
        output,
        "Console",
        lambda: RichConsole(file=buffer, force_terminal=False, width=120, color_system=None),
    )

    output.print_table(rows, "project-workspace")
    return buffer.getvalue()


def test_table_formats_and_orders_rows(monkeypatch):
    rendered = render_table(
        monkeypatch,
        [
            SummaryRow(group="Lab", provider="openai", currency="USD", amount=Decimal("1.2"), records=1),
            SummaryRow(group="Product", provider="anthropic", currency="USD", amount=Decimal("2.345"), records=1),
            SummaryRow(group="Default", provider="anthropic", currency="USD", amount=Decimal("0.50"), records=1),
        ],
    )

    assert rendered.index("Provider") < rendered.index("Group")
    assert "Currency" not in rendered
    assert "USD" not in rendered
    assert "$2.34" in rendered
    assert "$1.20" in rendered
    assert rendered.index("Product") < rendered.index("Default")
    assert rendered.index("Default") < rendered.index("Lab")


def test_table_shows_currency_for_multiple_currencies(monkeypatch):
    rendered = render_table(
        monkeypatch,
        [
            SummaryRow(group="Lab", provider="openai", currency="USD", amount=Decimal("1.20"), records=1),
            SummaryRow(group="Lab", provider="openai", currency="EUR", amount=Decimal("0.80"), records=1),
        ],
    )

    assert "Currency" in rendered
    assert "USD" in rendered
    assert "EUR" in rendered


def balance_row(**overrides):
    fields = dict(
        provider="openai",
        label="OpenAI Org",
        anchor_date=date(2026, 7, 1),
        anchor_amount=Decimal("100.00"),
        purchases_since=Decimal("20.00"),
        adjustments_since=Decimal("0"),
        spend_since=Decimal("15.50"),
        estimated_balance=Decimal("104.50"),
        currency="USD",
        as_of=date(2026, 7, 25),
    )
    fields.update(overrides)
    return BalanceRow(**fields)


def test_balance_table_formats_amounts_and_missing_values(monkeypatch):
    buffer = StringIO()
    monkeypatch.setattr(
        output,
        "Console",
        lambda: RichConsole(file=buffer, force_terminal=False, width=160, color_system=None),
    )

    output.print_balance_table(
        [
            balance_row(),
            balance_row(provider="anthropic", label="Anthropic Org", spend_since=None, estimated_balance=None),
        ]
    )
    rendered = buffer.getvalue()

    assert "Est. Balance" in rendered
    assert "$104.50" in rendered
    assert "$100.00" in rendered
    assert " - " in rendered
    assert "2026-07-25" in rendered


def test_balance_json_uses_string_amounts(capsys):
    output.print_balance_json([balance_row()])

    payload = json.loads(capsys.readouterr().out)
    assert payload["balances"][0]["anchor_amount"] == "100.00"
    assert payload["balances"][0]["estimated_balance"] == "104.50"
    assert payload["balances"][0]["as_of"] == "2026-07-25"


def test_balance_csv_blank_cells_for_missing_values(capsys):
    output.print_balance_csv([balance_row(spend_since=None, estimated_balance=None)])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "provider,label,anchor_date,anchor_amount,purchases_since,adjustments_since,"
        "spend_since,estimated_balance,currency,as_of"
    )
    assert lines[1] == "openai,OpenAI Org,2026-07-01,100.00,20.00,0,,,USD,2026-07-25"


def test_balance_table_shows_negative_adjustment(monkeypatch):
    buffer = StringIO()
    monkeypatch.setattr(
        output,
        "Console",
        lambda: RichConsole(file=buffer, force_terminal=False, width=180, color_system=None),
    )

    output.print_balance_table([balance_row(adjustments_since=Decimal("-13.73"))])
    rendered = buffer.getvalue()

    assert "Adjustments" in rendered
    assert "$-13.73" in rendered


def test_balance_json_includes_adjustments(capsys):
    output.print_balance_json([balance_row(adjustments_since=Decimal("-13.73"))])

    payload = json.loads(capsys.readouterr().out)
    assert payload["balances"][0]["adjustments_since"] == "-13.73"
