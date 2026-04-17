"""Central config — loaded once at startup from env (and optionally sops-decrypted file)."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core
    env: str = Field(default="dev", alias="DONNA_ENV")
    data_dir: Path = Field(default=Path("./data"), alias="DONNA_DATA_DIR")
    log_level: str = Field(default="INFO", alias="DONNA_LOG_LEVEL")
    process_role: str = Field(default="bot", alias="DONNA_PROCESS_ROLE")

    # Discord
    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    discord_allowed_user_id: int = Field(default=0, alias="DISCORD_ALLOWED_USER_ID")
    discord_guild_id: int | None = Field(default=None, alias="DISCORD_GUILD_ID")

    # Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model_fast: str = Field(
        default="claude-haiku-4-5-20251001", alias="ANTHROPIC_MODEL_FAST"
    )
    anthropic_model_strong: str = Field(
        default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL_STRONG"
    )
    anthropic_model_heavy: str = Field(
        default="claude-opus-4-6", alias="ANTHROPIC_MODEL_HEAVY"
    )

    # Tavily
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # Voyage
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")
    voyage_embed_model: str = Field(default="voyage-3", alias="VOYAGE_EMBED_MODEL")

    # Concurrency / budgets
    max_concurrent_jobs: int = Field(default=3, alias="DONNA_MAX_CONCURRENT_JOBS")
    daily_budget_alerts: str = Field(default="5,15,30", alias="DONNA_DAILY_BUDGET_ALERTS")
    max_tool_calls_per_job: int = Field(default=60, alias="DONNA_MAX_TOOL_CALLS_PER_JOB")
    compact_every_n: int = Field(default=20, alias="DONNA_COMPACT_EVERY_N")

    # OTel
    otel_endpoint: str = Field(
        default="http://phoenix:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(default="donna", alias="OTEL_SERVICE_NAME")

    # Rate limits (conservative defaults)
    rate_haiku_rpm: int = Field(default=4000, alias="DONNA_RATE_HAIKU_RPM")
    rate_haiku_itpm: int = Field(default=400000, alias="DONNA_RATE_HAIKU_ITPM")
    rate_haiku_otpm: int = Field(default=80000, alias="DONNA_RATE_HAIKU_OTPM")
    rate_sonnet_rpm: int = Field(default=4000, alias="DONNA_RATE_SONNET_RPM")
    rate_sonnet_itpm: int = Field(default=400000, alias="DONNA_RATE_SONNET_ITPM")
    rate_sonnet_otpm: int = Field(default=80000, alias="DONNA_RATE_SONNET_OTPM")
    rate_opus_rpm: int = Field(default=4000, alias="DONNA_RATE_OPUS_RPM")
    rate_opus_itpm: int = Field(default=200000, alias="DONNA_RATE_OPUS_ITPM")
    rate_opus_otpm: int = Field(default=40000, alias="DONNA_RATE_OPUS_OTPM")

    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "donna.db"

    @property
    def artifacts_dir(self) -> Path:
        d = self.data_dir / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def budget_thresholds(self) -> list[float]:
        return [float(x) for x in self.daily_budget_alerts.split(",") if x.strip()]


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
