"""Mandantentrennung als geprüfte Eigenschaft (Querschnitt 1).

Der Test findet die zu prüfenden Tabellen über Introspektion des
Modellregisters — nicht über eine Liste, die beim nächsten neuen Modell
vergessen wird.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Column, Table, insert, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk import modellregister  # noqa: F401  — fuellt das Register
from belegwerk.basis import Basis
from belegwerk.kern.mandantentrennung import (
    APP_ROLLE,
    kontext_setzen,
    mandanten_sitzung,
    mandantentabellen,
)

pytestmark = pytest.mark.anyio


def _beispielwert(spalte: Column[Any], zaehler: int) -> Any:
    """Ein zulässiger Wert für eine Spalte, allein aus ihrem Typ abgeleitet."""
    typ = spalte.type
    name = type(typ).__name__.lower()
    if "uuid" in name:
        return uuid.uuid4()
    if "enum" in name:
        return sorted(typ.enums)[0]  # type: ignore[attr-defined]
    if "boolean" in name:
        return False
    if "numeric" in name:
        return Decimal("1.00")
    if "integer" in name or "biginteger" in name or "smallinteger" in name:
        return zaehler
    if "datetime" in name:
        return dt.datetime.now(tz=dt.timezone.utc)
    if "date" in name:
        return dt.date(2026, 1, 1)
    if "jsonb" in name or "json" in name:
        return {}
    if "array" in name:
        return []
    laenge = getattr(typ, "length", None) or 40
    # Kurze Spalten (etwa PLZ mit fuenf Zeichen) muessen exakt eingehalten werden.
    return f"{zaehler}{uuid.uuid4().hex}"[: min(laenge, 60)]


async def _zeile_anlegen(
    sitzung: AsyncSession, tabelle: Table, mandant_id: uuid.UUID, bekannt: dict[str, uuid.UUID]
) -> uuid.UUID:
    """Legt eine Zeile in ``tabelle`` für ``mandant_id`` an — generisch."""
    werte: dict[str, Any] = {}
    zeile_id = uuid.uuid4()
    for nummer, spalte in enumerate(tabelle.columns, start=1):
        if spalte.name == "id":
            werte["id"] = zeile_id
            continue
        if spalte.name == "mandant_id":
            werte["mandant_id"] = mandant_id
            continue
        if spalte.foreign_keys:
            ziel = next(iter(spalte.foreign_keys)).column.table.name
            verweis = bekannt.get(f"{ziel}:{mandant_id}")
            if verweis is None:
                if spalte.nullable:
                    continue
                raise AssertionError(f"kein Verweis fuer {tabelle.name}.{spalte.name} -> {ziel}")
            werte[spalte.name] = verweis
            continue
        if spalte.nullable or spalte.server_default is not None or spalte.default is not None:
            continue
        werte[spalte.name] = _beispielwert(spalte, nummer)
    await sitzung.execute(insert(tabelle).values(**werte))
    bekannt[f"{tabelle.name}:{mandant_id}"] = zeile_id
    return zeile_id


async def _testdaten(sitzung: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> dict[str, uuid.UUID]:
    """Je eine Zeile in jeder Mandantentabelle für zwei verschiedene Mandanten."""
    mandant = Basis.metadata.tables["mandant"]
    bekannt: dict[str, uuid.UUID] = {}
    for mandant_id in (a, b):
        await sitzung.execute(insert(mandant).values(id=mandant_id, name=f"Buero {mandant_id.hex[:6]}"))
        bekannt[f"mandant:{mandant_id}"] = mandant_id
    namen = {t.name for t in mandantentabellen()}
    for tabelle in Basis.metadata.sorted_tables:
        if tabelle.name not in namen:
            continue
        for mandant_id in (a, b):
            await _zeile_anlegen(sitzung, tabelle, mandant_id, bekannt)
    await sitzung.commit()
    return bekannt


async def test_introspektion_findet_alle_mandantentabellen() -> None:
    namen = {t.name for t in mandantentabellen()}
    # Kernbestand — waechst mit jedem Modul.
    assert {"benutzer", "sitzung", "auftrag", "abonnement"} <= namen
    for tabelle in mandantentabellen():
        assert not tabelle.columns["mandant_id"].nullable, tabelle.name


async def test_kein_mandant_sieht_zeilen_eines_anderen(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Der Kerntest: für JEDE mandantenbezogene Tabelle Zugriff über Kreuz."""
    a, b = mandant_ids
    await _testdaten(sitzung, a, b)

    geprueft = 0
    async with mandanten_sitzung(b) as sitzung_b:
        for tabelle in mandantentabellen():
            zeilen = (await sitzung_b.execute(select(tabelle.c.mandant_id))).scalars().all()
            assert zeilen, f"{tabelle.name}: eigene Zeile muss sichtbar sein"
            assert set(zeilen) == {b}, f"{tabelle.name}: fremde Zeile sichtbar"
            geprueft += 1
    assert geprueft == len(mandantentabellen()) >= 4


