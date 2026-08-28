"""Health-Endpoint.

Plattformdatei Abschnitt 5: prueft die Abhaengigkeiten, nicht nur, ob der
Prozess lebt.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from belegwerk import __version__

router = APIRouter()


async def _pruefungen() -> dict[str, Any]:
    from belegwerk.datenbank import datenbank_erreichbar

    ergebnis: dict[str, Any] = {}
    ergebnis["datenbank"] = await datenbank_erreichbar()
    return ergebnis


@router.get("/gesundheit", include_in_schema=False)
async def gesundheit() -> JSONResponse:
    pruefungen = await _pruefungen()
    gesund = all(wert is True for wert in pruefungen.values())
    return JSONResponse(
        {"status": "gesund" if gesund else "gestoert", "version": __version__, "pruefungen": pruefungen},
        status_code=200 if gesund else 503,
    )
