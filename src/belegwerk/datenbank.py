"""Datenbankzugang.

Die Mandantentrennung wird zusaetzlich in der Datenbank durchgesetzt
(Row Level Security, siehe ``belegwerk/kern/mandantentrennung.py``). Dieses
Modul stellt nur Engine und Sitzungsfabrik bereit.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from belegwerk.konfiguration import einstellungen

_log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sitzungsfabrik: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            einstellungen().datenbank_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            echo=False,
        )
    return _engine


def sitzungsfabrik() -> async_sessionmaker[AsyncSession]:
    global _sitzungsfabrik
    if _sitzungsfabrik is None:
        _sitzungsfabrik = async_sessionmaker(engine(), expire_on_commit=False, autoflush=False)
    return _sitzungsfabrik


async def engine_schliessen() -> None:
    global _engine, _sitzungsfabrik
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sitzungsfabrik = None


async def datenbank_erreichbar() -> Any:
    """``True`` bei erreichbarer **und migrierter** Datenbank.

    Eine erreichbare Datenbank ohne Schema ist kein gesunder Zustand: die
    Anwendung nimmt Anfragen an und scheitert an jeder einzelnen. Deshalb wird
    zusätzlich geprüft, dass die Migrationen gelaufen sind — genau dieser Fall
    trat beim ersten Deployment auf, weil der Pre-Deploy-Command fehlte.
    """
    try:
        async with engine().connect() as verbindung:
            await verbindung.execute(text("SELECT 1"))
            stand = (
                await verbindung.execute(
                    text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                )
            ).scalar_one()
            if not stand:
                return "Schema fehlt — die Migrationen sind nicht gelaufen"
        return True
    except Exception as fehler:  # noqa: BLE001 — Health darf nie werfen
        _log.warning("Datenbank nicht erreichbar", extra={"fehlerart": type(fehler).__name__})
        return f"nicht erreichbar ({type(fehler).__name__})"


async def rohe_sitzung() -> AsyncIterator[AsyncSession]:
    """Sitzung ohne Mandantenkontext — nur fuer Anmeldung und Wartungsjobs."""
    async with sitzungsfabrik()() as sitzung:
        yield sitzung
