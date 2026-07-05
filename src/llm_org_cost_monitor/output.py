from __future__ import annotations

import csv
import json
import sys
from datetime import date
from decimal import Decimal
from typing import Any

from rich.console import Console
from rich.table import Table

from .models import CostRecord, GroupBy, SummaryRow, record_to_json, summary_to_json


def print_table(rows: list[SummaryRow], group_by: GroupBy) -> None:
    table = Table(title=f"LLM Organization Costs by {group_by}")
    table.add_column("Group")
    table.add_column("Provider")
    table.add_column("Currency")
    table.add_column("Amount", justify="right")
    table.add_column("Records", justify="right")
    for row in rows:
        table.add_row(row.group, row.provider, row.currency, _money(row.amount), str(row.records))
    Console().print(table)


def print_json(records: list[CostRecord], rows: list[SummaryRow], group_by: GroupBy) -> None:
    payload = {
        "group_by": group_by,
        "summary": [summary_to_json(row) for row in rows],
        "records": [record_to_json(record) for record in records],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def print_csv(rows: list[SummaryRow]) -> None:
    writer = csv.DictWriter(sys.stdout, fieldnames=["group", "provider", "currency", "amount", "records"])
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "group": row.group,
                "provider": row.provider,
                "currency": row.currency,
                "amount": str(row.amount),
                "records": row.records,
            }
        )


def _money(value: Decimal) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
