from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATEN_VERZEICHNIS", str(WURZEL / ".pytest-daten"))
os.environ.setdefault("SITZUNG_GEHEIMNIS", "test-geheimnis-nur-fuer-tests-0123456789")
os.environ.setdefault("UMGEBUNG", "test")
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://belegwerk@127.0.0.1:5433/belegwerk_test"
)

sys.path.insert(0, str(WURZEL / "src"))


def _datenbank_erreichbar(url: str) -> bool:
    import asyncio

    async def versuch() -> bool:
        import asyncpg  # type: ignore[import-untyped]

        roh = url.replace("postgresql+asyncpg://", "postgresql://")
        try:
            verbindung = await asyncpg.connect(roh, timeout=3)
        except Exception:
            return False
        await verbindung.close()
        return True

    try:
        return asyncio.run(versuch())
    except Exception:
        return False


@pytest.fixture(scope="session")
def datenbank_url() -> str:
    """URL einer laufenden Testdatenbank; ueberspringt, wenn keine da ist."""
    url = os.environ["TEST_DATABASE_URL"]
    if not _datenbank_erreichbar(url):
        pytest.skip("keine Testdatenbank erreichbar (TEST_DATABASE_URL)")
    return url


@pytest.fixture(scope="session")
def migrierte_datenbank(datenbank_url: str) -> Iterator[str]:
    """Spielt die Migrationen einmal je Testlauf ein."""
    umgebung = dict(os.environ, DATABASE_URL=datenbank_url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=WURZEL,
        env=umgebung,
        check=True,
        capture_output=True,
    )
    yield datenbank_url


@pytest.fixture()
async def sitzung(migrierte_datenbank: str) -> AsyncIterator["object"]:
    """Rohe Sitzung (Eigentuemerrolle) auf einer leeren Datenbank."""
    os.environ["DATABASE_URL"] = migrierte_datenbank
    from belegwerk.konfiguration import einstellungen

    einstellungen.cache_clear()
    from belegwerk import datenbank as db

    await db.engine_schliessen()
    from sqlalchemy import text

    from belegwerk.basis import Basis

    async with db.sitzungsfabrik()() as s:
        tabellen = ", ".join(t.name for t in reversed(Basis.metadata.sorted_tables))
        await s.execute(text(f"TRUNCATE {tabellen} RESTART IDENTITY CASCADE"))
        await s.commit()
        yield s
    await db.engine_schliessen()


@pytest.fixture()
def mandant_ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
