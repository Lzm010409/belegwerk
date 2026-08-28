"""Hintergrundaufträge über eine Tabelle (ADR 0003).

Parsing läuft nicht im Request. Ein Arbeiter im Anwendungsprozess holt Aufträge
mit ``FOR UPDATE SKIP LOCKED`` — damit lassen sich später mehrere Replicas
betreiben, ohne dass zwei denselben Auftrag anfassen. Die Oberfläche fragt den
Fortschritt per HTMX-Polling ab.

Nebenbei entstehen hier die Metriken aus Querschnitt 4.3: Dauer je Auftragsart,
Fehlerquote, Zahl der Versuche.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern.formate import jetzt
from belegwerk.kern.mandantentrennung import mandanten_sitzung
from belegwerk.kern.modelle import Auftrag, AuftragStatus

_log = logging.getLogger(__name__)

MAX_VERSUCHE = 3
ZEITGRENZE = timedelta(minutes=10)
RUHEZEIT_SEKUNDEN = 1.0

FortschrittMelder = Callable[[int, str], Awaitable[None]]
Behandler = Callable[["Auftragskontext"], Awaitable[None]]

_register: dict[str, Behandler] = {}


@dataclass(slots=True)
class Auftragskontext:
    auftrag_id: uuid.UUID
    mandant_id: uuid.UUID
    nutzlast: dict[str, Any]
    sitzung: AsyncSession
    melden: FortschrittMelder


def auftragsart(name: str) -> Callable[[Behandler], Behandler]:
    """Registriert einen Behandler für eine Auftragsart."""

    def eintragen(funktion: Behandler) -> Behandler:
        if name in _register:
            raise RuntimeError(f"Auftragsart {name} ist bereits belegt")
        _register[name] = funktion
        return funktion

    return eintragen


def bekannte_arten() -> tuple[str, ...]:
    return tuple(sorted(_register))


async def anlegen(
    sitzung: AsyncSession, mandant_id: uuid.UUID, art: str, nutzlast: dict[str, Any]
) -> Auftrag:
    if art not in _register:
        raise ValueError(f"unbekannte Auftragsart: {art}")
    auftrag = Auftrag(
        mandant_id=mandant_id,
        art=art,
        status=AuftragStatus.WARTET,
        nutzlast=nutzlast,
        angelegt_am=jetzt(),
    )
    sitzung.add(auftrag)
    await sitzung.flush()
    return auftrag


async def _naechster_auftrag() -> tuple[uuid.UUID, uuid.UUID, str, dict[str, Any]] | None:
    """Holt genau einen wartenden Auftrag und markiert ihn als laufend."""
    async with sitzungsfabrik()() as db:
        zeile = (
            await db.execute(
                text(
                    """
                    SELECT id, mandant_id, art, nutzlast
                    FROM auftrag
                    WHERE status = 'wartet'
                    ORDER BY angelegt_am
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
            )
        ).first()
        if zeile is None:
            await db.rollback()
            return None
        await db.execute(
            update(Auftrag)
            .where(Auftrag.id == zeile.id)
            .values(status=AuftragStatus.LAEUFT, gestartet_am=jetzt(), fortschritt=0)
        )
        await db.commit()
        return zeile.id, zeile.mandant_id, zeile.art, dict(zeile.nutzlast or {})


async def _abschliessen(
    auftrag_id: uuid.UUID, status: AuftragStatus, fehlertext: str | None, dauer_ms: int
) -> int:
    async with sitzungsfabrik()() as db:
        auftrag = (
            await db.execute(select(Auftrag).where(Auftrag.id == auftrag_id))
        ).scalar_one_or_none()
        if auftrag is None:
            return 0
        auftrag.versuche += 1
        auftrag.dauer_ms = dauer_ms
        auftrag.fehlertext = fehlertext
        if status is AuftragStatus.FEHLGESCHLAGEN and auftrag.versuche < MAX_VERSUCHE:
            auftrag.status = AuftragStatus.WARTET
        else:
            auftrag.status = status
            auftrag.beendet_am = jetzt()
            if status is AuftragStatus.FERTIG:
                auftrag.fortschritt = 100
        await db.commit()
        return auftrag.versuche


