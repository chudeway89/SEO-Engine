"""Alembic environment.

The migration target is always the metadata assembled by importing every ORM
model, so ``alembic revision --autogenerate`` sees the whole schema.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

import seo_engine.domain.models  # noqa: F401  (registers every table)
from alembic import context
from seo_engine.shared.config import get_settings
from seo_engine.shared.db import Base
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sync_database_url)


#: Migrations are authored one domain at a time so the history reads like the
#: Build Specification (0001_identity, 0002_brands, ...).  The generator script
#: `database/build_migrations.py` sets this to the table set of the domain it is
#: currently authoring; it is unset during normal upgrades.
_TABLE_SCOPE = {
    name.strip() for name in os.environ.get("ALEMBIC_TABLE_SCOPE", "").split(",") if name.strip()
}


def include_object(obj, name, type_, reflected, compare_to):
    # pgvector creates its own internal objects; never manage them here.
    if type_ == "table" and name in {"vector", "spatial_ref_sys"}:
        return False
    if _TABLE_SCOPE and type_ == "table" and name not in _TABLE_SCOPE:
        return False
    if _TABLE_SCOPE and type_ in {"index", "unique_constraint", "foreign_key_constraint"}:
        table_name = getattr(getattr(obj, "table", None), "name", None)
        if table_name and table_name not in _TABLE_SCOPE:
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
