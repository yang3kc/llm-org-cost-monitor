import json
from datetime import date
from decimal import Decimal

from typer.testing import CliRunner

from llm_org_cost_monitor import cli
from llm_org_cost_monitor.models import CostRecord, ProviderStatus

runner = CliRunner()


class FakeOpenAI:
    def __init__(self, key, label):
        self.label = label

    def fetch_costs(self, date_range):
        return [
            CostRecord(
                provider="openai",
                account_label=self.label,
                date=date(2026, 7, 1),
                amount=Decimal("1.50"),
                currency="USD",
                project_id="proj_1",
                project_name="Lab",
                api_key_id="key_1",
                line_item="Responses API",
                raw_amount={"value": 1.5, "currency": "usd"},
            )
        ], []

    def doctor(self):
        return ProviderStatus(provider="openai", label=self.label, status="ok", metadata="1 projects visible")


class FakeAnthropic:
    def __init__(self, key, label):
        self.label = label

    def fetch_costs(self, date_range):
        return [
            CostRecord(
                provider="anthropic",
                account_label=self.label,
                date=date(2026, 7, 1),
                amount=Decimal("2.25"),
                currency="USD",
                workspace_id="wrk_1",
                workspace_name="Product",
                line_item="Input Tokens",
                raw_amount="225",
            )
        ], []

    def doctor(self):
        return ProviderStatus(provider="anthropic", label=self.label, status="ok", metadata="1 workspaces visible")


def patch_clients(monkeypatch):
    monkeypatch.setattr(cli, "OpenAICostClient", FakeOpenAI)
    monkeypatch.setattr(cli, "AnthropicCostClient", FakeAnthropic)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-secret")
    monkeypatch.setenv("ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-secret")
    monkeypatch.setenv("OPENAI_ACCOUNT_LABEL", "OpenAI Org")
    monkeypatch.setenv("ANTHROPIC_ACCOUNT_LABEL", "Anthropic Org")


def test_summary_json(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["summary", "--start", "2026-07-01", "--end", "2026-07-01", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    amounts = {row["group"]: row["amount"] for row in payload["summary"]}
    assert amounts == {"Anthropic Org": "2.25", "OpenAI Org": "1.50"}
    assert payload["records"][0]["raw_amount"] == {"currency": "usd", "value": 1.5}
    assert payload["records"][0]["api_key_id"] == "key_1"


def test_summary_csv(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["summary", "--period", "last-7d", "--group", "line-item", "--format", "csv"])

    assert result.exit_code == 0
    assert "group,provider,currency,amount,records" in result.stdout
    assert "Responses API,openai,USD,1.50,1" in result.stdout
    assert "Input Tokens,anthropic,USD,2.25,1" in result.stdout


def test_summary_filters_to_openai_provider(monkeypatch):
    patch_clients(monkeypatch)

    class UnexpectedAnthropic:
        def __init__(self, key, label):
            raise AssertionError("Anthropic client should not be built")

    monkeypatch.setattr(cli, "AnthropicCostClient", UnexpectedAnthropic)
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY")

    result = runner.invoke(
        cli.app,
        ["summary", "--period", "mtd", "--provider", "openai", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {record["provider"] for record in payload["records"]} == {"openai"}
    assert [row["group"] for row in payload["summary"]] == ["OpenAI Org"]
    assert "ANTHROPIC_ADMIN_KEY is not set" not in result.stderr


def test_summary_filters_to_anthropic_provider(monkeypatch):
    patch_clients(monkeypatch)

    class UnexpectedOpenAI:
        def __init__(self, key, label):
            raise AssertionError("OpenAI client should not be built")

    monkeypatch.setattr(cli, "OpenAICostClient", UnexpectedOpenAI)
    monkeypatch.delenv("OPENAI_ADMIN_KEY")

    result = runner.invoke(
        cli.app,
        ["summary", "--period", "mtd", "--provider", "anthropic", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {record["provider"] for record in payload["records"]} == {"anthropic"}
    assert [row["group"] for row in payload["summary"]] == ["Anthropic Org"]
    assert "OPENAI_ADMIN_KEY is not set" not in result.stderr


def test_summary_project_workspace_group(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["summary", "--period", "mtd", "--group", "project-workspace", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    amounts = {(row["group"], row["provider"]): row["amount"] for row in payload["summary"]}
    assert amounts == {
        ("Lab", "openai"): "1.50",
        ("Product", "anthropic"): "2.25",
    }


def test_summary_api_key_group(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["summary", "--period", "mtd", "--group", "api-key", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    amounts = {(row["group"], row["provider"]): row["amount"] for row in payload["summary"]}
    assert amounts == {
        ("key_1", "openai"): "1.50",
        ("Unsupported/Unattributed", "anthropic"): "2.25",
    }


def test_summary_day_project_workspace_group(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["summary", "--period", "mtd", "--group", "day-project-workspace", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    amounts = {(row["group"], row["provider"]): row["amount"] for row in payload["summary"]}
    assert amounts == {
        ("2026-07-01 / Lab", "openai"): "1.50",
        ("2026-07-01 / Product", "anthropic"): "2.25",
    }


def test_doctor_redacts_keys(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "sk-admin-secret" not in result.stdout
    assert "sk-ant-admin01-secret" not in result.stdout
