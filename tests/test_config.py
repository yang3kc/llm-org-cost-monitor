from pathlib import Path

from llm_org_cost_monitor import config


def test_default_ledger_path(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.delenv("LLM_ORG_COST_LEDGER", raising=False)

    settings = config.load_settings()

    assert settings.ledger_path == config.DEFAULT_LEDGER_PATH
    assert settings.ledger_path == Path.home() / ".config" / "llm-org-cost-monitor" / "ledger.json"


def test_ledger_path_env_override_expands_home(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("LLM_ORG_COST_LEDGER", "~/custom/ledger.json")

    settings = config.load_settings()

    assert settings.ledger_path == Path.home() / "custom" / "ledger.json"
