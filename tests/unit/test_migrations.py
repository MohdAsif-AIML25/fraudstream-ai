"""Migration tests: the Alembic history must build EXACTLY the schema our models describe.

If someone adds a column to models.py but forgets the migration, this test fails in CI
instead of the API failing in production with "column does not exist".
"""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db.models import Base


def alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={url}"]})()  # same as: alembic -x url=...
    return cfg


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"models.py and migrations disagree: {diff}"


def test_downgrade_removes_day5_changes(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")  # step back one version, like a rollback

    inspector = inspect(create_engine(url))
    assert "review_cases" not in inspector.get_table_names()
    assert "features" not in {c["name"] for c in inspector.get_columns("transactions")}