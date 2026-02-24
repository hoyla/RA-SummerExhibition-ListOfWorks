import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Ensure the project root is on sys.path so "backend.app..." imports work
# when running `alembic` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.config import DATABASE_URL  # noqa: E402
from backend.app.db import Base  # noqa: E402

# Import every model so Base.metadata is fully populated
import backend.app.models.import_model  # noqa: F401, E402
import backend.app.models.section_model  # noqa: F401, E402
import backend.app.models.work_model  # noqa: F401, E402
import backend.app.models.override_model  # noqa: F401, E402
import backend.app.models.ruleset_model  # noqa: F401, E402
import backend.app.models.validation_warning_model  # noqa: F401, E402
import backend.app.models.audit_log_model  # noqa: F401, E402
import backend.app.models.export_snapshot_model  # noqa: F401, E402
import backend.app.models.index_artist_model  # noqa: F401, E402
import backend.app.models.index_cat_number_model  # noqa: F401, E402
import backend.app.models.index_override_model  # noqa: F401, E402
import backend.app.models.known_artist_model  # noqa: F401, E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url from the environment so we never need to
# hard-code credentials in alembic.ini.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at our models' metadata for autogenerate support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
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
