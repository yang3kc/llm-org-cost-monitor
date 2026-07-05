# llm-org-cost-monitor

Local Python 3.12 CLI for checking organization-level costs across one OpenAI organization and one Anthropic organization.

The installed command is `llm-org-cost`. The project name includes `org` because it reads provider organization cost reports rather than estimating individual request or model costs.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
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

## Usage

```bash
llm-org-cost doctor
llm-org-cost summary --period mtd
llm-org-cost summary --period last-7d --format json
llm-org-cost summary --start 2026-07-01 --end 2026-07-05 --group line-item --format csv
```

`--start` and `--end` are calendar dates. The end date is inclusive for the CLI and converted to the provider APIs' exclusive end timestamp.

Supported summary groups:

- `provider`
- `project`
- `workspace`
- `line-item`
- `day`

Supported output formats:

- `table`
- `json`
- `csv`

## Provider APIs

OpenAI uses `GET /v1/organization/costs` with `bucket_width=1d`, Unix UTC timestamps, pagination via `next_page`, and grouping by `project_id` and `line_item`.

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

## Development

```bash
pytest
```
