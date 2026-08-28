"""Plattform: Abonnements, Datenhoheit, Wartung, Benutzerverwaltung."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.kern import benutzerverwaltung, datenexport, wartung
from belegwerk.kern.abrechnung import (
    ModulGesperrt,
    alle_zugriffe,
    schreibzugriff_pruefen,
    zugriff_pruefen,
)
# Aliasname: pytest wuerde eine Funktion namens test* sonst einsammeln.
from belegwerk.kern.abrechnung import testphase_starten as _testphase_starten
from belegwerk.kern.mandantentrennung import mandanten_sitzung
from belegwerk.kern.modelle import (
    Abonnement,
    AbonnementStatus,
    Benutzer,
    Mandant,
    Modul,
    Rolle,
)

pytestmark = pytest.mark.anyio

PASSWORT = "Kotfluegel-vorn-links-2026"


async def _buero(sitzung: AsyncSession, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    from belegwerk.kern import passwoerter

    mandant = Mandant(name=name)
    sitzung.add(mandant)
    await sitzung.flush()
    benutzer = Benutzer(
        mandant_id=mandant.id,
        email=f"{uuid.uuid4().hex[:10]}@example.de",
        name=f"{name} Inhaber",
        passwort_hash=passwoerter.hashen(PASSWORT),
        rolle=Rolle.INHABER,
    )
    sitzung.add(benutzer)
    await sitzung.flush()
    await _testphase_starten(sitzung, mandant.id)
    await sitzung.commit()
    return mandant.id, benutzer.id


# --- Abonnements -----------------------------------------------------------


async def test_testphase_gilt_fuer_alle_module(sitzung: AsyncSession) -> None:
    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        zugriffe = await alle_zugriffe(db)
    assert set(zugriffe) == set(Modul)
    for zugriff in zugriffe.values():
        assert zugriff.lesen and zugriff.schreiben
        assert zugriff.status is AbonnementStatus.TESTPHASE


async def test_nach_ablauf_bleibt_lesen_erhalten(sitzung: AsyncSession) -> None:
    """Querschnitt 2.3: nach Ablauf Lesezugriff, kein Neuanlegen, keine Löschung."""
    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        abo = (await db.execute(select(Abonnement).where(Abonnement.modul == Modul.DELTA))).scalar_one()
        abo.ende = date.today() - timedelta(days=1)

    async with mandanten_sitzung(mandant_id) as db:
        zugriff = await zugriff_pruefen(db, Modul.DELTA)
        assert zugriff.lesen is True
        assert zugriff.schreiben is False
        with pytest.raises(ModulGesperrt) as fehler:
            await schreibzugriff_pruefen(db, Modul.DELTA)
    assert "bleiben vollständig lesbar" in str(fehler.value.detail)


async def test_ohne_abonnement_ist_das_modul_gesperrt(sitzung: AsyncSession) -> None:
    mandant = Mandant(name="Büro ohne Abo")
    sitzung.add(mandant)
    await sitzung.commit()
    async with mandanten_sitzung(mandant.id) as db:
        with pytest.raises(ModulGesperrt):
            await zugriff_pruefen(db, Modul.ATLAS)


async def test_wartung_setzt_abgelaufene_abos(sitzung: AsyncSession) -> None:
    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        for abo in (await db.execute(select(Abonnement))).scalars().all():
            abo.ende = date.today() - timedelta(days=2)

    bericht = wartung.Wartungsbericht()
    await wartung.abonnements_pruefen(bericht)
    assert bericht.abos_abgelaufen == 3

    async with mandanten_sitzung(mandant_id) as db:
        for abo in (await db.execute(select(Abonnement))).scalars().all():
            assert abo.status is AbonnementStatus.ABGELAUFEN


# --- Benutzerverwaltung ----------------------------------------------------


async def test_email_gehoert_zu_genau_einem_konto(sitzung: AsyncSession) -> None:
    mandant_id, benutzer_id = await _buero(sitzung, "Büro Nord")
    vorhandene = (
        await sitzung.execute(select(Benutzer).where(Benutzer.id == benutzer_id))
    ).scalar_one()
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(benutzerverwaltung.VerwaltungFehler, match="bereits ein Konto"):
            await benutzerverwaltung.einladen(
                db, mandant_id, benutzer_id, vorhandene.email, Rolle.MITARBEITER
            )


async def test_letzter_inhaber_kann_die_rolle_nicht_abgeben(sitzung: AsyncSession) -> None:
    mandant_id, benutzer_id = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(benutzerverwaltung.VerwaltungFehler, match="nicht selbst"):
            await benutzerverwaltung.rolle_aendern(db, benutzer_id, Rolle.MITARBEITER, benutzer_id)


async def test_niemand_sperrt_sich_selbst(sitzung: AsyncSession) -> None:
    mandant_id, benutzer_id = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(benutzerverwaltung.VerwaltungFehler, match="selbst sperren"):
            await benutzerverwaltung.zugang_sperren(db, benutzer_id, benutzer_id)


async def test_ungueltige_adresse_wird_abgewiesen(sitzung: AsyncSession) -> None:
    mandant_id, benutzer_id = await _buero(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(benutzerverwaltung.VerwaltungFehler, match="gültige E-Mail"):
            await benutzerverwaltung.einladen(db, mandant_id, benutzer_id, "kaputt", Rolle.MITARBEITER)


# --- Datenexport -----------------------------------------------------------


async def test_datenexport_enthaelt_daten_dateien_und_beschreibung(sitzung: AsyncSession) -> None:
    from belegwerk.kern import ablage

    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    ablage.speichern(mandant_id, b"%PDF-1.7\ntest")
    ablage.speichern(mandant_id, b"%PDF-1.7\nanlage", bereich="ausgaben")

    async with mandanten_sitzung(mandant_id) as db:
        archiv = await datenexport.archiv_bauen(db, mandant_id)

    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_datei:
        namen = set(zip_datei.namelist())
        assert "LIESMICH.txt" in namen
        assert "daten/mandant.json" in namen
        assert "daten/abonnement.json" in namen
        assert sum(1 for n in namen if n.startswith("dateien/uploads/")) == 1
        assert sum(1 for n in namen if n.startswith("dateien/ausgaben/")) == 1

        beschreibung = json.loads(zip_datei.read("export.json"))
        assert beschreibung["mandant_id"] == str(mandant_id)
        assert beschreibung["dateien"] == 2
        assert beschreibung["tabellen"]["abonnement"] == 3

        abos = json.loads(zip_datei.read("daten/abonnement.json"))
        assert len(abos) == 3
        # Geldbetraege als Zeichenkette, damit beim Lesen keine Rundung entsteht.
        for abo in abos:
            assert abo["preis_monat"] is None or isinstance(abo["preis_monat"], str)


async def test_datenexport_enthaelt_nur_eigene_daten(sitzung: AsyncSession) -> None:
    nord, _ = await _buero(sitzung, "Büro Nord")
    sued, _ = await _buero(sitzung, "Büro Süd")

    async with mandanten_sitzung(sued) as db:
        archiv = await datenexport.archiv_bauen(db, sued)

    with zipfile.ZipFile(io.BytesIO(archiv)) as zip_datei:
        mandanten = json.loads(zip_datei.read("daten/mandant.json"))
        assert [eintrag["id"] for eintrag in mandanten] == [str(sued)]
        benutzer = json.loads(zip_datei.read("daten/benutzer.json"))
        assert {eintrag["mandant_id"] for eintrag in benutzer} == {str(sued)}
        assert str(nord) not in zip_datei.read("daten/benutzer.json").decode()


# --- Kontolöschung ---------------------------------------------------------


async def test_kontoloeschung_erst_nach_karenz(sitzung: AsyncSession) -> None:
    from belegwerk.kern import ablage
    from belegwerk.konfiguration import einstellungen

    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    ablage.speichern(mandant_id, b"%PDF-1.7\ntest")

    await wartung.loeschung_beantragen(mandant_id)
    bericht = wartung.Wartungsbericht()
    await wartung.kontoloeschungen_vollziehen(bericht)
    assert bericht.mandanten_geloescht == 0
    assert (await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))).scalar_one_or_none()

    # Karenz zurückdatieren.
    from belegwerk.kern.formate import jetzt

    async with sitzung.begin_nested():
        mandant = (
            await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))
        ).scalar_one()
        mandant.loeschung_beantragt_am = jetzt() - timedelta(
            days=einstellungen().konto_karenz_tage + 1
        )
    await sitzung.commit()

    bericht = wartung.Wartungsbericht()
    await wartung.kontoloeschungen_vollziehen(bericht)
    assert bericht.mandanten_geloescht == 1


async def test_nach_der_loeschung_bleibt_keine_zeile_und_keine_datei(
    sitzung: AsyncSession,
) -> None:
    """Querschnitt 7.3: nach Ablauf existiert nichts mehr."""
    from belegwerk.basis import Basis
    from belegwerk.kern import ablage
    from belegwerk.kern.formate import jetzt
    from belegwerk.kern.mandantentrennung import mandantentabellen
    from belegwerk.konfiguration import einstellungen

    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    ablage.speichern(mandant_id, b"%PDF-1.7\ntest")
    ablage.speichern(mandant_id, b"%PDF-1.7\nanlage", bereich="ausgaben")

    mandant = (await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))).scalar_one()
    mandant.loeschung_beantragt_am = jetzt() - timedelta(
        days=einstellungen().konto_karenz_tage + 1
    )
    await sitzung.commit()

    await wartung.kontoloeschungen_vollziehen(wartung.Wartungsbericht())

    for tabelle in [Basis.metadata.tables["mandant"], *mandantentabellen()]:
        spalte = tabelle.c.id if tabelle.name == "mandant" else tabelle.c.mandant_id
        uebrig = (await sitzung.execute(select(spalte).where(spalte == mandant_id))).all()
        assert uebrig == [], f"{tabelle.name} hat noch Zeilen"

    for bereich in ("uploads", "ausgaben"):
        verzeichnis = ablage.mandantenverzeichnis(mandant_id, bereich)
        assert not any(verzeichnis.iterdir())


# --- Aufbewahrung ----------------------------------------------------------


async def test_alte_uploads_werden_geloescht(sitzung: AsyncSession) -> None:
    import os
    import time

    from belegwerk.kern import ablage
    from belegwerk.konfiguration import einstellungen

    mandant_id, _ = await _buero(sitzung, "Büro Nord")
    alt = ablage.speichern(mandant_id, b"%PDF-1.7\nalt")
    neu = ablage.speichern(mandant_id, b"%PDF-1.7\nneu")
    frist = einstellungen().aufbewahrung_uploads_tage
    vergangen = time.time() - (frist + 1) * 86400
    os.utime(alt.pfad, (vergangen, vergangen))

    bericht = wartung.Wartungsbericht()
    await wartung.uploads_aufraeumen(bericht)
    assert bericht.uploads_geloescht >= 1
    assert not alt.pfad.exists()
    assert neu.pfad.exists()


async def test_wartungslauf_faellt_nicht_aus(sitzung: AsyncSession) -> None:
    await _buero(sitzung, "Büro Nord")
    bericht = await wartung.alles_ausfuehren()
    assert bericht.meldungen == []


# --- Oberflaeche -----------------------------------------------------------


def _anmelden(klient: Any, email: str) -> None:
    klient.get("/anmelden")
    klient.post(
        "/anmelden",
        data={
            "email": email,
            "passwort": PASSWORT,
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "weiter": "",
        },
        follow_redirects=False,
    )


def test_einstellungen_und_rueckmeldung(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient, "nord@example.de")

    seite = klient.get("/app/einstellungen")
    assert seite.status_code == 200
    assert "Büro und Briefkopf" in seite.text
    assert "Testphase" in seite.text
    assert "kein Sprachmodell hinterlegt" in seite.text

    gespeichert = klient.post(
        "/app/einstellungen/buero",
        data={
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "name": "Büro Nordwest",
            "briefkopf_zeilen": "Büro Nordwest\nMusterweg 3\n26123 Oldenburg",
            "aktenzeichen_muster": r"\d{4}/\d{4}[A-Z]{2}",
        },
        follow_redirects=True,
    )
    assert "Einstellungen sind gespeichert" in gespeichert.text
    assert "Büro Nordwest" in gespeichert.text

    kaputt = klient.post(
        "/app/einstellungen/buero",
        data={
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "name": "Büro Nordwest",
            "aktenzeichen_muster": "[",
        },
        follow_redirects=True,
    )
    assert "kein gültiger Ausdruck" in kaputt.text

    rueck = klient.post(
        "/app/rueckmeldung",
        data={
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "text": "Die Delta-Tabelle könnte die Klassen farbig gruppieren.",
            "seite": "/app/delta",
        },
        follow_redirects=True,
    )
    assert "Rückmeldung ist angekommen" in rueck.text


def test_datenexport_ueber_die_oberflaeche(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient, "nord@example.de")
    antwort = klient.get("/app/einstellungen/datenexport.zip")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(antwort.content)) as archiv:
        assert "LIESMICH.txt" in archiv.namelist()


def test_mitarbeiter_darf_die_bueroeinstellungen_nicht_aendern(
    klient: Any, migrierte_datenbank: str
) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(
        migrierte_datenbank, "Büro Nord", "mitarbeiter@example.de", PASSWORT, rolle="mitarbeiter"
    )
    _anmelden(klient, "mitarbeiter@example.de")
    seite = klient.get("/app/einstellungen")
    assert "ändert der Inhaber des Büros" in seite.text
    antwort = klient.post(
        "/app/einstellungen/buero",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf"), "name": "Übernommen"},
        follow_redirects=False,
    )
    assert antwort.status_code == 403


def test_kontoloeschung_braucht_die_bestaetigung(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient, "nord@example.de")

    ohne = klient.post(
        "/app/einstellungen/konto-loeschen",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf"), "bestaetigung": "ja"},
        follow_redirects=True,
    )
    assert "das Wort LOESCHEN" in ohne.text

    mit = klient.post(
        "/app/einstellungen/konto-loeschen",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf"), "bestaetigung": "LOESCHEN"},
        follow_redirects=True,
    )
    assert "Löschung ist beantragt" in mit.text
    assert "Löschung widerrufen" in mit.text

    widerrufen = klient.post(
        "/app/einstellungen/loeschung-widerrufen",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf")},
        follow_redirects=True,
    )
    assert "Löschung ist widerrufen" in widerrufen.text


def test_fremde_datei_wird_nicht_ausgeliefert(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    nord, _ = buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    buero_anlegen(migrierte_datenbank, "Büro Süd", "sued@example.de", PASSWORT)

    from belegwerk.kern import ablage

    eintrag = ablage.speichern(uuid.UUID(nord), b"%PDF-1.7\ngeheim")

    _anmelden(klient, "sued@example.de")
    antwort = klient.get(f"/app/datei/{eintrag.kennung}")
    assert antwort.status_code == 404
    assert "gehört nicht zu Ihrem Büro" in antwort.text
