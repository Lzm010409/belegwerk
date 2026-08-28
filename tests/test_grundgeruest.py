"""Grundgeruest: Health, Sicherheits-Kopfzeilen, Fehlerseiten."""

from __future__ import annotations

from fastapi.testclient import TestClient

from belegwerk.anwendung import anwendung_erzeugen


def test_gesundheit_meldet_gestoert_ohne_datenbank() -> None:
    """Der Health-Endpoint prueft die Abhaengigkeiten, nicht nur den Prozess."""
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/gesundheit")
    assert antwort.status_code == 503
    inhalt = antwort.json()
    assert inhalt["status"] == "gestoert"
    assert inhalt["pruefungen"]["datenbank"] is not True


def test_sicherheits_kopfzeilen_auf_jeder_antwort() -> None:
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/static/belegwerk.css")
    assert antwort.status_code == 200
    assert "default-src 'self'" in antwort.headers["content-security-policy"]
    assert antwort.headers["x-frame-options"] == "DENY"
    assert antwort.headers["x-content-type-options"] == "nosniff"


def test_404_liefert_gestaltete_seite_mit_weg_nach_vorn() -> None:
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/gibt-es-nicht")
    assert antwort.status_code == 404
    assert "Seite nicht gefunden" in antwort.text
    assert "Zur Startseite" in antwort.text


def test_404_als_json_fuer_api_pfade() -> None:
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/api/gibt-es-nicht")
    assert antwort.status_code == 404
    assert antwort.json()["fehler"] == "Seite nicht gefunden"


def test_schriften_werden_lokal_ausgeliefert() -> None:
    """DSGVO: keine externen Google-Fonts-Aufrufe."""
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        css = klient.get("/static/schriften.css")
    assert css.status_code == 200
    assert "fonts.gstatic.com" not in css.text
    assert "/static/fonts/" in css.text
