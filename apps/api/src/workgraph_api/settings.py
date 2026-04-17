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