async def test_mandant_tabelle_zeigt_nur_den_eigenen_datensatz(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = mandant_ids
    await _testdaten(sitzung, a, b)
    mandant = Basis.metadata.tables["mandant"]
    async with mandanten_sitzung(a) as sitzung_a:
        ids = (await sitzung_a.execute(select(mandant.c.id))).scalars().all()
    assert ids == [a]


async def test_ohne_gesetzte_variable_null_zeilen(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Querschnitt 1.2: eine Abfrage ohne gesetzte Variable liefert null Zeilen."""
    a, b = mandant_ids
    await _testdaten(sitzung, a, b)
    from belegwerk.datenbank import sitzungsfabrik

    async with sitzungsfabrik()() as blanke:
        await blanke.execute(text(f"SET LOCAL ROLE {APP_ROLLE}"))
        for tabelle in mandantentabellen():
            zeilen = (await blanke.execute(select(tabelle.c.mandant_id))).scalars().all()
            assert zeilen == [], f"{tabelle.name} liefert ohne Mandantenkontext Zeilen"


async def test_app_rolle_ist_kein_superuser(sitzung: AsyncSession) -> None:
    """Superuser umgehen RLS vollständig — die App-Rolle darf keiner sein."""
    zeile = (
        await sitzung.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :name"),
            {"name": APP_ROLLE},
        )
    ).one()
    assert zeile == (False, False)


async def test_schreiben_auf_fremden_mandanten_wird_abgewiesen(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """WITH CHECK: auch das Anlegen unter fremder mandant_id muss scheitern."""
    a, b = mandant_ids
    await _testdaten(sitzung, a, b)
    auftrag = Basis.metadata.tables["auftrag"]
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with mandanten_sitzung(b) as sitzung_b:
            await sitzung_b.execute(
                insert(auftrag).values(
                    id=uuid.uuid4(),
                    mandant_id=a,
                    art="test",
                    status="wartet",
                    nutzlast={},
                    fortschritt=0,
                    versuche=0,
                    angelegt_am=dt.datetime.now(tz=dt.timezone.utc),
                )
            )


async def test_loeschen_fremder_zeilen_bleibt_wirkungslos(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = mandant_ids
    await _testdaten(sitzung, a, b)
    auftrag = Basis.metadata.tables["auftrag"]
    async with mandanten_sitzung(b) as sitzung_b:
        await sitzung_b.execute(auftrag.delete())
    uebrig = (await sitzung.execute(select(auftrag.c.mandant_id))).scalars().all()
    assert uebrig == [a]


async def test_kontext_gilt_nur_fuer_die_transaktion(
    sitzung: AsyncSession, mandant_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SET LOCAL: nach dem Commit darf kein Mandantenkontext hängenbleiben."""
    a, _ = mandant_ids
    from belegwerk.datenbank import sitzungsfabrik

    async with sitzungsfabrik()() as s:
        await kontext_setzen(s, a)
        assert (await s.execute(text("SELECT current_user"))).scalar_one() == APP_ROLLE
        await s.commit()
        assert (await s.execute(text("SELECT current_user"))).scalar_one() != APP_ROLLE
        assert (
            await s.execute(text("SELECT current_setting('app.mandant_id', true)"))
        ).scalar_one() in (None, "")


async def test_gesundheit_ist_gruen_mit_erreichbarer_datenbank(sitzung: AsyncSession) -> None:
    from belegwerk.web.gesundheit import gesundheit

    antwort = await gesundheit()
    assert antwort.status_code == 200
    import json

    assert json.loads(bytes(antwort.body))["pruefungen"]["datenbank"] is True
