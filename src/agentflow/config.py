"""Validated local defaults; no credentials or tenant clients."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from agentflow.domain import StrictModel

DATA = Path(__file__).with_name("data")


class Settings(StrictModel):
    provider: Literal["mock", "ollama"] = "mock"
    integrations: Literal["simulated"] = "simulated"
    mode: Literal["offline"] = "offline"
    db_path: str = "data/agentflow.sqlite3"
    webhook_secret: str | None = Field(default=None, min_length=32, repr=False)
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "local-model-name"
    mcp_persona: Literal["viewer", "editor", "reviewer", "admin"] = "editor"

    @classmethod
    def local_ollama_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama must use an explicit local HTTP origin.")
        return value.rstrip("/")

    @classmethod
    def from_env(cls) -> "Settings":
        if os.getenv("AGENTFLOW_ALLOW_REAL_CLOUD", "false").lower() != "false":
            raise ValueError("Real cloud integrations are unavailable; use false.")
        db_url = os.getenv("AGENTFLOW_DB_URL", "sqlite:///./data/agentflow.sqlite3")
        if not db_url.startswith("sqlite:///"):
            raise ValueError("Only local SQLite is supported.")
        secret = os.getenv("AGENTFLOW_WEBHOOK_SECRET")
        if secret == "REPLACE_WITH_LONG_RANDOM_LOCAL_DEV_SECRET":
            secret = None
        if secret and len(secret) < 32:
            raise ValueError("Local webhook secret must be at least 32 characters.")
        return cls(
            provider=os.getenv("PROVIDER", os.getenv("AGENTFLOW_PROVIDER", "mock")),
            integrations=os.getenv(
                "INTEGRATIONS", os.getenv("AGENTFLOW_INTEGRATIONS", "simulated")
            ),
            mode=os.getenv("AGENTFLOW_MODE", "offline"),
            db_path=db_url.removeprefix("sqlite:///"),
            webhook_secret=secret,
            ollama_url=cls.local_ollama_url(
                os.getenv("AGENTFLOW_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            ),
            ollama_model=os.getenv("AGENTFLOW_OLLAMA_MODEL", "local-model-name"),
            mcp_persona=os.getenv("AGENTFLOW_MCP_PERSONA", "editor"),
        )
