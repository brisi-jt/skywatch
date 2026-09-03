from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import skywatch.db.models  # noqa: F401  (register tables on the shared metadata)
from skywatch.db.fts import include_name

config = context.config
target_metadata = SQLModel.metadata

_SQLITE_FILE_PREFIX = "sqlite:///"


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        from skywatch.db.engine import default_db_path, sqlite_url
        from skywatch.settings import Settings

        url = sqlite_url(default_db_path(Settings().data_root))

    if url.startswith(_SQLITE_FILE_PREFIX):
        Path(url.removeprefix(_SQLITE_FILE_PREFIX)).parent.mkdir(parents=True, exist_ok=True)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_name=include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
