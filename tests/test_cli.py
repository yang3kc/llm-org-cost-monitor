import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from llm_org_cost_monitor import cli
from llm_org_cost_monitor.models import CostRecord, ProviderStatus
from llm_org_cost_monitor.providers import MissingKeyError, ProviderAPIError

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


def patch_ledger(monkeypatch, tmp_path):
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setenv("LLM_ORG_COST_LEDGER", str(ledger_path))
    return ledger_path


def write_ledger(path, entries):
    path.write_text(json.dumps({"version": 1, "entries": entries}))


def ledger_entry(provider, entry_type, entry_date, amount):
    return {"provider": provider, "type": entry_type, "date": entry_date, "amount": amount, "currency": "USD"}


class NeverBuiltClient:
    def __init__(self, key, label):
        raise AssertionError("provider client should not be built")


class BalanceFakeOpenAI:
    captured = {}

    def __init__(self, key, label):
        self.label = label

    def fetch_costs(self, date_range):
        type(self).captured["openai"] = date_range
        return [
            CostRecord(
                provider="openai",
                account_label=self.label,
                date=date(2020, 1, 6),
                amount=Decimal("10.00"),
                currency="USD",
            ),
            CostRecord(
                provider="openai",
                account_label=self.label,
                date=date(2020, 1, 7),
                amount=Decimal("5.50"),
                currency="USD",
            ),
        ], []


class BalanceFakeAnthropic:
    captured = {}

    def __init__(self, key, label):
        self.label = label

    def fetch_costs(self, date_range):
        type(self).captured["anthropic"] = date_range
        return [
            CostRecord(
                provider="anthropic",
                account_label=self.label,
                date=date(2020, 2, 2),
                amount=Decimal("2.25"),
                currency="USD",
            )
        ], []


class KeylessAnthropic:
    def __init__(self, key, label):
        raise MissingKeyError("ANTHROPIC_ADMIN_KEY is not set")


def make_failing_client(provider_name):
    class FailingClient:
        def __init__(self, key, label):
            self.label = label

        def fetch_costs(self, date_range):
            raise ProviderAPIError(provider_name, 500, "boom")

    return FailingClient


def patch_balance_clients(monkeypatch, tmp_path, openai=BalanceFakeOpenAI, anthropic=BalanceFakeAnthropic):
    ledger_path = patch_ledger(monkeypatch, tmp_path)
    patch_clients(monkeypatch)
    monkeypatch.setattr(cli, "OpenAICostClient", openai)
    monkeypatch.setattr(cli, "AnthropicCostClient", anthropic)
    BalanceFakeOpenAI.captured = {}
    BalanceFakeAnthropic.captured = {}
    return ledger_path


def test_balance_set_add_log_work_without_keys(monkeypatch, tmp_path):
    ledger_path = patch_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OpenAICostClient", NeverBuiltClient)
    monkeypatch.setattr(cli, "AnthropicCostClient", NeverBuiltClient)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)

    set_result = runner.invoke(
        cli.app, ["balance", "set", "openai", "120.50", "--date", "2020-01-05", "--note", "after top-up"]
    )
    add_result = runner.invoke(cli.app, ["balance", "add", "openai", "25.00", "--date", "2020-01-10"])
    log_result = runner.invoke(cli.app, ["balance", "log"])

    assert set_result.exit_code == 0
    assert add_result.exit_code == 0
    assert log_result.exit_code == 0
    raw = json.loads(ledger_path.read_text())
    assert raw["version"] == 2
    assert [(item["type"], item["amount"]) for item in raw["entries"]] == [("set", "120.50"), ("add", "25.00")]
    assert raw["entries"][0]["note"] == "after top-up"
    assert "120.50" in log_result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["balance", "set", "openai", "abc"],
        ["balance", "set", "openai", "--", "-5"],
        ["balance", "add", "openai", "0"],
        ["balance", "add", "openai", "--", "-1"],
        ["balance", "adjust", "openai", "0"],
        ["balance", "adjust", "openai", "abc"],
        ["balance", "set", "openai", "10", "--date", "2026-13-01"],
    ],
)
def test_balance_rejects_bad_parameters(monkeypatch, tmp_path, args):
    patch_ledger(monkeypatch, tmp_path)

    result = runner.invoke(cli.app, args)

    assert result.exit_code == 2


