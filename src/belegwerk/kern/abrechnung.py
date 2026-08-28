"""Abonnements und Modulzugriff (Querschnitt 2).

Der Zugriff auf ein Modul hängt an einem Abonnement, nicht an einem
handgesetzten Flag. Nach Ablauf der Testphase bleiben die eigenen Daten lesbar,
neue Vorgänge lassen sich nicht mehr anlegen — gelöscht wird nichts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.konfiguration import einstellungen
from belegwerk.kern.modelle import Abonnement, AbonnementStatus, Modul

MODULNAMEN = {Modul.DELTA: "Delta", Modul.ATLAS: "Atlas", Modul.CHECK: "Check"}
MODULBESCHREIBUNG = {
    Modul.DELTA: "Kalkulationsvergleich",
    Modul.ATLAS: "Stundensatz-Register",
    Modul.CHECK: "Endkontrolle",
}
LISTENPREIS = {Modul.DELTA: "49,00", Modul.ATLAS: "29,00", Modul.CHECK: "39,00"}


class ModulGesperrt(HTTPException):
    def __init__(self, modul: Modul, grund: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=grund)
        self.modul = modul


@dataclass(frozen=True, slots=True)
class Zugriff:
    modul: Modul
    lesen: bool
    schreiben: bool
    status: AbonnementStatus | None
    ende: date | None

    @property
    def name(self) -> str:
        return MODULNAMEN[self.modul]

    @property
    def tage_bis_ende(self) -> int | None:
        return (self.ende - date.today()).days if self.ende else None


def _bewerten(abonnement: Abonnement | None, modul: Modul) -> Zugriff:
    if abonnement is None:
        return Zugriff(modul, lesen=False, schreiben=False, status=None, ende=None)
    heute = date.today()
    abgelaufen = abonnement.ende is not None and abonnement.ende < heute
    if abonnement.status is AbonnementStatus.ABGELAUFEN or abgelaufen:
        return Zugriff(modul, lesen=True, schreiben=False, status=AbonnementStatus.ABGELAUFEN, ende=abonnement.ende)
    if abonnement.beginn > heute:
        return Zugriff(modul, lesen=False, schreiben=False, status=abonnement.status, ende=abonnement.ende)
    return Zugriff(modul, lesen=True, schreiben=True, status=abonnement.status, ende=abonnement.ende)


async def zugriff(sitzung: AsyncSession, modul: Modul) -> Zugriff:
    abonnement = (
        await sitzung.execute(select(Abonnement).where(Abonnement.modul == modul))
    ).scalar_one_or_none()
    return _bewerten(abonnement, modul)


async def alle_zugriffe(sitzung: AsyncSession) -> dict[Modul, Zugriff]:
    vorhandene = {
        eintrag.modul: eintrag
        for eintrag in (await sitzung.execute(select(Abonnement))).scalars().all()
    }
    return {modul: _bewerten(vorhandene.get(modul), modul) for modul in Modul}


async def zugriff_pruefen(sitzung: AsyncSession, modul: Modul) -> Zugriff:
    """Wirft, wenn das Modul nicht einmal lesbar ist."""
    ergebnis = await zugriff(sitzung, modul)
    if not ergebnis.lesen:
        raise ModulGesperrt(
            modul,
            f"Das Modul {MODULNAMEN[modul]} ist für Ihr Büro nicht freigeschaltet. "
            "Der Inhaber kann es in den Einstellungen hinzufügen.",
        )
    return ergebnis


async def schreibzugriff_pruefen(sitzung: AsyncSession, modul: Modul) -> Zugriff:
    """Wirft, wenn nur noch gelesen werden darf (Testphase abgelaufen)."""
    ergebnis = await zugriff_pruefen(sitzung, modul)
    if not ergebnis.schreiben:
        raise ModulGesperrt(
            modul,
            f"Die Testphase für {MODULNAMEN[modul]} ist abgelaufen. Ihre bisherigen "
            "Daten bleiben vollständig lesbar und exportierbar; neue Vorgänge legen "
            "Sie nach Abschluss eines Abonnements wieder an.",
        )
    return ergebnis


async def testphase_starten(sitzung: AsyncSession, mandant_id: uuid.UUID) -> list[Abonnement]:
    """30 Tage, alle Module, ohne Zahlungsmittel (Querschnitt 2.3)."""
    heute = date.today()
    ende = heute + timedelta(days=einstellungen().testphase_tage)
    angelegt: list[Abonnement] = []
    # Der mandant_id-Filter ist hier nicht ueberfluessig: Wartungspfade und
    # Tests arbeiten mit der Eigentuemerrolle, fuer die RLS nicht greift.
    vorhanden = {
        eintrag.modul
        for eintrag in (
            await sitzung.execute(select(Abonnement).where(Abonnement.mandant_id == mandant_id))
        )
        .scalars()
        .all()
    }
    for modul in Modul:
        if modul in vorhanden:
            continue
        abonnement = Abonnement(
            mandant_id=mandant_id,
            modul=modul,
            status=AbonnementStatus.TESTPHASE,
            beginn=heute,
            ende=ende,
        )
        sitzung.add(abonnement)
        angelegt.append(abonnement)
    await sitzung.flush()
    return angelegt
