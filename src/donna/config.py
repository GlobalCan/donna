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

    # Slack
    # bot token (xoxb-...) — Web API auth, scoped to the workspace
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    # app-level token (xapp-...) with `connections:write` — Socket Mode
    slack_app_token: str = Field(default="", alias="SLACK_APP_TOKEN")
    # workspace allowlist (T0...) — every event is checked against this
    slack_team_id: str = Field(default="", alias="SLACK_TEAM_ID")
    # solo-operator allowlist (U0...) — only this user's events are processed
    slack_allowed_user_id: str = Field(default="", alias="SLACK_ALLOWED_USER_ID")

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

    # v0.7.3 (Codex #11 operator fatigue): alert digest interval. When 0,
    # alerts (delivery dead-letter, budget, stuck-job, recent-failures)
    # DM the operator immediately — preserving v0.7.x soak behavior.
    # Set to >= 1 to opt in to queued-and-batched alert delivery: each
    # alert lands in `alert_digest_queue`; a background flusher posts
    # one merged DM per interval if there's anything to send. Suggested
    # operator value: 30 (one digest every 30 min).
    alert_digest_interval_min: int = Field(
        default=0, alias="DONNA_ALERT_DIGEST_INTERVAL_MIN",
    )

    # v0.6 #7: HARD caps that gate new job intake. Soft alerts at
    # daily_budget_alerts thresholds remain (they DM the operator).
    # Hard caps go further: when exceeded, intake refuses new jobs with
    # an explicit "spending paused" reply. Set to 0 to disable (keeps
    # only the soft-alert behavior). Default values are conservative
    # for solo-bot personal use; raise via env if you actually need to.
    daily_hard_cap_usd: float = Field(
        default=20.0, alias="DONNA_DAILY_HARD_CAP_USD",
    )
    weekly_hard_cap_usd: float = Field(
        default=100.0, alias="DONNA_WEEKLY_HARD_CAP_USD",
    )

    # OTel — default targets the local trace backend (jaeger all-in-one,
    # service name `jaeger` in docker-compose). Was `phoenix:4317` before
    # the 14.x breakage forced a swap. Keeping the OTLP-gRPC port at 4317
    # means the exporter code is unchanged; only the hostname moves.
    otel_endpoint: str = Field(
        default="http://jaeger:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
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
