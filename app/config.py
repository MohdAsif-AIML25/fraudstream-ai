"""Application settings, loaded once from environment variables or .env."""

from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    redis_url: str = "redis://localhost:6379/0"

    # Day 4: where the Kafka broker listens (host side of docker-compose)
    kafka_bootstrap_servers: str = "127.0.0.1:9092"

    # scoring worker 
    consumer_group: str = "fraud-scorer"   # all worker copies share this name -> Kafka splits partitions between them
    model_path: str = "artifacts/fraud_model_v1.joblib"          # binary (gitignored)
    model_meta_path: str = "artifacts_meta/fraud_model_v1.json"  # features + thresholds (committed)
    history_ttl_days: int = 30             # Redis forgets an account that has been silent for 30 days


    
    @property
    def postgres_dsn(self) -> str:
        """Build the connection URL. Credentials are percent-encoded so characters
        like @ : / # in a password can't break the URL structure."""
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        """Same DSN, but tells SQLAlchemy to use the psycopg (v3) driver we installed on Day 1."""
        return self.postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache  # first call creates Settings; later calls return the SAME object
def get_settings() -> Settings:
    return Settings()