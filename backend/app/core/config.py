from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the backend/ directory — used to resolve relative session paths
# regardless of the working directory the process was started from.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# .env lives in the project root (one level above backend/).
_ENV_FILE = _BACKEND_DIR.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://wonthurt:changeme@localhost:5432/wonthurtmaps"

    # Telegram
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_channel_name: str = ""
    telegram_session_path: str = "sessions/telegram.session"
    telegram_bootstrap_limit: int = 500

    # Auth
    jwt_secret: str = "changeme"
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Stored as plain string to avoid pydantic-settings JSON-decoding a list field.
    # Use settings.cors_origins_list for the parsed form.
    cors_origins: str = "http://localhost:4200"

    @property
    def telegram_session_path_resolved(self) -> Path:
        """Return an absolute Path to the session file.

        If ``telegram_session_path`` is already absolute it is used as-is.
        Otherwise it is resolved relative to the backend/ directory so the
        path is stable regardless of the working directory the process was
        started from.
        """
        p = Path(self.telegram_session_path)
        return p if p.is_absolute() else _BACKEND_DIR / p

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["http://localhost:4200"]

    # Google Gemini (LLM extraction)
    gemini_api_key: str = ""
    llm_queue_max: int = 500
    llm_max_consecutive_failures: int = 3

    # Google Maps Geocoding
    google_maps_api_key: str = ""
    geocoding_queue_max: int = 500
    geocoding_max_consecutive_failures: int = 3

    # Worker
    pipeline_interval_minutes: int = 60

    @property
    def sync_database_url(self) -> str:
        """Alembic needs a sync URL with explicit psycopg2 driver."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


settings = Settings()
