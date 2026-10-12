"""Application settings, loaded once from environment variables or .env."""

from functools import lru_cache  # caches a function's return value
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every field maps to an environment variable with the same name (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=".env",            # read values from .env in the project root
        env_file_encoding="utf-8",
        extra="ignore",             # ignore .env keys this class doesn't define
    )

    app_env: str = "local"          # has a default, so it's optional

    postgres_user: str              # no default, so the app FAILS AT STARTUP if missing (fail fast)
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432       # "5432" text from .env is converted to int automatically

    redis_url: str = "redis://localhost:6379/0"

    @property
    def postgres_dsn(self) -> str:
        """Build the connection URL. Credentials are percent-encoded so characters
        like @ : / # in a password can't break the URL structure."""
        user = quote(self.postgres_user, safe="")          # safe="" encodes EVERY special char, including /
        password = quote(self.postgres_password, safe="")  # 'MYsql123@' becomes 'MYsql123%40'
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache  # first call creates Settings; later calls return the SAME object (no re-reading .env)
def get_settings() -> Settings:
    return Settings()