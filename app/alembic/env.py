import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every model module so Base.metadata is fully populated before
# autogenerate diffs against it — app.models defines every table.
import app.models  # noqa: F401,E402
from app.config import settings
from app.database import Base

config = context.config

# Reuse the app's own settings instead of a separate connection string in
# alembic.ini — one source of truth for DATABASE_URL (env var/.env), same
# as every other part of the app.
config.set_main_option("sqlalchemy.url", settings.database_url)

# alembic.ini's [loggers]/[handlers] sections reconfigure the ROOT logger
# via fileConfig() — this clobbers app/logging_config.py's JSON formatter
# whenever alembic.command.upgrade() runs as part of the app's own startup
# (app/main.py's lifespan hook), silently reverting every log line
# (including uvicorn's own) to plain text. A real bug found via live
# verification: the JSON logs worked in isolation but broke on the very
# next app boot once migrations ran. Only apply fileConfig for standalone
# CLI usage (`alembic upgrade head` from a shell, where nothing else has
# configured logging yet) — skip it when the app's own JsonFormatter is
# already installed on the root logger.
_root_already_configured = any(
    type(getattr(h, "formatter", None)).__name__ == "JsonFormatter" for h in logging.getLogger().handlers
)
if config.config_file_name is not None and not _root_already_configured:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
