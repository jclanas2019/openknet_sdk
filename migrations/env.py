"""
Alembic migration environment.

Reads DB URL from OPENKNET_DATABASE_URL environment variable,
falling back to SQLite in workspace_root.

Usage:
    alembic upgrade head          # apply all pending migrations
    alembic revision --autogenerate -m "add foo column"  # generate migration
    alembic downgrade -1          # roll back one migration
    alembic current               # show current revision
    alembic history               # show migration history
"""
from __future__ import annotations
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make openknet importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openknet.db import Base
from openknet.models import orm  # noqa: F401 — registers all ORM models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve DB URL from env, stripping async drivers (Alembic uses sync)."""
    from openknet.config import settings
    url = settings.get_db_url()
    # Alembic needs sync drivers
    url = url.replace("+asyncpg", "").replace("+aiosqlite", "")
    return url


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
