from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_LEDGER_PATH = Path.home() / ".config" / "llm-org-cost-monitor" / "ledger.json"


@dataclass(frozen=True)
class Settings:
    openai_admin_key: str | None
    anthropic_admin_key: str | None
    openai_label: str
    anthropic_label: str
    ledger_path: Path


def load_settings() -> Settings:
    load_dotenv()
    ledger_override = os.getenv("LLM_ORG_COST_LEDGER")
    return Settings(
        openai_admin_key=os.getenv("OPENAI_ADMIN_KEY"),
        anthropic_admin_key=os.getenv("ANTHROPIC_ADMIN_KEY"),
        openai_label=os.getenv("OPENAI_ACCOUNT_LABEL", "OpenAI"),
        anthropic_label=os.getenv("ANTHROPIC_ACCOUNT_LABEL", "Anthropic"),
        ledger_path=Path(ledger_override).expanduser() if ledger_override else DEFAULT_LEDGER_PATH,
    )
