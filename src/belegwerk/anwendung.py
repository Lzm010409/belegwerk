"""Anwendungsfabrik: baut die FastAPI-Anwendung zusammen."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from belegwerk import __version__
from belegwerk.konfiguration import einstellungen
from belegwerk.protokoll import logging_einrichten
from belegwerk.web.fehlerseiten import fehlerseiten_registrieren
from belegwerk.web.gesundheit import router as gesundheit_router
from belegwerk.web.sicherheit import SicherheitsKopfzeilen
from belegwerk.web.vorlagen import STATIK_VERZEICHNIS

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
    konfiguration = einstellungen()
    for verzeichnis in (konfiguration.upload_verzeichnis, konfiguration.ausgabe_verzeichnis):
        verzeichnis.mkdir(parents=True, exist_ok=True)
    try:
        from belegwerk.kern.erststart import ersten_mandanten_anlegen

        await ersten_mandanten_anlegen()
    except Exception as fehler:  # noqa: BLE001 — Start darf daran nicht scheitern
        _log.error("Erststart fehlgeschlagen", extra={"fehlerart": type(fehler).__name__})
    from belegwerk.kern.auftraege import arbeiter_schleife

    stopp = asyncio.Event()
    arbeiter = asyncio.create_task(arbeiter_schleife(stopp), name="auftragsarbeiter")
    _log.info("Anwendung gestartet", extra={"version": __version__, "umgebung": konfiguration.umgebung})
    yield
    stopp.set()
    try:
        await asyncio.wait_for(arbeiter, timeout=15)
    except (TimeoutError, asyncio.CancelledError):
        arbeiter.cancel()
    from belegwerk.datenbank import engine_schliessen

    await engine_schliessen()
    _log.info("Anwendung beendet")


def anwendung_erzeugen() -> FastAPI:
    logging_einrichten()
    konfiguration = einstellungen()

    app = FastAPI(
        title="Belegwerk",
        version=__version__,
        lifespan=lebenszyklus,
        docs_url="/api/dokumentation" if not konfiguration.ist_produktion else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if not konfiguration.ist_produktion else None,
    )

    app.add_middleware(SicherheitsKopfzeilen, hsts=konfiguration.ist_produktion)
    app.mount("/static", StaticFiles(directory=str(STATIK_VERZEICHNIS)), name="static")

    from belegwerk.atlas.router import router as atlas_router
    from belegwerk.check.router import router as check_router
    from belegwerk.delta.router import router as delta_router
    from belegwerk.kern.router import router as kern_router

    app.include_router(gesundheit_router)
    app.include_router(kern_router)
    app.include_router(check_router)
    app.include_router(delta_router)
    app.include_router(atlas_router)
    fehlerseiten_registrieren(app)
    return app


app = anwendung_erzeugen()
