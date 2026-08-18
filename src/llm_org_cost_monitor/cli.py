from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .dates import DateRange, parse_cli_range, range_for_period, range_since
from .ledger import LedgerEntry, LedgerError, append_entry, compute_balance_row, find_anchor, load_entries
from .models import BalanceRow, GroupBy, ProviderStatus, summarize
from .output import print_balance_csv, print_balance_json, print_balance_table, print_csv, print_json, print_table
from .providers import AnthropicCostClient, MissingKeyError, OpenAICostClient, ProviderAPIError

app = typer.Typer(help="Check OpenAI and Anthropic organization costs.")
balance_app = typer.Typer(help="Track prepaid credit balances with a local ledger.")
app.add_typer(balance_app, name="balance")
err_console = Console(stderr=True)

OutputFormat = Literal["table", "json", "csv"]
PeriodOption = Literal["mtd", "last-7d", "last-30d"]
ProviderOption = Literal["all", "openai", "anthropic"]
LedgerProvider = Literal["openai", "anthropic"]


@app.command()
def summary(
    period: Annotated[PeriodOption | None, typer.Option(help="Preset period.")] = None,
    start: Annotated[str | None, typer.Option(help="Start date, YYYY-MM-DD.")] = None,
    end: Annotated[str | None, typer.Option(help="Inclusive end date, YYYY-MM-DD.")] = None,
    provider: Annotated[ProviderOption, typer.Option(help="Provider to include.")] = "all",
    group: Annotated[GroupBy, typer.Option(help="Summary grouping.")] = "provider",
    format: Annotated[OutputFormat, typer.Option(help="Output format.")] = "table",
) -> None:
    """Fetch and summarize organization cost reports."""
    try:
        date_range = _resolve_date_range(period, start, end)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    settings = load_settings()
    records = []
    warnings = []
    failures = []

    provider_clients = (
        ("openai", lambda: OpenAICostClient(settings.openai_admin_key, settings.openai_label)),
        ("anthropic", lambda: AnthropicCostClient(settings.anthropic_admin_key, settings.anthropic_label)),
    )
    for provider_name, build_client in provider_clients:
        if provider != "all" and provider != provider_name:
            continue
        try:
            client = build_client()
            provider_records, provider_warnings = client.fetch_costs(date_range)
            records.extend(provider_records)
            warnings.extend(provider_warnings)
        except MissingKeyError as exc:
            warnings.append(str(exc))
        except ProviderAPIError as exc:
            failures.append(str(exc))

    for warning in warnings:
        err_console.print(f"Warning: {warning}")
    for failure in failures:
        err_console.print(f"Error: {failure}")

    if not records and failures:
        raise typer.Exit(code=1)
    if not records and not warnings:
        raise typer.Exit(code=1)

    rows = summarize(records, group)
    if format == "table":
        print_table(rows, group)
    elif format == "json":
        print_json(records, rows, group)
    elif format == "csv":
        print_csv(rows)
    else:
        raise typer.BadParameter(f"Unsupported format: {format}")


@app.command()
def doctor() -> None:
    """Verify configured admin keys without printing secrets."""
    settings = load_settings()
    statuses: list[ProviderStatus] = []
    for provider, label, key, client_type in (
        ("openai", settings.openai_label, settings.openai_admin_key, OpenAICostClient),
        ("anthropic", settings.anthropic_label, settings.anthropic_admin_key, AnthropicCostClient),
    ):
        if not key:
            statuses.append(ProviderStatus(provider=provider, label=label, status="missing-key", metadata="not configured"))
            continue
        try:
            statuses.append(client_type(key, label).doctor())
        except ProviderAPIError as exc:
            status = "auth-failed" if exc.status_code in {401, 403} else "error"
            statuses.append(ProviderStatus(provider=provider, label=label, status=status, metadata=exc.message))

    table = Table(title="LLM Organization Cost Monitor Doctor")
    table.add_column("Provider")
    table.add_column("Label")
    table.add_column("Status")
    table.add_column("Metadata")
    for status in statuses:
        table.add_row(status.provider, status.label, status.status, status.metadata)
    Console().print(table)

    if any(status.status in {"auth-failed", "error"} for status in statuses):
        raise typer.Exit(code=1)


