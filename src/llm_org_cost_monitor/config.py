from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_admin_key: str | None
    anthropic_admin_key: str | None
    openai_label: str
    anthropic_label: str


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        openai_admin_key=os.getenv("OPENAI_ADMIN_KEY"),
        anthropic_admin_key=os.getenv("ANTHROPIC_ADMIN_KEY"),
        openai_label=os.getenv("OPENAI_ACCOUNT_LABEL", "OpenAI"),
        anthropic_label=os.getenv("ANTHROPIC_ACCOUNT_LABEL", "Anthropic"),
    )
