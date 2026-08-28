"""FastAPI-Abhängigkeiten: angemeldeter Benutzer, Mandantensitzung, CSRF."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.kern import csrf
from belegwerk.kern.anmeldung import COOKIE_NAME, AngemeldeterBenutzer, sitzung_lesen
from belegwerk.kern.mandantentrennung import mandanten_sitzung
from belegwerk.kern.modelle import Modul


async def optionaler_benutzer(request: Request) -> AngemeldeterBenutzer | None:
    """Liest die Sitzung, ohne eine Anmeldung zu erzwingen."""
    if hasattr(request.state, "benutzer"):
        gemerkt: AngemeldeterBenutzer | None = request.state.benutzer
        return gemerkt
    benutzer = await sitzung_lesen(request.cookies.get(COOKIE_NAME, ""))
    request.state.benutzer = benutzer
    return benutzer


class AnmeldungNoetig(Exception):
    """Kein Fehler, sondern eine Umleitung: die Seite setzt Anmeldung voraus."""

    def __init__(self, ziel: str) -> None:
        super().__init__("Anmeldung nötig")
        self.ziel = ziel


async def angemeldet(request: Request) -> AngemeldeterBenutzer:
    benutzer = await optionaler_benutzer(request)
    if benutzer is None:
        raise AnmeldungNoetig(request.url.path)
    return benutzer


async def inhaber(
    benutzer: Annotated[AngemeldeterBenutzer, Depends(angemeldet)],
) -> AngemeldeterBenutzer:
    if not benutzer.ist_inhaber:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diese Einstellung ändert der Inhaber des Büros.",
        )
    return benutzer


async def datenbank(
    benutzer: Annotated[AngemeldeterBenutzer, Depends(angemeldet)],
) -> AsyncIterator[AsyncSession]:
    """Die einzige Datenbanksitzung, die Modulcode benutzen darf."""
    async with mandanten_sitzung(benutzer.mandant_id) as sitzung:
        yield sitzung


async def csrf_geprueft(request: Request) -> None:
    try:
        await csrf.pruefen(request)
    except csrf.CsrfFehler as fehler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(fehler)) from fehler


def modul_noetig(modul: Modul) -> object:
    """Prüft den Modulzugriff gegen ein aktives Abonnement (Querschnitt 2.2)."""

    async def pruefer(
        benutzer: Annotated[AngemeldeterBenutzer, Depends(angemeldet)],
        sitzung: Annotated[AsyncSession, Depends(datenbank)],
    ) -> AngemeldeterBenutzer:
        from belegwerk.kern.abrechnung import zugriff_pruefen

        await zugriff_pruefen(sitzung, modul)
        return benutzer

    return Depends(pruefer)


BenutzerAbh = Annotated[AngemeldeterBenutzer, Depends(angemeldet)]
OptionalerBenutzerAbh = Annotated[AngemeldeterBenutzer | None, Depends(optionaler_benutzer)]
InhaberAbh = Annotated[AngemeldeterBenutzer, Depends(inhaber)]
DatenbankAbh = Annotated[AsyncSession, Depends(datenbank)]
CsrfAbh = Annotated[None, Depends(csrf_geprueft)]
