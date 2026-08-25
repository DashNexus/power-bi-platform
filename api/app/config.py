"""Typed settings and the feature-flag registry.

Every environment variable the API reads is declared here, so `.env.example` and
this file are the two places to look. `FEATURE_ENV_VARS` maps a feature key to its
`FEATURE_*` override; a flag missing from it still works through the database but
loses the ability to be forced from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Maps each feature key to its controlling environment variable.
# Set FEATURE_<KEY>=true or FEATURE_<KEY>=false to override the database value.
# Env vars always take precedence over whatever is stored in feature_flags table.
FEATURE_ENV_VARS: dict[str, str] = {
    "dashboards": "FEATURE_DASHBOARDS",
    "custom_pages": "FEATURE_CUSTOM_PAGES",
    "exports": "FEATURE_EXPORTS",
    "governance": "FEATURE_GOVERNANCE",
    "pipelines": "FEATURE_PIPELINES",
    "embed.powerbi": "FEATURE_EMBED_POWERBI",
    "embed.page": "FEATURE_EMBED_PAGE",
    "pipelines.adf": "FEATURE_PIPELINES_ADF",
}

# Project root is three levels up from this file (api/app/config.py → root)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    All secrets and URLs are sourced from environment variables or a .env file.
    Never hardcode values here.
    """

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Databases
    app_database_url: str
    warehouse_database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    storage_uri: str = "file:///data/storage"
    s3_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    # Secrets backend
    secrets_backend: str = "env"

    # Auth
    nextauth_secret: str
    totp_encryption_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Notifications
    notification_channels_enabled: str = "email"

    # SMTP
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None

    # Slack
    slack_bot_token: str | None = None
    slack_default_channel: str = "#data-alerts"

    # Teams
    teams_webhook_url: str | None = None

    # Google Chat
    gchat_webhook_url: str | None = None

    # Twilio
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    # Sentry
    sentry_dsn: str | None = None

    # Azure
    azure_keyvault_url: str | None = None

    # Export reports — resource ceilings. A report runs SQL somebody typed
    # against a live database, so every one of these is a limit on what a bad
    # query can cost, not a tuning knob.
    export_query_timeout_seconds: int = 300
    export_preview_timeout_seconds: int = 30
    export_max_rows: int = 100_000
    export_preview_rows: int = 50
    # Cells, not rows: 100k rows of 3 columns and 1k rows of 300 are the same
    # amount of memory, and only one of them is obvious from a row count.
    export_max_cells: int = 2_000_000

    # GCP
    google_project_id: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list for FastAPI middleware."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def notification_channels_list(self) -> list[str]:
        """Return notification channels as a list."""
        return [ch.strip() for ch in self.notification_channels_enabled.split(",") if ch.strip()]

    @property
    def feature_overrides(self) -> dict[str, bool]:
        """Return feature flags explicitly set via FEATURE_* environment variables.

        Read at call time (not class init) so that monkeypatching os.environ works
        in tests without reloading the settings singleton.
        """
        overrides: dict[str, bool] = {}
        for feature_key, env_var in FEATURE_ENV_VARS.items():
            raw = os.getenv(env_var)
            if raw is not None:
                overrides[feature_key] = raw.lower() in ("true", "1", "yes")
        return overrides


settings = Settings()
