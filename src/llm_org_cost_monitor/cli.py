from __future__ import annotations

from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .dates import DateRange, parse_cli_range, range_for_period
from .models import GroupBy, ProviderStatus, summarize
from .output import print_csv, print_json, print_table
from .providers import AnthropicCostClient, MissingKeyError, OpenAICostClient, ProviderAPIError

app = typer.Typer(help="Check OpenAI and Anthropic organization costs.")
err_console = Console(stderr=True)

OutputFormat = Literal["table", "json", "csv"]
PeriodOption = Literal["mtd", "last-7d", "last-30d"]


@app.command()
def summary(
    period: Annotated[PeriodOption | None, typer.Option(help="Preset period.")] = None,
    start: Annotated[str | None, typer.Option(help="Start date, YYYY-MM-DD.")] = None,
    end: Annotated[str | None, typer.Option(help="Inclusive end date, YYYY-MM-DD.")] = None,
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

    for build_client in (
        lambda: OpenAICostClient(settings.openai_admin_key, settings.openai_label),
        lambda: AnthropicCostClient(settings.anthropic_admin_key, settings.anthropic_label),
    ):
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
