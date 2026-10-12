"""Check that PostgreSQL and Redis are reachable with the configured settings.

Run from the project root:  python -m scripts.check_services
(-m runs it as a module, so 'import app' works.)
"""

import sys

import psycopg
import redis

from app.config import get_settings


def check_postgres(dsn: str) -> bool:
    try:
        # 'with' closes the connection automatically, even if an error happens
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            version = conn.execute("SELECT version();").fetchone()[0]  # fetchone() returns a tuple
        print(f"[OK]   PostgreSQL -> {version.split(',')[0]}")
        return True
    except psycopg.OperationalError as exc:  # wrong password, server down, wrong port...
        print(f"[FAIL] PostgreSQL -> {exc}")
        return False


def check_redis(url: str) -> bool:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=3)
        client.ping()  # raises an exception if Redis doesn't answer
        print("[OK]   Redis -> PONG")
        return True
    except redis.exceptions.ConnectionError as exc:
        print(f"[FAIL] Redis -> {exc}")
        return False


def main() -> int:
    settings = get_settings()
    results = [check_postgres(settings.postgres_dsn), check_redis(settings.redis_url)]
    return 0 if all(results) else 1  # exit code 0 = success, 1 = failure (CI tools read this)


if __name__ == "__main__":  
    sys.exit(main())