# llm-org-cost-monitor

Local Python 3.12 CLI for checking organization-level costs across one OpenAI organization and one Anthropic organization.

The installed command is `llm-org-cost`. The project name includes `org` because it reads provider organization cost reports rather than estimating individual request or model costs.

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
```

```dotenv
OPENAI_ADMIN_KEY=...
ANTHROPIC_ADMIN_KEY=...
OPENAI_ACCOUNT_LABEL=OpenAI
ANTHROPIC_ACCOUNT_LABEL=Anthropic
```

Only one provider key is required if you only want reports for that provider. The account label variables are optional and default to `OpenAI` and `Anthropic`.

The CLI does not accept API keys as command-line flags. This keeps secrets out of shell history, terminal scrollback, and process listings.

## Usage

Local development:

```bash
uv run llm-org-cost doctor
uvx --from . llm-org-cost doctor
```

After the package is published to PyPI:

```bash
uvx llm-org-cost-monitor llm-org-cost doctor
uvx llm-org-cost-monitor llm-org-cost summary --period mtd
```

Installed command examples:

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
uv sync --dev
uv run pytest
uv run llm-org-cost --help
uvx --from . llm-org-cost --help
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
