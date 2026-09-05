from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Financial AI API"
    cors_origins: str = "https://2026-ai-challenge-fe.vercel.app"
    # Either set DATABASE_URL directly (used for local dev via .env), or set
    # DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD and it's assembled below
    # (matches how Render/Supabase expose connection info as separate fields).
    database_url: str | None = None
    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    openai_api_key: str = ""
    llm_model: str = "gpt-5-mini"
    llm_timeout_seconds: float = 30.0
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.database_url:
            return self
        if self.db_host and self.db_name and self.db_user and self.db_password:
            self.database_url = (
                f"postgresql+psycopg://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}?sslmode=require"
            )
            return self
        raise ValueError(
            "Set DATABASE_URL, or all of DB_HOST/DB_NAME/DB_USER/DB_PASSWORD, "
            "to configure the database connection."
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