def _melder(auftrag_id: uuid.UUID) -> FortschrittMelder:
    async def melden(prozent: int, schritt: str) -> None:
        async with sitzungsfabrik()() as db:
            await db.execute(
                update(Auftrag)
                .where(Auftrag.id == auftrag_id)
                .values(fortschritt=max(0, min(100, prozent)), schritt=schritt[:200])
            )
            await db.commit()

    return melden


async def einen_auftrag_abarbeiten() -> bool:
    """Arbeitet höchstens einen Auftrag ab. Gibt zurück, ob einer da war."""
    geholt = await _naechster_auftrag()
    if geholt is None:
        return False
    auftrag_id, mandant_id, art, nutzlast = geholt
    behandler = _register.get(art)
    beginn = jetzt()

    if behandler is None:
        await _abschliessen(
            auftrag_id, AuftragStatus.FEHLGESCHLAGEN, f"unbekannte Auftragsart: {art}", 0
        )
        return True

    fehlertext: str | None = None
    status = AuftragStatus.FERTIG
    try:
        async with asyncio.timeout(ZEITGRENZE.total_seconds()):
            async with mandanten_sitzung(mandant_id) as sitzung:
                await behandler(
                    Auftragskontext(
                        auftrag_id=auftrag_id,
                        mandant_id=mandant_id,
                        nutzlast=nutzlast,
                        sitzung=sitzung,
                        melden=_melder(auftrag_id),
                    )
                )
    except TimeoutError:
        status = AuftragStatus.FEHLGESCHLAGEN
        fehlertext = (
            "Die Verarbeitung hat die Zeitgrenze überschritten. Das Dokument ist "
            "vermutlich ungewöhnlich umfangreich. Bitte melden Sie den Vorgang."
        )
    except Exception as fehler:  # noqa: BLE001 — der Arbeiter darf nicht sterben
        status = AuftragStatus.FEHLGESCHLAGEN
        fehlertext = str(fehler) or type(fehler).__name__
        _log.exception(
            "Auftrag fehlgeschlagen",
            extra={"auftrag_id": str(auftrag_id), "art": art, "mandant_id": str(mandant_id)},
        )

    dauer_ms = int((jetzt() - beginn).total_seconds() * 1000)
    versuche = await _abschliessen(auftrag_id, status, fehlertext, dauer_ms)
    _log.info(
        "Auftrag beendet",
        extra={
            "auftrag_id": str(auftrag_id),
            "art": art,
            "status": status.value,
            "dauer_ms": dauer_ms,
            "versuche": versuche,
        },
    )
    return True


async def arbeiter_schleife(stopp: asyncio.Event) -> None:
    """Läuft als Hintergrundtask der Anwendung."""
    _log.info("Auftragsarbeiter gestartet", extra={"arten": list(bekannte_arten())})
    while not stopp.is_set():
        try:
            hatte_arbeit = await einen_auftrag_abarbeiten()
        except Exception as fehler:  # noqa: BLE001
            _log.error("Arbeiterschleife gestört", extra={"fehlerart": type(fehler).__name__})
            hatte_arbeit = False
        if not hatte_arbeit:
            try:
                await asyncio.wait_for(stopp.wait(), timeout=RUHEZEIT_SEKUNDEN)
            except TimeoutError:
                pass
    _log.info("Auftragsarbeiter beendet")


async def auftrag_lesen(sitzung: AsyncSession, auftrag_id: uuid.UUID) -> Auftrag | None:
    return (await sitzung.execute(select(Auftrag).where(Auftrag.id == auftrag_id))).scalar_one_or_none()
