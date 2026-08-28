"""Anmeldung, Einladung, Passwortrücksetzung, Rate-Limit, CSRF."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import buero_anlegen

PASSWORT = "Kotfluegel-vorn-links-2026"


def _anmelden(klient: TestClient, email: str, passwort: str) -> Any:
    klient.get("/anmelden")  # setzt das CSRF-Cookie
    token = klient.cookies.get("belegwerk_csrf")
    return klient.post(
        "/anmelden",
        data={"email": email, "passwort": passwort, "csrf_token": token, "weiter": ""},
        follow_redirects=False,
    )


def test_anmeldung_und_uebersicht(klient: TestClient, migrierte_datenbank: str) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    antwort = _anmelden(klient, "nord@example.de", PASSWORT)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/app"
    assert klient.cookies.get("belegwerk_sitzung")

    uebersicht = klient.get("/app")
    assert uebersicht.status_code == 200
    assert "Büro Nord" in uebersicht.text
    assert "Delta" in uebersicht.text and "Atlas" in uebersicht.text


def test_falsches_passwort_nennt_keinen_grund(klient: TestClient, migrierte_datenbank: str) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    antwort = _anmelden(klient, "nord@example.de", "falsch-falsch-falsch")
    assert antwort.status_code == 401
    assert "E-Mail-Adresse oder Passwort" in antwort.text


def test_unbekanntes_konto_antwortet_wie_falsches_passwort(klient: TestClient) -> None:
    antwort = _anmelden(klient, "gibtsnicht@example.de", PASSWORT)
    assert antwort.status_code == 401
    assert "E-Mail-Adresse oder Passwort" in antwort.text


def test_geschuetzte_seite_leitet_zur_anmeldung(klient: TestClient) -> None:
    antwort = klient.get("/app", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/anmelden?weiter=/app"


def test_ohne_csrf_token_wird_abgewiesen(klient: TestClient, migrierte_datenbank: str) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    antwort = klient.post(
        "/anmelden",
        data={"email": "nord@example.de", "passwort": PASSWORT, "weiter": ""},
        follow_redirects=False,
    )
    assert antwort.status_code == 400
    assert "Formular" in antwort.text


def test_fremdes_csrf_token_wird_abgewiesen(klient: TestClient, migrierte_datenbank: str) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    klient.get("/anmelden")
    antwort = klient.post(
        "/anmelden",
        data={
            "email": "nord@example.de",
            "passwort": PASSWORT,
            "csrf_token": "ausgedacht",
            "weiter": "",
        },
        follow_redirects=False,
    )
    assert antwort.status_code == 400


def test_rate_limit_greift_nach_acht_fehlversuchen(
    klient: TestClient, migrierte_datenbank: str
) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    for _ in range(8):
        _anmelden(klient, "nord@example.de", "falsch-falsch-falsch")
    gesperrt = _anmelden(klient, "nord@example.de", PASSWORT)
    assert gesperrt.status_code == 429
    assert "Zu viele Versuche" in gesperrt.text


def test_weiterleitung_nur_auf_eigene_pfade(klient: TestClient, migrierte_datenbank: str) -> None:
    """Ein offenes weiter-Feld macht die Anmeldeseite zur Weiterleitung."""
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    klient.get("/anmelden")
    token = klient.cookies.get("belegwerk_csrf")
    antwort = klient.post(
        "/anmelden",
        data={
            "email": "nord@example.de",
            "passwort": PASSWORT,
            "csrf_token": token,
            "weiter": "https://beispiel.invalid/phishing",
        },
        follow_redirects=False,
    )
    assert antwort.headers["location"] == "/app"


def test_abmelden_entwertet_die_sitzung(klient: TestClient, migrierte_datenbank: str) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient, "nord@example.de", PASSWORT)
    token = klient.cookies.get("belegwerk_csrf")
    klient.post("/abmelden", data={"csrf_token": token}, follow_redirects=False)
    assert klient.get("/app", follow_redirects=False).status_code == 303


def test_sitzungscookie_ist_httponly_und_samesite(
    klient: TestClient, migrierte_datenbank: str
) -> None:
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    antwort = _anmelden(klient, "nord@example.de", PASSWORT)
    gesetzt = antwort.headers["set-cookie"]
    assert "HttpOnly" in gesetzt
    assert "SameSite=lax" in gesetzt or "samesite=lax" in gesetzt.lower()


def test_zwei_bueros_sehen_nur_den_eigenen_namen(
    klient: TestClient, migrierte_datenbank: str
) -> None:
    """Mandantentrennung über HTTP, nicht nur über SQL."""
    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    buero_anlegen(migrierte_datenbank, "Büro Süd", "sued@example.de", PASSWORT)

    _anmelden(klient, "nord@example.de", PASSWORT)
    nord = klient.get("/app").text
    assert "Büro Nord" in nord and "Büro Süd" not in nord

    klient.cookies.clear()
    _anmelden(klient, "sued@example.de", PASSWORT)
    sued = klient.get("/app").text
    assert "Büro Süd" in sued and "Büro Nord" not in sued


def test_einladung_und_passwortruecksetzung(klient: TestClient, migrierte_datenbank: str) -> None:
    from belegwerk.kern.anmeldung import einladung_anlegen
    from belegwerk.kern.modelle import Rolle

    mandant_id, benutzer_id = buero_anlegen(
        migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT
    )
    import uuid

    from tests.conftest import _mit_engine

    async def einladen(s: Any) -> str:
        return await einladung_anlegen(
            s, uuid.UUID(mandant_id), "kollege@example.de", Rolle.MITARBEITER, uuid.UUID(benutzer_id)
        )

    code = _mit_engine(migrierte_datenbank, einladen)

    formular = klient.get(f"/einladung/{code}")
    assert formular.status_code == 200
    assert "kollege@example.de" in formular.text

    token = klient.cookies.get("belegwerk_csrf")
    neues = "Verbringungskosten-2026-ok"
    angelegt = klient.post(
        f"/einladung/{code}",
        data={
            "csrf_token": token,
            "name": "Kollege",
            "passwort": neues,
            "passwort_wiederholung": neues,
        },
        follow_redirects=False,
    )
    assert angelegt.status_code == 303

    # Der Code lässt sich kein zweites Mal einlösen.
    erneut = klient.get(f"/einladung/{code}")
    assert erneut.status_code == 410

    klient.cookies.clear()
    assert _anmelden(klient, "kollege@example.de", neues).status_code == 303


def test_passwort_vergessen_verraet_keine_konten(klient: TestClient) -> None:
    klient.get("/passwort-vergessen")
    token = klient.cookies.get("belegwerk_csrf")
    antwort = klient.post(
        "/passwort-vergessen",
        data={"email": "gibtsnicht@example.de", "csrf_token": token},
    )
    assert antwort.status_code == 200
    assert "Besteht zu dieser Adresse ein Konto" in antwort.text


def test_zu_schwaches_passwort_wird_mit_grund_abgelehnt() -> None:
    from belegwerk.kern.passwoerter import PasswortZuSchwach, hashen

    with pytest.raises(PasswortZuSchwach) as fehler:
        hashen("kurz")
    assert "mindestens" in str(fehler.value)
