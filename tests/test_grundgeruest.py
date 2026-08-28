"""Grundgeruest: Health, Sicherheits-Kopfzeilen, Fehlerseiten."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from belegwerk.anwendung import anwendung_erzeugen


def test_gesundheit_meldet_gestoert_ohne_datenbank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Health-Endpoint prueft die Abhaengigkeiten, nicht nur den Prozess."""
    import belegwerk.datenbank as db
    from belegwerk.konfiguration import einstellungen

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://niemand@127.0.0.1:1/gibtesnicht"
    )
    einstellungen.cache_clear()
    db._engine = None
    db._sitzungsfabrik = None
    with TestClient(anwendung_erzeugen(), raise_server_exceptions=False) as klient:
        antwort = klient.get("/gesundheit")
    assert antwort.status_code == 503
    inhalt = antwort.json()
    assert inhalt["status"] == "gestoert"
    assert inhalt["pruefungen"]["datenbank"] is not True
    einstellungen.cache_clear()
    db._engine = None
    db._sitzungsfabrik = None


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


def test_gesundheit_meldet_fehlendes_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eine erreichbare Datenbank ohne Migrationen ist kein gesunder Zustand."""
    import asyncio

    import belegwerk.datenbank as db

    class LeereVerbindung:
        async def __aenter__(self) -> "LeereVerbindung":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def execute(self, anweisung: object, *rest: object) -> object:
            text = str(anweisung)

            class Ergebnis:
                @staticmethod
                def scalar_one() -> object:
                    return False if "alembic_version" in text else 1

            return Ergebnis()

    class Engine:
        @staticmethod
        def connect() -> LeereVerbindung:
            return LeereVerbindung()

    monkeypatch.setattr(db, "engine", lambda: Engine())
    ergebnis = asyncio.run(db.datenbank_erreichbar())
    assert ergebnis != True  # noqa: E712 — hier ist die Identität gemeint
    assert "Migrationen" in str(ergebnis)
