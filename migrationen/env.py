"""Alembic-Umgebung. Laeuft asynchron ueber asyncpg — dieselbe URL wie die App."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from belegwerk.basis import Basis
from belegwerk.konfiguration import einstellungen

# Modelle importieren, damit die Metadaten vollstaendig sind.
import belegwerk.kern.modelle  # noqa: F401
from belegwerk import modellregister  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", einstellungen().datenbank_url)
zielmetadaten = Basis.metadata


def migrationen_ausfuehren(verbindung: Connection) -> None:
    context.configure(
        connection=verbindung,
        target_metadata=zielmetadaten,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online_async() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as verbindung:
        await verbindung.run_sync(migrationen_ausfuehren)
        await verbindung.commit()
    await engine.dispose()


def offline() -> None:
    context.configure(
        url=einstellungen().datenbank_url,
        target_metadata=zielmetadaten,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    offline()
else:
    asyncio.run(online_async())
