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


def test_summary_csv(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["summary", "--period", "last-7d", "--group", "line-item", "--format", "csv"])

    assert result.exit_code == 0
    assert "group,provider,currency,amount,records" in result.stdout
    assert "Responses API,openai,USD,1.50,1" in result.stdout
    assert "Input Tokens,anthropic,USD,2.25,1" in result.stdout


def test_doctor_redacts_keys(monkeypatch):
    patch_clients(monkeypatch)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert "sk-admin-secret" not in result.stdout
    assert "sk-ant-admin01-secret" not in result.stdout
