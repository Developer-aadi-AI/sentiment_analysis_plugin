"""Settings, loaded from environment variables / .env. Never hard-code keys."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-5-5"
    llm_api_key: SecretStr | None = None
    llm_structured_method: str = "auto"
    llm_max_retries: int = 2

    # Source adapter
    adapter: str = "csv"
    source_name: str = "app"
    source_file: str | None = None
    source_field_map: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    source_db_url: str | None = None
    source_table: str = "feedback"
    source_processed_column: str | None = None
    source_context_query: str | None = None
    webhook_secret: SecretStr | None = None
    admin_token: SecretStr | None = None

    # Sink
    sink: str = "smtp"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: str = "support@example.com"

    # Brand voice
    brand_name: str = "Our Team"
    brand_signoff: str = "The Customer Care Team"
    brand_voice: str = "Warm, concise, human."
    brand_never_promise: str = "refunds, discounts, compensation, delivery dates"

    # Safety
    dry_run: bool = True
    auto_send: bool = False
    min_confidence: float = 0.7
    max_body_chars: int = 1500
    max_subject_chars: int = 120
    state_db: str = ".review_responder/state.db"

    # Server: check the source for new reviews every N seconds (0 = off; webhook needs none)
    poll_interval_seconds: int = 0

    @field_validator("source_field_map", mode="before")
    @classmethod
    def _parse_field_map(cls, v: Any) -> Any:
        if isinstance(v, str):
            return json.loads(v) if v.strip() else {}
        return v


@lru_cache
def get_settings() -> Settings:
    # Also export .env into os.environ, so provider SDKs pick up their own key variables
    # (ANTHROPIC_API_KEY, GROQ_API_KEY, ...) when LLM_API_KEY is not set.
    load_dotenv(override=False)
    return Settings()
