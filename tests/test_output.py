from decimal import Decimal
from io import StringIO

from rich.console import Console as RichConsole

from llm_org_cost_monitor import output
from llm_org_cost_monitor.models import SummaryRow


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
