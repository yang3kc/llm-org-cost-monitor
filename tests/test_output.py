from decimal import Decimal
from io import StringIO

from rich.console import Console as RichConsole

from llm_org_cost_monitor import output
from llm_org_cost_monitor.models import SummaryRow


def test_table_formats_and_orders_rows(monkeypatch):
    buffer = StringIO()

    monkeypatch.setattr(
        output,
        "Console",
        lambda: RichConsole(file=buffer, force_terminal=False, width=120, color_system=None),
    )

    output.print_table(
        [
            SummaryRow(group="Lab", provider="openai", currency="USD", amount=Decimal("1.2"), records=1),
            SummaryRow(group="Product", provider="anthropic", currency="USD", amount=Decimal("2.345"), records=1),
            SummaryRow(group="Default", provider="anthropic", currency="USD", amount=Decimal("0.50"), records=1),
        ],
        "project-workspace",
    )

    rendered = buffer.getvalue()
    assert rendered.index("Provider") < rendered.index("Group")
    assert "$2.34" in rendered
    assert "$1.20" in rendered
    assert rendered.index("Product") < rendered.index("Default")
    assert rendered.index("Default") < rendered.index("Lab")
