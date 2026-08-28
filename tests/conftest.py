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


# ---------------------------------------------------------------------------
# Hilfen fuer HTTP-Tests: eigener Ereignisschleifen-Kontext, damit die
# asyncpg-Verbindungen des Testclients nicht an die pytest-Schleife gebunden
# sind.
# ---------------------------------------------------------------------------


def _mit_engine(url: str, arbeit: object) -> object:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def lauf() -> object:
        engine = create_async_engine(url, poolclass=None)
        fabrik = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with fabrik() as s:
                ergebnis = await arbeit(s)  # type: ignore[operator]
                await s.commit()
                return ergebnis
        finally:
            await engine.dispose()

    return asyncio.run(lauf())


def datenbank_leeren(url: str) -> None:
    from sqlalchemy import text

    from belegwerk.basis import Basis
    import belegwerk.modellregister  # noqa: F401

    async def arbeit(s: object) -> None:
        tabellen = ", ".join(t.name for t in reversed(Basis.metadata.sorted_tables))
        await s.execute(text(f"TRUNCATE {tabellen} RESTART IDENTITY CASCADE"))  # type: ignore[attr-defined]

    _mit_engine(url, arbeit)


def buero_anlegen(
    url: str, name: str, email: str, passwort: str, rolle: str = "inhaber"
) -> tuple[str, str]:
    """Legt Mandant, Benutzer und die Testphase an. Gibt (mandant_id, benutzer_id)."""
    from belegwerk.kern import passwoerter
    from belegwerk.kern.abrechnung import testphase_starten
    from belegwerk.kern.modelle import Benutzer, Mandant, Rolle

    hash_wert = passwoerter.hashen(passwort)

    async def arbeit(s: object) -> tuple[str, str]:
        mandant = Mandant(name=name)
        s.add(mandant)  # type: ignore[attr-defined]
        await s.flush()  # type: ignore[attr-defined]
        benutzer = Benutzer(
            mandant_id=mandant.id,
            email=email.lower(),
            name=name + " Inhaber",
            passwort_hash=hash_wert,
            rolle=Rolle(rolle),
        )
        s.add(benutzer)  # type: ignore[attr-defined]
        await testphase_starten(s, mandant.id)  # type: ignore[arg-type]
        await s.flush()  # type: ignore[attr-defined]
        return str(mandant.id), str(benutzer.id)

    return _mit_engine(url, arbeit)  # type: ignore[return-value]


@pytest.fixture()
def klient(migrierte_datenbank: str) -> Iterator["object"]:
    """TestClient auf leerer Datenbank."""
    import os

    from fastapi.testclient import TestClient

    os.environ["DATABASE_URL"] = migrierte_datenbank
    from belegwerk.konfiguration import einstellungen

    einstellungen.cache_clear()
    datenbank_leeren(migrierte_datenbank)

    from belegwerk.anwendung import anwendung_erzeugen
    from belegwerk.kern import ratenbegrenzung

    ratenbegrenzung.alles_zuruecksetzen()
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as c:
        yield c