def test_balance_rejects_future_date(monkeypatch, tmp_path):
    patch_ledger(monkeypatch, tmp_path)
    future = (date.today() + timedelta(days=2)).isoformat()

    result = runner.invoke(cli.app, ["balance", "set", "openai", "10", "--date", future])

    assert result.exit_code == 2


def test_balance_show_json_estimates(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(monkeypatch, tmp_path)
    write_ledger(
        ledger_path,
        [
            ledger_entry("openai", "set", "2020-01-05", "100.00"),
            ledger_entry("openai", "add", "2020-01-10", "20.00"),
            ledger_entry("anthropic", "set", "2020-02-01", "50.00"),
        ],
    )

    result = runner.invoke(cli.app, ["balance", "show", "--format", "json"])

    assert result.exit_code == 0
    openai_range = BalanceFakeOpenAI.captured["openai"]
    assert openai_range.start == date(2020, 1, 5)
    assert openai_range.end_exclusive == date.today() + timedelta(days=1)
    anthropic_range = BalanceFakeAnthropic.captured["anthropic"]
    assert anthropic_range.start == date(2020, 2, 1)
    payload = json.loads(result.stdout)
    by_provider = {row["provider"]: row for row in payload["balances"]}
    assert by_provider["openai"]["anchor_amount"] == "100.00"
    assert by_provider["openai"]["purchases_since"] == "20.00"
    assert by_provider["openai"]["spend_since"] == "15.50"
    assert by_provider["openai"]["estimated_balance"] == "104.50"
    assert by_provider["anthropic"]["estimated_balance"] == "47.75"


def test_balance_show_missing_key_gives_ledger_only_row(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(monkeypatch, tmp_path, anthropic=KeylessAnthropic)
    write_ledger(
        ledger_path,
        [
            ledger_entry("openai", "set", "2020-01-05", "100.00"),
            ledger_entry("anthropic", "set", "2020-02-01", "50.00"),
        ],
    )

    result = runner.invoke(cli.app, ["balance", "show", "--format", "json"])

    assert result.exit_code == 0
    assert "ANTHROPIC_ADMIN_KEY is not set" in result.stderr
    payload = json.loads(result.stdout)
    by_provider = {row["provider"]: row for row in payload["balances"]}
    assert by_provider["anthropic"]["anchor_amount"] == "50.00"
    assert by_provider["anthropic"]["spend_since"] is None
    assert by_provider["anthropic"]["estimated_balance"] is None
    assert by_provider["openai"]["estimated_balance"] == "84.50"


def test_balance_show_all_providers_failing_exits_1(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(
        monkeypatch, tmp_path, openai=make_failing_client("openai"), anthropic=make_failing_client("anthropic")
    )
    write_ledger(
        ledger_path,
        [
            ledger_entry("openai", "set", "2020-01-05", "100.00"),
            ledger_entry("anthropic", "set", "2020-02-01", "50.00"),
        ],
    )

    result = runner.invoke(cli.app, ["balance", "show"])

    assert result.exit_code == 1
    assert "Error:" in result.stderr


def test_balance_show_provider_filter_skips_other_client(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(monkeypatch, tmp_path, anthropic=NeverBuiltClient)
    write_ledger(
        ledger_path,
        [
            ledger_entry("openai", "set", "2020-01-05", "100.00"),
            ledger_entry("anthropic", "set", "2020-02-01", "50.00"),
        ],
    )

    result = runner.invoke(cli.app, ["balance", "show", "--provider", "openai", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [row["provider"] for row in payload["balances"]] == ["openai"]


def test_balance_show_csv_header(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(monkeypatch, tmp_path)
    write_ledger(ledger_path, [ledger_entry("openai", "set", "2020-01-05", "100.00")])

    result = runner.invoke(cli.app, ["balance", "show", "--format", "csv"])

    assert result.exit_code == 0
    header = result.stdout.splitlines()[0]
    assert header == (
        "provider,label,anchor_date,anchor_amount,purchases_since,adjustments_since,"
        "spend_since,estimated_balance,currency,as_of"
    )


def test_balance_show_empty_ledger_exits_1(monkeypatch, tmp_path):
    patch_balance_clients(monkeypatch, tmp_path, openai=NeverBuiltClient, anthropic=NeverBuiltClient)

    result = runner.invoke(cli.app, ["balance", "show"])

    assert result.exit_code == 1


def test_balance_corrupt_ledger_exits_1(monkeypatch, tmp_path):
    ledger_path = patch_ledger(monkeypatch, tmp_path)
    ledger_path.write_text("not json")

    show_result = runner.invoke(cli.app, ["balance", "show"])
    log_result = runner.invoke(cli.app, ["balance", "log"])
    set_result = runner.invoke(cli.app, ["balance", "set", "openai", "10"])

    assert show_result.exit_code == 1
    assert log_result.exit_code == 1
    assert set_result.exit_code == 1
    assert "Error:" in show_result.stderr


def test_balance_adjust_works_without_keys(monkeypatch, tmp_path):
    ledger_path = patch_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OpenAICostClient", NeverBuiltClient)
    monkeypatch.setattr(cli, "AnthropicCostClient", NeverBuiltClient)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)

    set_result = runner.invoke(cli.app, ["balance", "set", "openai", "100.00", "--date", "2020-01-05"])
    adjust_result = runner.invoke(
        cli.app,
        ["balance", "adjust", "--date", "2020-01-10", "--note", "credits expired", "--", "openai", "-13.73"],
    )

    assert set_result.exit_code == 0
    assert adjust_result.exit_code == 0
    raw = json.loads(ledger_path.read_text())
    assert [(item["type"], item["amount"]) for item in raw["entries"]] == [("set", "100.00"), ("adjust", "-13.73")]
    assert raw["entries"][1]["note"] == "credits expired"


def test_balance_adjust_accepts_negative_amount_after_separator(monkeypatch, tmp_path):
    ledger_path = patch_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OpenAICostClient", NeverBuiltClient)
    monkeypatch.setattr(cli, "AnthropicCostClient", NeverBuiltClient)

    result = runner.invoke(cli.app, ["balance", "adjust", "openai", "--", "-13.73"])

    assert result.exit_code == 0
    raw = json.loads(ledger_path.read_text())
    assert raw["entries"][0]["amount"] == "-13.73"


def test_balance_adjust_shows_in_log(monkeypatch, tmp_path):
    patch_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OpenAICostClient", NeverBuiltClient)
    monkeypatch.setattr(cli, "AnthropicCostClient", NeverBuiltClient)

    runner.invoke(cli.app, ["balance", "adjust", "--note", "credits expired", "--", "openai", "-13.73"])
    log_result = runner.invoke(cli.app, ["balance", "log"])

    assert log_result.exit_code == 0
    assert "adjust" in log_result.stdout
    assert "-13.73" in log_result.stdout


def test_balance_show_json_applies_adjustments(monkeypatch, tmp_path):
    ledger_path = patch_balance_clients(monkeypatch, tmp_path)
    write_ledger(
        ledger_path,
        [
            ledger_entry("openai", "set", "2020-01-05", "100.00"),
            ledger_entry("openai", "add", "2020-01-10", "20.00"),
            ledger_entry("openai", "adjust", "2020-01-12", "-13.73"),
            ledger_entry("anthropic", "set", "2020-02-01", "50.00"),
        ],
    )

    result = runner.invoke(cli.app, ["balance", "show", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_provider = {row["provider"]: row for row in payload["balances"]}
    assert by_provider["openai"]["purchases_since"] == "20.00"
    assert by_provider["openai"]["adjustments_since"] == "-13.73"
    assert by_provider["openai"]["estimated_balance"] == "90.77"
    assert by_provider["anthropic"]["adjustments_since"] == "0"


def test_balance_adjust_confirmation_says_adjustment(monkeypatch, tmp_path):
    patch_ledger(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OpenAICostClient", NeverBuiltClient)
    monkeypatch.setattr(cli, "AnthropicCostClient", NeverBuiltClient)

    result = runner.invoke(cli.app, ["balance", "adjust", "openai", "--", "-13.73"])

    assert result.exit_code == 0
    assert "adjustment" in result.stdout
    assert "top-up" not in result.stdout