@balance_app.command("set")
def balance_set(
    provider: Annotated[LedgerProvider, typer.Argument(help="Provider the balance belongs to.")],
    amount: Annotated[str, typer.Argument(help="Balance shown in the provider console, e.g. 120.00.")],
    date_: Annotated[str | None, typer.Option("--date", help="Snapshot date, YYYY-MM-DD. Defaults to today.")] = None,
    note: Annotated[str | None, typer.Option(help="Optional note stored with the entry.")] = None,
) -> None:
    """Record a balance snapshot (anchor) copied from the provider console."""
    _record_ledger_entry("set", provider, amount, date_, note)


@balance_app.command("add")
def balance_add(
    provider: Annotated[LedgerProvider, typer.Argument(help="Provider the top-up belongs to.")],
    amount: Annotated[str, typer.Argument(help="Credit amount purchased, e.g. 25.00.")],
    date_: Annotated[str | None, typer.Option("--date", help="Purchase date, YYYY-MM-DD. Defaults to today.")] = None,
    note: Annotated[str | None, typer.Option(help="Optional note stored with the entry.")] = None,
) -> None:
    """Record a credit top-up made after the last balance snapshot."""
    _record_ledger_entry("add", provider, amount, date_, note)


@balance_app.command("adjust")
def balance_adjust(
    provider: Annotated[LedgerProvider, typer.Argument(help="Provider the adjustment belongs to.")],
    amount: Annotated[
        str,
        typer.Argument(help="Signed correction, e.g. -13.73 for expired credits or 5.00 for a refund."),
    ],
    date_: Annotated[str | None, typer.Option("--date", help="Adjustment date, YYYY-MM-DD. Defaults to today.")] = None,
    note: Annotated[str | None, typer.Option(help="Optional note stored with the entry.")] = None,
) -> None:
    """Record a credit change the cost APIs cannot see, such as an expiry or refund."""
    _record_ledger_entry("adjust", provider, amount, date_, note)


@balance_app.command("log")
def balance_log(
    provider: Annotated[ProviderOption, typer.Option(help="Provider to include.")] = "all",
) -> None:
    """List recorded ledger entries."""
    settings = load_settings()
    try:
        entries = load_entries(settings.ledger_path)
    except LedgerError as exc:
        err_console.print(f"Error: {exc}")
        raise typer.Exit(code=1) from exc

    selected = [entry for entry in entries if provider in ("all", entry.provider)]
    if not selected:
        typer.echo(f"No ledger entries recorded in {settings.ledger_path}")
        return

    table = Table(title=f"Balance Ledger ({settings.ledger_path})")
    table.add_column("Date")
    table.add_column("Provider")
    table.add_column("Type")
    table.add_column("Amount", justify="right")
    table.add_column("Currency")
    table.add_column("Note")
    for entry in sorted(selected, key=lambda entry: entry.date):
        table.add_row(
            entry.date.isoformat(),
            entry.provider,
            entry.type,
            str(entry.amount),
            entry.currency,
            entry.note or "",
        )
    Console().print(table)


