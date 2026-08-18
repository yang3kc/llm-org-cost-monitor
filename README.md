# llm-org-cost-monitor

Local Python 3.12 CLI for checking organization-level costs across one OpenAI organization and one Anthropic organization.

The primary installed command is `llm-org-cost-monitor`. The shorter `llm-org-cost` command is also provided as a compatibility alias. The project name includes `org` because it reads provider organization cost reports rather than estimating individual request or model costs.

## Setup

```bash
uv sync --dev
cp .env.example .env
```

Fill `.env` with local admin keys:

```dotenv
OPENAI_ADMIN_KEY=...
ANTHROPIC_ADMIN_KEY=...
OPENAI_ACCOUNT_LABEL=OpenAI
ANTHROPIC_ACCOUNT_LABEL=Anthropic
```

`.env` is ignored by git and must not be committed.

## Configuration

The CLI reads configuration from environment variables. For local use, you can either export variables in your shell or put them in a `.env` file in the directory where you run the command.

```bash
export OPENAI_ADMIN_KEY=...
export ANTHROPIC_ADMIN_KEY=...
export OPENAI_ACCOUNT_LABEL=OpenAI
export ANTHROPIC_ACCOUNT_LABEL=Anthropic
export LLM_ORG_COST_LEDGER=~/.config/llm-org-cost-monitor/ledger.json
```

```dotenv
OPENAI_ADMIN_KEY=...
ANTHROPIC_ADMIN_KEY=...
OPENAI_ACCOUNT_LABEL=OpenAI
ANTHROPIC_ACCOUNT_LABEL=Anthropic
LLM_ORG_COST_LEDGER=~/.config/llm-org-cost-monitor/ledger.json
```

Only one provider key is required if you only want reports for that provider. The account label variables are optional and default to `OpenAI` and `Anthropic`. `LLM_ORG_COST_LEDGER` is optional and overrides the balance ledger location, which defaults to `~/.config/llm-org-cost-monitor/ledger.json`.

The CLI does not accept API keys as command-line flags. This keeps secrets out of shell history, terminal scrollback, and process listings.

## Usage

Local development:

```bash
uv run llm-org-cost-monitor doctor
uvx --from . llm-org-cost-monitor doctor
```

After the package is published to PyPI:

```bash
uvx llm-org-cost-monitor doctor
uvx llm-org-cost-monitor summary --period mtd
```

Installed command examples:

```bash
llm-org-cost-monitor doctor
llm-org-cost-monitor summary --period mtd
llm-org-cost-monitor summary --period mtd --provider openai
llm-org-cost-monitor summary --period mtd --provider anthropic
llm-org-cost-monitor summary --period mtd --group project-workspace
llm-org-cost-monitor summary --period mtd --group api-key
llm-org-cost-monitor summary --period mtd --group day-project-workspace
llm-org-cost-monitor summary --period last-7d --format json
llm-org-cost-monitor summary --start 2026-07-01 --end 2026-07-05 --group line-item --format csv
```

`--start` and `--end` are calendar dates. The end date is inclusive for the CLI and converted to the provider APIs' exclusive end timestamp.

Use `--provider openai` or `--provider anthropic` to fetch and show only one provider. The default is `--provider all`.

Supported summary groups:

- `provider`
- `project`
- `workspace`
- `line-item`
- `day`
- `project-workspace`
- `api-key`
- `day-project-workspace`

`project-workspace` combines the two provider-native ownership views: OpenAI costs are grouped by project and Anthropic costs are grouped by workspace. `api-key` groups OpenAI costs by `api_key_id`; Anthropic rows are reported as `Unsupported/Unattributed` because Anthropic cost reports do not currently expose API key attribution. `day-project-workspace` applies the combined project/workspace view per day.

Supported output formats:

- `table`
- `json`
- `csv`

## Balance tracking

Neither OpenAI nor Anthropic exposes prepaid credit balance via API, so the CLI keeps a locally maintained ledger that you update when you buy credits. The `balance` commands never require API keys except `balance show`, which fetches spend.

```bash
llm-org-cost-monitor balance set openai 120.00 --date 2026-07-01 --note "after top-up"
llm-org-cost-monitor balance add openai 25.00
llm-org-cost-monitor balance adjust --date 2026-07-31 --note "credits expired" -- openai -13.73
llm-org-cost-monitor balance log
llm-org-cost-monitor balance show
llm-org-cost-monitor balance show --provider anthropic --format json
```

- `balance set` records a balance snapshot (the anchor) copied from the provider console.
- `balance add` records a credit top-up made after the last snapshot. The amount must be positive.
- `balance adjust` records a credit change the cost APIs cannot see, such as expired credits or a refund. The amount is signed and must be nonzero: negative removes credit, positive adds it.
- `balance log` lists ledger entries; `balance show` estimates current balances.

