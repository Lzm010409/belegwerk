"""Dateiablage und Uploadprüfung (Querschnitt 1.4 und 8.4)."""

from __future__ import annotations

import uuid

import pytest

from belegwerk.kern.ablage import (
    AblageFehler,
    lesen,
    mandant_vollstaendig_loeschen,
    mandantenverzeichnis,
    pfad_pruefen,
    speichern,
)
from belegwerk.kern.dateipruefung import DateiAbgelehnt, art_bestimmen, pruefen

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF"


def test_upload_liegt_unter_der_mandanten_kennung() -> None:
    mandant = uuid.uuid4()
    eintrag = speichern(mandant, PDF)
    assert eintrag.pfad.parent.name == str(mandant)
    assert lesen(mandant, eintrag.pfad) == PDF
    assert eintrag.sha256 == __import__("hashlib").sha256(PDF).hexdigest()


def test_fremder_mandant_kommt_nicht_an_die_datei() -> None:
    eigener, fremder = uuid.uuid4(), uuid.uuid4()
    eintrag = speichern(eigener, PDF)
    with pytest.raises(AblageFehler):
        lesen(fremder, eintrag.pfad)


def test_pfad_ausbruch_wird_abgewiesen() -> None:
    """Ein aus der Datenbank stammender Pfad darf den Bereich nicht verlassen."""
    mandant = uuid.uuid4()
    verzeichnis = mandantenverzeichnis(mandant)
    with pytest.raises(AblageFehler):
        pfad_pruefen(mandant, verzeichnis / ".." / ".." / "etc" / "passwd")


def test_kontoloeschung_entfernt_alle_dateien() -> None:
    mandant = uuid.uuid4()
    speichern(mandant, PDF)
    speichern(mandant, PDF, bereich="ausgaben")
    assert mandant_vollstaendig_loeschen(mandant) == 2
    assert mandant_vollstaendig_loeschen(mandant) == 0


def test_typ_wird_am_inhalt_erkannt_nicht_an_der_endung() -> None:
    assert art_bestimmen(PDF).art == "pdf"
    assert art_bestimmen(b"<?xml version='1.0'?><Kalkulation/>").art == "xml"
    assert art_bestimmen(b"\xff\xd8\xff\xe0JFIF").unterart == "jpeg"
    assert art_bestimmen("Position 1  Kotflügel".encode()).art == "text"


def test_falscher_typ_wird_mit_klartext_abgelehnt() -> None:
    with pytest.raises(DateiAbgelehnt) as fehler:
        pruefen(PDF, frozenset({"bild"}))
    assert "pdf" in str(fehler.value)
    assert "bild" in str(fehler.value)


def test_zu_grosse_datei_nennt_beide_zahlen() -> None:
    with pytest.raises(DateiAbgelehnt) as fehler:
        pruefen(PDF + b"x" * 2000, frozenset({"pdf"}), max_bytes=1000)
    text = str(fehler.value)
    assert "MB" in text and "Zulässig" in text


def test_leere_datei() -> None:
    with pytest.raises(DateiAbgelehnt):
        pruefen(b"", frozenset({"pdf"}))