@balance_app.command("show")
def balance_show(
    provider: Annotated[ProviderOption, typer.Option(help="Provider to include.")] = "all",
    format: Annotated[OutputFormat, typer.Option(help="Output format.")] = "table",
) -> None:
    """Estimate current prepaid balances from the ledger and API-reported spend."""
    settings = load_settings()
    try:
        entries = load_entries(settings.ledger_path)
    except LedgerError as exc:
        err_console.print(f"Error: {exc}")
        raise typer.Exit(code=1) from exc

    today = date.today()
    rows: list[BalanceRow] = []
    warnings: list[str] = []
    failures: list[str] = []

    provider_clients = (
        ("openai", settings.openai_label, lambda: OpenAICostClient(settings.openai_admin_key, settings.openai_label)),
        (
            "anthropic",
            settings.anthropic_label,
            lambda: AnthropicCostClient(settings.anthropic_admin_key, settings.anthropic_label),
        ),
    )
    for provider_name, label, build_client in provider_clients:
        if provider != "all" and provider != provider_name:
            continue
        if not any(entry.provider == provider_name for entry in entries):
            continue
        anchor = find_anchor(entries, provider_name)
        spend_records = None
        if anchor is not None:
            try:
                date_range = range_since(anchor.date, today)
                client = build_client()
                spend_records, provider_warnings = client.fetch_costs(date_range)
                warnings.extend(provider_warnings)
            except MissingKeyError as exc:
                warnings.append(str(exc))
            except ProviderAPIError as exc:
                failures.append(str(exc))
            except ValueError as exc:
                failures.append(f"{provider_name}: {exc}")
        row, row_warnings = compute_balance_row(provider_name, label, entries, spend_records, today)
        warnings.extend(row_warnings)
        if row is not None:
            rows.append(row)

    for warning in warnings:
        err_console.print(f"Warning: {warning}")
    for failure in failures:
        err_console.print(f"Error: {failure}")

    if failures and not any(row.estimated_balance is not None for row in rows):
        raise typer.Exit(code=1)
    if not rows and not warnings:
        err_console.print("Error: no balance entries recorded; use 'balance set' to record a snapshot first")
        raise typer.Exit(code=1)

    if format == "table":
        print_balance_table(rows)
    elif format == "json":
        print_balance_json(rows)
    elif format == "csv":
        print_balance_csv(rows)
    else:
        raise typer.BadParameter(f"Unsupported format: {format}")


def _record_ledger_entry(
    entry_type: Literal["set", "add", "adjust"],
    provider: LedgerProvider,
    amount: str,
    date_str: str | None,
    note: str | None,
) -> None:
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise typer.BadParameter(f"amount must be a decimal number, got {amount!r}") from exc
    if not value.is_finite():
        raise typer.BadParameter(f"amount must be a finite decimal number, got {amount!r}")
    if entry_type == "set" and value < 0:
        raise typer.BadParameter("balance for 'set' must be >= 0")
    if entry_type == "add" and value <= 0:
        raise typer.BadParameter("top-up for 'add' must be > 0")
    if entry_type == "adjust" and value == 0:
        raise typer.BadParameter("adjustment for 'adjust' must be nonzero")

    if date_str is None:
        entry_date = date.today()
    else:
        try:
            entry_date = date.fromisoformat(date_str)
        except ValueError as exc:
            raise typer.BadParameter(f"date must be YYYY-MM-DD, got {date_str!r}") from exc
    if entry_date > date.today():
        raise typer.BadParameter(f"date {entry_date.isoformat()} is in the future")

    settings = load_settings()
    entry = LedgerEntry(
        provider=provider,
        type=entry_type,
        date=entry_date,
        amount=value,
        currency="USD",
        note=note,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    try:
        append_entry(settings.ledger_path, entry)
    except LedgerError as exc:
        err_console.print(f"Error: {exc}")
        raise typer.Exit(code=1) from exc

    label = {"set": "balance snapshot", "add": "top-up", "adjust": "adjustment"}[entry_type]
    typer.echo(f"Recorded {provider} {label} {value} USD on {entry_date.isoformat()} in {settings.ledger_path}")


def _resolve_date_range(period: PeriodOption | None, start: str | None, end: str | None) -> DateRange:
    if start or end:
        if period:
            raise ValueError("Use either --period or --start/--end, not both")
        if not start or not end:
            raise ValueError("--start and --end must be provided together")
        return parse_cli_range(start, end)
    return range_for_period(period or "mtd")


if __name__ == "__main__":
    app()
