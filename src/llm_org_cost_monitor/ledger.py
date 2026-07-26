from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from .models import BalanceRow, CostRecord, ProviderName

LEDGER_VERSION = 1

EntryType = Literal["set", "add"]


class LedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class LedgerEntry:
    provider: ProviderName
    type: EntryType
    date: date
    amount: Decimal
    currency: str = "USD"
    note: str | None = None
    created_at: str | None = None


def load_entries(path: Path) -> list[LedgerEntry]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise LedgerError(f"{path}: ledger file is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise LedgerError(f"{path}: ledger root must be a JSON object")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise LedgerError(f"{path}: missing or invalid ledger version")
    if version > LEDGER_VERSION:
        raise LedgerError(f"{path}: unsupported ledger version {version} (this tool supports up to {LEDGER_VERSION})")
    raw_entries = raw.get("entries")
    if not isinstance(raw_entries, list):
        raise LedgerError(f"{path}: 'entries' must be a list")
    return [_parse_entry(path, index, item) for index, item in enumerate(raw_entries)]


def append_entry(path: Path, entry: LedgerEntry) -> None:
    load_entries(path)
    raw_entries: list[dict[str, Any]] = []
    if path.exists():
        raw_entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    raw_entries.append(entry_to_json(entry))
    payload = {"version": LEDGER_VERSION, "entries": raw_entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def entry_to_json(entry: LedgerEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": entry.provider,
        "type": entry.type,
        "date": entry.date.isoformat(),
        "amount": str(entry.amount),
        "currency": entry.currency,
    }
    if entry.note is not None:
        payload["note"] = entry.note
    if entry.created_at is not None:
        payload["created_at"] = entry.created_at
    return payload


def find_anchor(entries: list[LedgerEntry], provider: ProviderName) -> LedgerEntry | None:
    ordered, anchor_index = _ordered_entries_and_anchor(entries, provider)
    return ordered[anchor_index] if anchor_index is not None else None


def compute_balance_row(
    provider: ProviderName,
    label: str,
    entries: list[LedgerEntry],
    spend_records: list[CostRecord] | None,
    today: date,
) -> tuple[BalanceRow | None, list[str]]:
    warnings: list[str] = []
    ordered, anchor_index = _ordered_entries_and_anchor(entries, provider)
    if not ordered:
        return None, warnings
    if anchor_index is None:
        warnings.append(f"{provider}: ledger has no 'set' entry; record a balance snapshot with 'balance set' first")
        return None, warnings
    anchor = ordered[anchor_index]

    purchases = Decimal("0")
    for entry in ordered[anchor_index + 1 :]:
        if entry.type != "add":
            continue
        if entry.currency.upper() != anchor.currency.upper():
            warnings.append(
                f"{provider}: excluded {entry.currency} top-up dated {entry.date.isoformat()}"
                f" (ledger anchor currency is {anchor.currency})"
            )
            continue
        purchases += entry.amount

    spend_since: Decimal | None = None
    estimated: Decimal | None = None
    if spend_records is not None:
        spend_since = Decimal("0")
        for record in spend_records:
            if record.currency.upper() != anchor.currency.upper():
                warnings.append(
                    f"{provider}: excluded {record.currency} spend record dated {record.date.isoformat()}"
                    f" (ledger anchor currency is {anchor.currency})"
                )
                continue
            spend_since += record.amount
        estimated = anchor.amount + purchases - spend_since

    row = BalanceRow(
        provider=provider,
        label=label,
        anchor_date=anchor.date,
        anchor_amount=anchor.amount,
        purchases_since=purchases,
        spend_since=spend_since,
        estimated_balance=estimated,
        currency=anchor.currency.upper(),
        as_of=today,
    )
    return row, warnings


def _ordered_entries_and_anchor(
    entries: list[LedgerEntry], provider: ProviderName
) -> tuple[list[LedgerEntry], int | None]:
    ordered = sorted((entry for entry in entries if entry.provider == provider), key=lambda entry: entry.date)
    anchor_index: int | None = None
    for index, entry in enumerate(ordered):
        if entry.type == "set":
            anchor_index = index
    return ordered, anchor_index


def _parse_entry(path: Path, index: int, item: Any) -> LedgerEntry:
    def fail(message: str) -> None:
        raise LedgerError(f"{path}: entry {index}: {message}")

    if not isinstance(item, dict):
        fail("must be a JSON object")
    provider = item.get("provider")
    if provider not in ("openai", "anthropic"):
        fail(f"invalid provider {provider!r}")
    entry_type = item.get("type")
    if entry_type not in ("set", "add"):
        fail(f"invalid type {entry_type!r}")
    try:
        entry_date = date.fromisoformat(str(item.get("date")))
    except ValueError:
        fail(f"invalid date {item.get('date')!r}")
    raw_amount = item.get("amount")
    if not isinstance(raw_amount, str):
        fail(f"amount must be a string, got {raw_amount!r}")
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        fail(f"invalid amount {raw_amount!r}")
    if not amount.is_finite():
        fail(f"invalid amount {raw_amount!r}")
    currency = item.get("currency", "USD")
    if not isinstance(currency, str) or not currency:
        fail(f"invalid currency {currency!r}")
    note = item.get("note")
    if note is not None and not isinstance(note, str):
        fail("note must be a string")
    created_at = item.get("created_at")
    if created_at is not None and not isinstance(created_at, str):
        fail("created_at must be a string")
    return LedgerEntry(
        provider=provider,
        type=entry_type,
        date=entry_date,
        amount=amount,
        currency=currency,
        note=note,
        created_at=created_at,
    )
