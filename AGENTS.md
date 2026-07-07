# AGENTS.md

Guidance for AI agents working in this repository.

## What this is

`llm-org-cost-monitor` is a local Python 3.12 CLI that reports **organization-level**
costs from one OpenAI organization and one Anthropic organization. It reads the
providers' native org cost-report APIs — it does not estimate per-request or
per-model costs.

Installed commands: `llm-org-cost-monitor` (primary) and `llm-org-cost` (alias).
Both map to `llm_org_cost_monitor.cli:app`.

## Layout

```
src/llm_org_cost_monitor/
  cli.py         Typer app: `summary` and `doctor` commands, arg parsing, date resolution
  config.py      Loads settings from env / .env (python-dotenv)
  dates.py       DateRange, period + CLI date-range parsing (mtd, last-7d, last-30d, --start/--end)
  models.py      CostRecord / SummaryRow / ProviderStatus, GroupBy, summarize(), JSON serialization
  output.py      Rich table, JSON, and CSV renderers
  providers.py   OpenAICostClient + AnthropicCostClient (httpx), pagination, name mapping, errors
tests/           pytest suite, one file per module
```

## Environment

Uses `uv`. Common commands:

```bash
uv sync --dev                       # install deps (incl. dev)
uv run pytest                       # run tests
uv run llm-org-cost-monitor --help  # run the CLI locally
uv build                            # build sdist + wheel
```

Configuration is via environment variables (or a local `.env`):
`OPENAI_ADMIN_KEY`, `ANTHROPIC_ADMIN_KEY`, `OPENAI_ACCOUNT_LABEL`,
`ANTHROPIC_ACCOUNT_LABEL`. Only one provider key is required to use that provider.

## Rules

- **Never commit `.env` or secrets.** `.env` is gitignored; keep it that way.
- **Never print full API keys.** Keys are admin-scoped and highly sensitive. The
  CLI intentionally does not accept keys as command-line flags (keeps them out of
  shell history / process listings). `doctor` reports only provider, label, auth
  status, and metadata counts. JSON output must not include request headers or keys.
- **Run `uv run pytest` before considering a change done.** Add/adjust tests in the
  matching `tests/test_<module>.py` when changing behavior.
- Keep provider-specific quirks documented in `README.md` in sync with code
  (e.g. Anthropic has no API-key attribution → `Unsupported/Unattributed`).
- Dates: `--start`/`--end` are inclusive calendar dates in the CLI; conversion to
  the providers' exclusive end timestamp happens internally (`dates.py`).

## Provider API notes

- OpenAI: `GET /v1/organization/costs`, `bucket_width=1d`, Unix UTC timestamps,
  pagination via `next_page`, grouped by `project_id`, `api_key_id`, `line_item`.
- Anthropic: `GET /v1/organizations/cost_report`, RFC3339 UTC timestamps,
  pagination via `next_page`, grouped by `workspace_id` and `description`.
- ID→name mapping is best-effort; on failure keep IDs and warn without leaking secrets.

## Release

Tags matching `v*` trigger `.github/workflows/release.yml`, which tests, builds,
and publishes to PyPI via Trusted Publishing. Bump `version` in `pyproject.toml`
before tagging.