Because a negative amount looks like a command-line option, pass `--` before the arguments:

```bash
llm-org-cost-monitor balance adjust --note "credits expired" -- openai -13.73
```

The estimate is computed as:

```text
estimated balance = latest "set" amount
                  + "add" amounts recorded after that "set"
                  + "adjust" amounts recorded after that "set"   (signed)
                  - API-reported spend from the "set" date through today
```

Entries are ordered by date; entries sharing a date keep file order. `add` and `adjust` entries dated before the latest `set` are ignored because the snapshot already reflects them.

The ledger lives at `~/.config/llm-org-cost-monitor/ledger.json` by default (override with `LLM_ORG_COST_LEDGER`). Amounts are stored as strings so they round-trip exactly:

```json
{
  "version": 2,
  "entries": [
    {
      "provider": "openai",
      "type": "set",
      "date": "2026-07-01",
      "amount": "120.00",
      "currency": "USD",
      "note": "after top-up",
      "created_at": "2026-07-01T15:04:05Z"
    },
    {
      "provider": "openai",
      "type": "adjust",
      "date": "2026-07-31",
      "amount": "-13.73",
      "currency": "USD",
      "note": "credits expired",
      "created_at": "2026-07-31T15:04:05Z"
    }
  ]
}
```

Ledger format version 2 added the `adjust` entry type. This tool reads version 1 and version 2 files, and writes version 2. A version 1 ledger is upgraded in place the next time an entry is appended, after which older builds of the tool will refuse to read it.

Hand-editing the file is supported; unknown entry keys are preserved. The CLI enforces the sign rules above, but the loader deliberately does not, so a hand-edited file can hold entries the CLI would refuse to write. Record credit reductions as `adjust` entries: a negative `add` still loads and still produces the right total, but it is reported under purchases rather than adjustments, and `balance show` warns when it finds one.

Accuracy caveats:

- The estimate is deliberately conservative: spend on the anchor date itself is subtracted in full, even spend that occurred before you took the snapshot, so the estimate can be slightly lower than reality on and near the anchor date.
- In the other direction, providers report spend with some lag, so the most recent usage may not be counted yet; intraday estimates can run slightly high until reporting catches up.
- Provider cost APIs report usage costs only. Taxes, fees, and other invoice adjustments are not included.
- Expired or promotional credits are invisible to the cost APIs. Record them yourself with `balance adjust` or they will not show up in the estimate.
- Only USD is supported; spend records in other currencies are excluded with a warning.
- Re-run `balance set` with the console balance after each top-up. This keeps the estimate anchored to reality and keeps the spend lookback short — Anthropic's cost report pages 31 days per request, so a months-old anchor makes `balance show` slower.

## Provider APIs

OpenAI uses `GET /v1/organization/costs` with `bucket_width=1d`, Unix UTC timestamps, pagination via `next_page`, and grouping by `project_id`, `api_key_id`, and `line_item`.

Anthropic uses `GET /v1/organizations/cost_report` with RFC3339 UTC timestamps, pagination via `next_page`, and grouping by `workspace_id` and `description`.

The tool best-effort maps OpenAI project IDs and Anthropic workspace IDs to names. If mapping fails, it keeps IDs and prints a warning without exposing secrets.

Official references:

- OpenAI costs API: https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs
- OpenAI admin API auth: https://developers.openai.com/api/docs/guides/admin-apis
- Anthropic Usage and Cost API: https://platform.claude.com/docs/en/manage-claude/usage-cost-api
- Anthropic Admin API: https://platform.claude.com/docs/en/api/admin

## Security

- Keys are read from `.env` with `python-dotenv`.
- Full keys are never printed.
- `doctor` reports provider, label, auth status, and metadata counts only.
- JSON output preserves provider amount fields under `raw_amount`, but does not include request headers or keys.
- The balance ledger is a plain local JSON file. It contains financial amounts but no secrets, and it is never sent anywhere.

## Development

```bash
uv sync --dev
uv run pytest
uv run llm-org-cost-monitor --help
uv run llm-org-cost --help
uvx --from . llm-org-cost-monitor --help
uv build
```

## Release

Releases are published by GitHub Actions when a version tag matching `v*` is pushed. The workflow installs uv, syncs locked development dependencies, runs the test suite, builds the source and wheel distributions, and publishes to PyPI with Trusted Publishing.

Before the first release, configure PyPI Trusted Publishing for:

```text
Repository owner: yang3kc
Repository name: llm-org-cost-monitor
Workflow filename: release.yml
Environment name: <blank>
```
