from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

ProviderName = Literal["openai", "anthropic"]
GroupBy = Literal[
    "provider",
    "project",
    "workspace",
    "line-item",
    "day",
    "project-workspace",
    "api-key",
    "day-project-workspace",
]


@dataclass(frozen=True)
class CostRecord:
    provider: ProviderName
    account_label: str
    date: date
    amount: Decimal
    currency: str
    project_id: str | None = None
    project_name: str | None = None
    api_key_id: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    line_item: str | None = None
    raw_amount: Any = None

    def display_name(self, group_by: GroupBy) -> str:
        if group_by == "provider":
            return self.account_label
        if group_by == "project":
            return self.project_name or self.project_id or "Unattributed"
        if group_by == "workspace":
            return self.workspace_name or self.workspace_id or "Default/Unattributed"
        if group_by == "line-item":
            return self.line_item or "Unattributed"
        if group_by == "day":
            return self.date.isoformat()
        if group_by == "project-workspace":
            return self.project_or_workspace_name()
        if group_by == "api-key":
            return self.api_key_id or ("Unsupported/Unattributed" if self.provider == "anthropic" else "Unattributed")
        if group_by == "day-project-workspace":
            return f"{self.date.isoformat()} / {self.project_or_workspace_name()}"
        raise ValueError(f"Unsupported group: {group_by}")

    def project_or_workspace_name(self) -> str:
        if self.provider == "openai":
            return self.project_name or self.project_id or "Unattributed"
        return self.workspace_name or self.workspace_id or "Default/Unattributed"


@dataclass(frozen=True)
class SummaryRow:
    group: str
    provider: str
    currency: str
    amount: Decimal
    records: int


@dataclass(frozen=True)
class ProviderStatus:
    provider: ProviderName
    label: str
    status: str
    metadata: str


def summarize(records: list[CostRecord], group_by: GroupBy) -> list[SummaryRow]:
    grouped: dict[tuple[str, str, str], tuple[Decimal, int]] = {}
    for record in records:
        provider = record.provider if group_by != "provider" else ""
        key = (record.display_name(group_by), provider, record.currency.upper())
        amount, count = grouped.get(key, (Decimal("0"), 0))
        grouped[key] = (amount + record.amount, count + 1)

    rows = [
        SummaryRow(group=group, provider=provider or "all", currency=currency, amount=amount, records=count)
        for (group, provider, currency), (amount, count) in grouped.items()
    ]
    return sorted(rows, key=lambda row: (row.currency, -row.amount, row.group, row.provider))


def record_to_json(record: CostRecord) -> dict[str, Any]:
    return {
        "provider": record.provider,
        "account_label": record.account_label,
        "date": record.date.isoformat(),
        "amount": str(record.amount),
        "currency": record.currency,
        "project_id": record.project_id,
        "project_name": record.project_name,
        "api_key_id": record.api_key_id,
        "workspace_id": record.workspace_id,
        "workspace_name": record.workspace_name,
        "line_item": record.line_item,
        "raw_amount": record.raw_amount,
    }


def summary_to_json(row: SummaryRow) -> dict[str, Any]:
    return {
        "group": row.group,
        "provider": row.provider,
        "amount": str(row.amount),
        "currency": row.currency,
        "records": row.records,
    }
