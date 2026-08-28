"""Fachlicher Ablauf von Check: prüfen, speichern, quittieren.

Der Weg vom Upload zum Protokoll führt durch das Dokumentenpaket (Text), den
Feldkatalog (Werte), die Ableitungen (gerechnete Größen) und die Regelmaschine
(Befunde). Kein Schritt kennt den nächsten.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.check.ableitungen import ableiten
from belegwerk.check.extraktion import Extraktionsergebnis, extrahieren
from belegwerk.check.modelle import (
    Befund,
    CheckFeldmuster,
    CheckRegel,
    Pruefung,
    PruefungStatus,
    Regelherkunft,
)
from belegwerk.check.regelmaschine import (
    Pruefergebnis,
    Regel,
    RegelFehler,
    ausfuehren,
    regel_aus_dict,
    startkatalog,
)
from belegwerk.dokumente.text import text_aus_bytes
from belegwerk.kern import ablage
from belegwerk.kern.dateipruefung import DateiAbgelehnt, pruefen as datei_pruefen, seitenzahl_pruefen
from belegwerk.kern.formate import jetzt

_log = logging.getLogger(__name__)

ERLAUBTE_ARTEN = frozenset({"pdf", "text"})


@dataclass(slots=True)
class Pruefbericht:
    """Was die Oberfläche zeigt — ohne Datenbankbindung."""

    extraktion: Extraktionsergebnis
    ergebnis: Pruefergebnis
    felder: dict[str, Any]
    dokument_hash: str


async def eigene_regeln(sitzung: AsyncSession) -> tuple[tuple[Regel, ...], tuple[str, ...]]:
    """Aktive Regeln des Mandanten: Startkatalog minus Abschaltungen plus eigene."""
    eintraege = (await sitzung.execute(select(CheckRegel))).scalars().all()
    abgeschaltet = {
        e.kennung for e in eintraege if e.herkunft is Regelherkunft.GLOBAL and not e.aktiv
    }
    aktive: list[Regel] = [r for r in startkatalog() if r.id not in abgeschaltet]
    fehlerhafte: list[str] = []
    for eintrag in eintraege:
        if eintrag.herkunft is not Regelherkunft.EIGEN or not eintrag.aktiv or not eintrag.yaml_quelle:
            continue
        try:
            import yaml

            daten = yaml.safe_load(eintrag.yaml_quelle)
            aktive.append(regel_aus_dict(daten, mandant_eigen=True))
        except (RegelFehler, Exception) as fehler:  # noqa: BLE001
            _log.warning(
                "Eigene Regel nicht ladbar",
                extra={"kennung": eintrag.kennung, "fehlerart": type(fehler).__name__},
            )
            fehlerhafte.append(eintrag.kennung)
    return tuple(aktive), tuple(fehlerhafte)


async def mandantenmuster(sitzung: AsyncSession) -> dict[str, list[str]]:
    eintraege = (
        (await sitzung.execute(select(CheckFeldmuster).order_by(CheckFeldmuster.prioritaet)))
        .scalars()
        .all()
    )
    ergebnis: dict[str, list[str]] = {}
    for eintrag in eintraege:
        ergebnis.setdefault(eintrag.feld, []).append(eintrag.muster)
    return ergebnis


def pruefen_ohne_speichern(
    inhalt: bytes,
    *,
    regeln: tuple[Regel, ...] | None = None,
    muster: dict[str, list[str]] | None = None,
    aktenzeichen_muster: str | None = None,
) -> Pruefbericht:
    """Der reine Prüfvorgang. Ohne Datenbank, damit er auch öffentlich läuft."""
    befund = datei_pruefen(inhalt, ERLAUBTE_ARTEN)
    extraktion_text = text_aus_bytes(inhalt, befund.art)
    seitenzahl_pruefen(extraktion_text.seiten)

    extraktion = extrahieren(extraktion_text.text, muster)
    felder = ableiten(extraktion.als_felder(), aktenzeichen_muster=aktenzeichen_muster)
    ergebnis = ausfuehren(extraktion, felder, regeln)
    return Pruefbericht(
        extraktion=extraktion,
        ergebnis=ergebnis,
        felder=felder,
        dokument_hash=hashlib.sha256(inhalt).hexdigest(),
    )


def _extraktion_speicherbar(extraktion: Extraktionsergebnis) -> dict[str, Any]:
    """Feldwerte als JSON — mit Fundort, ohne den Dokumenttext."""
    return {
        name: {
            "wert": None if eintrag.wert is None else str(eintrag.wert),
            "roh": eintrag.roh,
            "seite": eintrag.fundstelle.seite if eintrag.fundstelle else None,
            "ausschnitt": eintrag.fundstelle.ausschnitt if eintrag.fundstelle else None,
        }
        for name, eintrag in extraktion.werte.items()
    }


async def pruefung_anlegen(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    benutzer_id: uuid.UUID | None,
    dateiname: str,
    inhalt: bytes,
    aktenzeichen_muster: str | None = None,
) -> Pruefung:
    """Prüft und speichert. Wirft ``DateiAbgelehnt`` mit Klartext."""
    regeln, _ = await eigene_regeln(sitzung)
    muster = await mandantenmuster(sitzung)
    bericht = pruefen_ohne_speichern(
        inhalt, regeln=regeln, muster=muster, aktenzeichen_muster=aktenzeichen_muster
    )

    eintrag = ablage.speichern(mandant_id, inhalt)
    aktenzeichen = bericht.extraktion.werte.get("aktenzeichen")
    pruefung = Pruefung(
        mandant_id=mandant_id,
        benutzer_id=benutzer_id,
        aktenzeichen=str(aktenzeichen.wert) if aktenzeichen and aktenzeichen.wert else None,
        dateiname=dateiname[:300],
        dokument_hash=bericht.dokument_hash,
        upload_pfad=str(eintrag.pfad),
        seiten=bericht.extraktion.seiten,
        gutachtenart=bericht.extraktion.gutachtenart,
        status=PruefungStatus.FERTIG,
        extraktion=_extraktion_speicherbar(bericht.extraktion),
        konfidenz=bericht.extraktion.konfidenz,
        geprueft_regeln=bericht.ergebnis.geprueft,
        nicht_entscheidbar=list(bericht.ergebnis.nicht_entscheidbar),
        fehlende_pflichtfelder=list(bericht.ergebnis.fehlende_pflichtfelder),
    )
    sitzung.add(pruefung)
    await sitzung.flush()

    for gefunden in bericht.ergebnis.befunde:
        sitzung.add(
            Befund(
                mandant_id=mandant_id,
                pruefung_id=pruefung.id,
                regel_id=gefunden.regel_id,
                nummer=gefunden.nummer,
                schwere=gefunden.schwere,
                titel=gefunden.titel,
                meldung=gefunden.meldung,
                feldwerte=gefunden.feldwerte,
                seite=gefunden.fundstelle.seite if gefunden.fundstelle else None,
                ausschnitt=gefunden.fundstelle.ausschnitt if gefunden.fundstelle else None,
            )
        )
    await sitzung.flush()
    _log.info(
        "Pruefung abgeschlossen",
        extra={
            "mandant_id": str(mandant_id),
            "dokument_hash": bericht.dokument_hash[:16],
            "befunde": len(bericht.ergebnis.befunde),
            "regeln": bericht.ergebnis.geprueft,
        },
    )
    return pruefung


async def quittieren(
    sitzung: AsyncSession, befund_id: uuid.UUID, benutzer_id: uuid.UUID, grund: str
) -> Befund:
    """Ein Befund wird mit Begründung abgehakt — nie ohne."""
    if not grund.strip():
        raise ValueError(
            "Zum Quittieren gehört eine Begründung. Sie ist später der Beleg dafür, "
            "warum der Befund bewusst stehen blieb."
        )
    befund = (await sitzung.execute(select(Befund).where(Befund.id == befund_id))).scalar_one_or_none()
    if befund is None:
        raise LookupError("Dieser Befund gehört nicht zu Ihren Prüfungen.")
    befund.quittiert_von_id = benutzer_id
    befund.quittiert_am = jetzt()
    befund.quittierungsgrund = grund.strip()
    await sitzung.flush()
    return befund


async def pruefung_lesen(sitzung: AsyncSession, pruefung_id: uuid.UUID) -> Pruefung | None:
    return (
        await sitzung.execute(select(Pruefung).where(Pruefung.id == pruefung_id))
    ).scalar_one_or_none()


async def historie(sitzung: AsyncSession, aktenzeichen: str) -> list[Pruefung]:
    """Alle Prüfungen zu einem Aktenzeichen, neueste zuerst (Todo 3.4)."""
    return list(
        (
            await sitzung.execute(
                select(Pruefung)
                .where(Pruefung.aktenzeichen == aktenzeichen)
                .order_by(Pruefung.angelegt_am.desc())
            )
        )
        .scalars()
        .all()
    )


def vergleich(neu: Pruefung, alt: Pruefung) -> dict[str, list[str]]:
    """Was hat sich zwischen zwei Prüfungen desselben Aktenzeichens geändert?"""
    neue = {b.regel_id for b in neu.befunde}
    alte = {b.regel_id for b in alt.befunde}
    return {
        "behoben": sorted(alte - neue),
        "neu": sorted(neue - alte),
        "unveraendert": sorted(neue & alte),
    }


__all__ = [
    "DateiAbgelehnt",
    "Pruefbericht",
    "eigene_regeln",
    "historie",
    "mandantenmuster",
    "pruefen_ohne_speichern",
    "pruefung_anlegen",
    "pruefung_lesen",
    "quittieren",
    "vergleich",
]
