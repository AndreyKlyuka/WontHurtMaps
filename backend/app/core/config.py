from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://wonthurt:changeme@localhost:5432/wonthurtmaps"

    # Telegram
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_channel_link: str = ""

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
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["http://localhost:4200"]

    # Worker
    pipeline_interval_minutes: int = 60
    nominatim_rate_limit: float = 1.0
    nominatim_queue_max: int = 500

    @property
    def sync_database_url(self) -> str:
        """Alembic needs a sync URL with explicit psycopg2 driver."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


settings = Settings()
