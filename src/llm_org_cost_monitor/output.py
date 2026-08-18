from __future__ import annotations

import csv
import json
import sys
from datetime import date
from decimal import Decimal
from typing import Any

from rich.console import Console
from rich.table import Table

from .models import BalanceRow, CostRecord, GroupBy, SummaryRow, balance_to_json, record_to_json, summary_to_json


def print_table(rows: list[SummaryRow], group_by: GroupBy) -> None:
    show_currency = len({row.currency for row in rows}) > 1
    table = Table(title=f"LLM Organization Costs by {group_by}")
    table.add_column("Provider")
    table.add_column("Group")
    if show_currency:
        table.add_column("Currency")
    table.add_column("Amount", justify="right")
    table.add_column("Records", justify="right")
    for row in sorted(rows, key=lambda row: (row.provider, -row.amount, row.group, row.currency)):
        values = [row.provider, row.group]
        if show_currency:
            values.append(row.currency)
        values.extend([_money(row.amount), str(row.records)])
        table.add_row(*values)
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


def print_balance_table(rows: list[BalanceRow]) -> None:
    table = Table(title="LLM Prepaid Balance Estimates")
    table.add_column("Provider")
    table.add_column("Label")
    table.add_column("Anchor Date")
    table.add_column("Anchor Amount", justify="right")
    table.add_column("Purchases Since", justify="right")
    table.add_column("Adjustments", justify="right")
    table.add_column("Spend Since", justify="right")
    table.add_column("Est. Balance", justify="right")
    table.add_column("As Of")
    for row in rows:
        table.add_row(
            row.provider,
            row.label,
            row.anchor_date.isoformat(),
            _money(row.anchor_amount),
            _money(row.purchases_since),
            _money(row.adjustments_since),
            "-" if row.spend_since is None else _money(row.spend_since),
            "-" if row.estimated_balance is None else _money(row.estimated_balance),
            row.as_of.isoformat(),
        )
    Console().print(table)


def print_balance_json(rows: list[BalanceRow]) -> None:
    payload = {"balances": [balance_to_json(row) for row in rows]}
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def print_balance_csv(rows: list[BalanceRow]) -> None:
    fieldnames = [
        "provider",
        "label",
        "anchor_date",
        "anchor_amount",
        "purchases_since",
        "adjustments_since",
        "spend_since",
        "estimated_balance",
        "currency",
        "as_of",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "provider": row.provider,
                "label": row.label,
                "anchor_date": row.anchor_date.isoformat(),
                "anchor_amount": str(row.anchor_amount),
                "purchases_since": str(row.purchases_since),
                "adjustments_since": str(row.adjustments_since),
                "spend_since": "" if row.spend_since is None else str(row.spend_since),
                "estimated_balance": "" if row.estimated_balance is None else str(row.estimated_balance),
                "currency": row.currency,
                "as_of": row.as_of.isoformat(),
            }
        )


def _money(value: Decimal) -> str:
    return f"${value:.2f}"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
