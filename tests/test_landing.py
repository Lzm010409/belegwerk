"""Öffentliche Seiten: Landingpages, Rechtstexte, Zugangsanfrage, offene Prüfung."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from belegwerk.anwendung import anwendung_erzeugen

OEFFENTLICH = [
    "/",
    "/delta",
    "/atlas",
    "/check",
    "/impressum",
    "/datenschutz",
    "/agb",
    "/auftragsverarbeitung",
    "/tom",
    "/unterauftragsverarbeiter",
]


@pytest.fixture()
def offen(klient: Any) -> Any:
    return klient


@pytest.mark.parametrize("pfad", OEFFENTLICH)
def test_seite_ist_ohne_anmeldung_erreichbar(offen: Any, pfad: str) -> None:
    antwort = offen.get(pfad)
    assert antwort.status_code == 200
    assert "Anmelden" in antwort.text


def test_startseite_nennt_alle_drei_module_mit_preis(offen: Any) -> None:
    text = offen.get("/").text
    for name in ("Delta", "Atlas", "Check"):
        assert name in text
    assert "€ im Monat" in text
    assert "Zahlen kommen nicht aus einem Sprachmodell" in text


def test_delta_hero_zeigt_eine_echte_deltatabelle(offen: Any) -> None:
    text = offen.get("/delta").text
    assert "gestrichen. Hier steht, wo." in text
    assert "Position gestrichen" in text
    assert "Gesamtdifferenz" in text
    # Alle elf Abweichungsklassen als Tabelle, ausgeschrieben.
    from belegwerk.delta.klassifikation import Klasse

    for klasse in Klasse:
        assert klasse.beschriftung in text


def test_atlas_hero_zeigt_livezahlen(offen: Any, migrierte_datenbank: str) -> None:
    """Die Zahlen kommen aus der Datenbank, nicht aus einer Textdatei."""
    antwort = offen.get("/atlas")
    assert "0 erfasste Betriebe" in antwort.text
    assert "Ihr Umkreis fehlt noch" in antwort.text
    assert antwort.headers["cache-control"] == "no-store"


def test_check_hero_prueft_wirklich(offen: Any) -> None:
    from tests.fixtures.gutachten import Gutachten, als_text

    seite = offen.get("/check")
    assert "In fünfzehn Sekunden" in seite.text
    assert "Die Datei wird nicht gespeichert" in seite.text

    from decimal import Decimal

    antwort = offen.post(
        "/check/probe",
        data={"csrf_token": offen.cookies.get("belegwerk_csrf")},
        files={
            "datei": (
                "gutachten.txt",
                als_text(Gutachten(restwert=Decimal("13000.00"))).encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert antwort.status_code == 200
    assert "Prüfprotokoll" in antwort.text
    assert "Restwert liegt auf oder über" in antwort.text


def test_offene_pruefung_speichert_nichts(offen: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import _mit_engine
    from tests.fixtures.gutachten import Gutachten, als_text

    offen.get("/check")
    offen.post(
        "/check/probe",
        data={"csrf_token": offen.cookies.get("belegwerk_csrf")},
        files={"datei": ("g.txt", als_text(Gutachten()).encode("utf-8"), "text/plain")},
    )

    from sqlalchemy import func, select

    from belegwerk.check.modelle import Pruefung

    async def zaehlen(s: Any) -> int:
        return int((await s.execute(select(func.count()).select_from(Pruefung))).scalar_one())

    assert _mit_engine(migrierte_datenbank, zaehlen) == 0


def test_offene_pruefung_ist_mengenmaessig_begrenzt(offen: Any) -> None:
    from tests.fixtures.gutachten import Gutachten, als_text

    inhalt = als_text(Gutachten()).encode("utf-8")
    offen.get("/check")
    for _ in range(5):
        offen.post(
            "/check/probe",
            data={"csrf_token": offen.cookies.get("belegwerk_csrf")},
            files={"datei": ("g.txt", inhalt, "text/plain")},
        )
    gesperrt = offen.post(
        "/check/probe",
        data={"csrf_token": offen.cookies.get("belegwerk_csrf")},
        files={"datei": ("g.txt", inhalt, "text/plain")},
    )
    assert gesperrt.status_code == 400
    assert "Zu viele Versuche" in gesperrt.text


def test_zugangsanfrage_wird_gespeichert(offen: Any, migrierte_datenbank: str) -> None:
    offen.get("/")
    antwort = offen.post(
        "/zugang",
        data={
            "csrf_token": offen.cookies.get("belegwerk_csrf"),
            "name": "Anna Beispiel",
            "buero": "Sachverständigenbüro Beispiel",
            "email": "anna@beispiel.de",
            "plz": "26123",
            "modul": "atlas",
            "webseite": "",
        },
        follow_redirects=True,
    )
    assert "Testzugang angefordert" in antwort.text

    from sqlalchemy import select

    from belegwerk.kern.modelle import Zugangsanfrage
    from tests.conftest import _mit_engine

    async def lesen(s: Any) -> list[str]:
        zeilen = (await s.execute(select(Zugangsanfrage))).scalars().all()
        return [f"{z.email}|{z.plz}|{z.modul}" for z in zeilen]

    assert _mit_engine(migrierte_datenbank, lesen) == ["anna@beispiel.de|26123|atlas"]


def test_honeypot_verwirft_die_anfrage_still(offen: Any, migrierte_datenbank: str) -> None:
    offen.get("/")
    antwort = offen.post(
        "/zugang",
        data={
            "csrf_token": offen.cookies.get("belegwerk_csrf"),
            "name": "Bot",
            "buero": "Bot",
            "email": "bot@example.invalid",
            "webseite": "https://spam.example",
        },
        follow_redirects=True,
    )
    # Für den Absender sieht es aus wie ein Erfolg — sonst lernt der Bot dazu.
    assert antwort.status_code == 200
    assert "Testzugang angefordert" in antwort.text

    from sqlalchemy import func, select

    from belegwerk.kern.modelle import Zugangsanfrage
    from tests.conftest import _mit_engine

    async def zaehlen(s: Any) -> int:
        return int((await s.execute(select(func.count()).select_from(Zugangsanfrage))).scalar_one())

    assert _mit_engine(migrierte_datenbank, zaehlen) == 0


def test_av_vertrag_als_pdf(offen: Any) -> None:
    antwort = offen.get("/auftragsverarbeitung.pdf")
    assert antwort.status_code == 200
    assert antwort.content.startswith(b"%PDF-")
    assert len(antwort.content) > 8000


def test_rechtstexte_nennen_die_pflichtangaben(offen: Any) -> None:
    datenschutz = offen.get("/datenschutz").text
    assert "Auftragsverarbeiter" in datenschutz
    assert "90 Tage" in datenschutz and "14 Tage" in datenschutz
    assert "belegwerk_sitzung" in datenschutz

    agb = offen.get("/agb").text
    assert "fachliche Verantwortung für das Gutachten" in agb
    assert "keine Rechtsdienstleistung" in agb
    assert "jederzeit zum Ende des laufenden Monats kündbar" in agb

    tom = offen.get("/tom").text
    assert "Row-Level-Security" in tom
    assert "Argon2id" in tom

    liste = offen.get("/unterauftragsverarbeiter").text
    assert "Mistral" in liste
    assert "nur bei eingeschaltetem Sprachmodellpfad" in liste


def test_rechtstexte_sind_als_ungeprueft_gekennzeichnet(offen: Any) -> None:
    """Ehrlichkeit vor Fassade: die Texte sind Entwürfe."""
    for pfad in ("/impressum", "/datenschutz", "/agb", "/tom"):
        assert "nicht anwaltlich geprüft" in offen.get(pfad).text


def test_oeffentliche_seiten_setzen_keine_tracker(offen: Any) -> None:
    antwort = offen.get("/")
    assert "google" not in antwort.text.lower()
    assert "analytics" not in antwort.text.lower()
    assert "fonts.gstatic" not in antwort.text
    gesetzt = antwort.headers.get("set-cookie", "")
    assert "belegwerk_csrf" in gesetzt or gesetzt == ""


def test_startseite_wird_zwischengespeichert(offen: Any) -> None:
    assert offen.get("/").headers["cache-control"].startswith("public")


def test_nicht_belegte_wurzelpfade_liefern_404(offen: Any) -> None:
    antwort = offen.get("/gibtesnicht")
    assert antwort.status_code == 404
    assert "Seite nicht gefunden" in antwort.text


def test_anmeldeseite_wird_nicht_von_den_rechtsseiten_verdeckt() -> None:
    """Ein Platzhalterpfad wie /{seite} würde /anmelden einsammeln."""
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/anmelden")
    assert antwort.status_code == 200
    assert "Passwort vergessen" in antwort.text
