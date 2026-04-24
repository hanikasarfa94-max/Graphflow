from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKGRAPH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod"] = Field(
        default="dev",
        description="Deployment environment. Required.",
    )
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/workgraph.sqlite",
        description="SQLAlchemy async URL. Swap to postgres+asyncpg for prod.",
    )
    redis_url: str | None = Field(
        default=None,
        description="Optional Redis URL (redis://host:port/0). Enables multi-node WS fanout.",
    )
    use_stubs: bool = Field(
        default=False,
        description=(
            "Wire every LLM agent to deterministic stubs instead of DeepSeek. "
            "Use for demo-day and local UI work — the canonical flow runs "
            "in under a second and costs nothing."
        ),
    )
    membrane_active_interval_minutes: int = Field(
        default=0,
        description=(
            "Active-membrane cron interval (Phase 2.A). 0 disables the "
            "in-process scheduler entirely — production points an "
            "external cron at POST /api/projects/{id}/membrane/scan-now "
            "instead. Dev can set e.g. 30 to exercise the pipeline."
        ),
    )

    # --- Feishu webhook authenticity -------------------------------------
    # These env vars are NOT WORKGRAPH_-prefixed — they match Feishu's own
    # dashboard naming so ops can copy them verbatim from Lark.
    feishu_app_id: str | None = Field(
        default=None,
        validation_alias="FEISHU_APP_ID",
        description="Feishu/Lark app id. Informational — not used for auth.",
    )
    feishu_app_secret: str | None = Field(
        default=None,
        validation_alias="FEISHU_APP_SECRET",
        description=(
            "Feishu/Lark encryption secret. When set, webhooks must carry "
            "X-Lark-Request-Timestamp / X-Lark-Request-Nonce / "
            "X-Lark-Signature headers that verify via HMAC-SHA256."
        ),
    )
    feishu_verification_token: str | None = Field(
        default=None,
        validation_alias="FEISHU_VERIFICATION_TOKEN",
        description=(
            "Feishu/Lark verification token. Used when signature mode is "
            "not configured — payload.token must match exactly."
        ),
    )


def load_settings() -> Settings:
    try:
        return Settings()
    except Exception as exc:
        msg = (
            "WorkGraph API failed to load settings. "
            "Copy .env.example to .env and set required WORKGRAPH_* variables. "
            f"Underlying error: {exc}"
        )
        raise RuntimeError(msg) from exc
