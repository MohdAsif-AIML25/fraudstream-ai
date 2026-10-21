"""Alembic runtime: connects to the database and runs migrations.

Where does the URL come from?
  1. -x url=...   on the command line (handy for tests: alembic -x url=sqlite:///tmp.db upgrade head)
  2. otherwise    app.config.Settings, i.e. your .env  (same settings the API and worker use)
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.db.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)  # use the [loggers] section of alembic.ini

target_metadata = Base.metadata  # lets 'alembic revision --autogenerate' compare models vs database


def database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url")
    if url:
        return url
    from app.config import get_settings  # imported lazily: tests with -x url don't need a .env
    return get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    """'alembic upgrade head --sql': print the SQL instead of running it (useful for review)."""
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():  # each upgrade runs inside one transaction (Postgres)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()