"""Hintergrundaufträge (ADR 0003)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.kern import auftraege
from belegwerk.kern.mandantentrennung import mandanten_sitzung
from belegwerk.kern.modelle import Auftrag, AuftragStatus, Mandant

pytestmark = pytest.mark.anyio

ERGEBNISSE: list[tuple[uuid.UUID, dict[str, Any]]] = []


@auftraege.auftragsart("test.erfolg")
async def _erfolg(kontext: auftraege.Auftragskontext) -> None:
    await kontext.melden(50, "halb")
    ERGEBNISSE.append((kontext.mandant_id, kontext.nutzlast))


@auftraege.auftragsart("test.fehler")
async def _fehler(kontext: auftraege.Auftragskontext) -> None:
    raise ValueError("Das Dokument enthält keine Positionszeilen.")


async def _mandant(sitzung: AsyncSession) -> uuid.UUID:
    mandant = Mandant(name="Büro Auftrag")
    sitzung.add(mandant)
    await sitzung.commit()
    return mandant.id


async def test_auftrag_wird_abgearbeitet_und_meldet_fortschritt(sitzung: AsyncSession) -> None:
    ERGEBNISSE.clear()
    mandant_id = await _mandant(sitzung)
    async with mandanten_sitzung(mandant_id) as db:
        auftrag = await auftraege.anlegen(db, mandant_id, "test.erfolg", {"datei": "a.pdf"})
        auftrag_id = auftrag.id

    assert await auftraege.einen_auftrag_abarbeiten() is True
    assert ERGEBNISSE == [(mandant_id, {"datei": "a.pdf"})]

    frisch = (await sitzung.execute(select(Auftrag).where(Auftrag.id == auftrag_id))).scalar_one()
    await sitzung.refresh(frisch)
    assert frisch.status is AuftragStatus.FERTIG
    assert frisch.fortschritt == 100
    assert frisch.dauer_ms is not None


async def test_leere_warteschlange_meldet_nichts_zu_tun(sitzung: AsyncSession) -> None:
    assert await auftraege.einen_auftrag_abarbeiten() is False


async def test_fehler_wird_wiederholt_und_dann_endgueltig(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung)
    async with mandanten_sitzung(mandant_id) as db:
        auftrag = await auftraege.anlegen(db, mandant_id, "test.fehler", {})
        auftrag_id = auftrag.id

    for _ in range(auftraege.MAX_VERSUCHE):
        assert await auftraege.einen_auftrag_abarbeiten() is True

    frisch = (await sitzung.execute(select(Auftrag).where(Auftrag.id == auftrag_id))).scalar_one()
    await sitzung.refresh(frisch)
    assert frisch.status is AuftragStatus.FEHLGESCHLAGEN
    assert frisch.versuche == auftraege.MAX_VERSUCHE
    assert "Positionszeilen" in (frisch.fehlertext or "")
    assert await auftraege.einen_auftrag_abarbeiten() is False


async def test_unbekannte_art_wird_beim_anlegen_abgewiesen(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung)
    with pytest.raises(ValueError, match="unbekannte Auftragsart"):
        async with mandanten_sitzung(mandant_id) as db:
            await auftraege.anlegen(db, mandant_id, "gibt.es.nicht", {})


async def test_auftrag_bleibt_beim_eigenen_mandanten(sitzung: AsyncSession) -> None:
    eigener = await _mandant(sitzung)
    fremder = Mandant(name="Büro Fremd")
    sitzung.add(fremder)
    await sitzung.commit()

    async with mandanten_sitzung(eigener) as db:
        await auftraege.anlegen(db, eigener, "test.erfolg", {})

    async with mandanten_sitzung(fremder.id) as db:
        sichtbar = (await db.execute(select(Auftrag))).scalars().all()
    assert sichtbar == []


async def test_arbeiter_zieht_sich_bei_stoerungen_zurueck(sitzung: AsyncSession) -> None:
    """Ohne Rückzug schreibt eine kaputte Datenbank jede Sekunde dieselbe Zeile."""
    import asyncio

    pausen: list[float] = []

    async def kaputt() -> bool:
        raise RuntimeError("Datenbank weg")

    async def kurz_warten(warten: Any, timeout: float) -> None:
        # Die uebergebene Coroutine schliessen, sonst warnt asyncio zu Recht.
        warten.close()
        pausen.append(timeout)
        if len(pausen) >= 4:
            stopp.set()
        raise TimeoutError

    stopp = asyncio.Event()
    original_abarbeiten = auftraege.einen_auftrag_abarbeiten
    original_warten = asyncio.wait_for
    auftraege.einen_auftrag_abarbeiten = kaputt  # type: ignore[assignment]
    asyncio.wait_for = kurz_warten  # type: ignore[assignment]
    try:
        await auftraege.arbeiter_schleife(stopp)
    finally:
        auftraege.einen_auftrag_abarbeiten = original_abarbeiten  # type: ignore[assignment]
        asyncio.wait_for = original_warten  # type: ignore[assignment]

    assert pausen == [2.0, 4.0, 8.0, 16.0]
    assert max(pausen) <= auftraege.RUECKZUG_MAX_SEKUNDEN
