"""Modul Check: Extraktion, Ableitungen, Regelmaschine.

Todo 2.3 verlangt je Regel einen positiven und einen negativen Test. Das ist
hier über den Fixture-Bestand automatisiert: fehlt zu einer Regel ein Paar,
schlägt ``test_jede_regel_hat_ein_paar`` fehl.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from belegwerk.check.ableitungen import ableiten
from belegwerk.check.extraktion import extrahieren
from belegwerk.check.regelmaschine import Schwere, ausfuehren, startkatalog
from tests.fixtures.gutachten import Gutachten, als_text, regelfaelle, sollwerte

GUTACHTEN = Path(__file__).parent / "fixtures" / "gutachten"
TXT = sorted(GUTACHTEN.glob("*.txt"))
PDF = sorted(GUTACHTEN.glob("*.pdf"))
HEUTE = date(2026, 8, 28)


def _pruefen(g: Gutachten, aktenzeichen_muster: str | None = None) -> Any:
    extraktion = extrahieren(als_text(g))
    felder = ableiten(
        extraktion.als_felder(), heute=HEUTE, aktenzeichen_muster=aktenzeichen_muster
    )
    return ausfuehren(extraktion, felder)


# --- Bestand --------------------------------------------------------------


def test_gutachtenbestand_ist_vollstaendig() -> None:
    assert len(TXT) == 20
    assert len(PDF) == 20
    assert len(list(GUTACHTEN.glob("*.soll.json"))) == 20


@pytest.mark.parametrize("dokument", TXT, ids=lambda p: p.name)
def test_sollwerte_werden_getroffen(dokument: Path) -> None:
    """Todo 1.3: über alle Fixtures mindestens 90 % der Sollwerte."""
    soll = json.loads((GUTACHTEN / f"{dokument.stem}.soll.json").read_text(encoding="utf-8"))
    extraktion = extrahieren(dokument.read_text(encoding="utf-8"))
    erwartet = {name: wert for name, wert in soll.items() if wert is not None}
    getroffen = sum(
        1
        for name, wert in erwartet.items()
        if extraktion.werte.get(name) is not None
        and str(extraktion.werte[name].wert) == wert
    )
    quote = getroffen / len(erwartet)
    assert quote >= 0.9, f"{quote:.0%} — daneben: " + ", ".join(
        f"{name}={extraktion.werte[name].wert!r} statt {wert!r}"
        for name, wert in erwartet.items()
        if extraktion.werte.get(name) is None or str(extraktion.werte[name].wert) != wert
    )


@pytest.mark.parametrize("dokument", PDF, ids=lambda p: p.name)
def test_extraktion_aus_pdf_trifft_dieselben_werte(dokument: Path) -> None:
    """Der Weg über das PDF muss dasselbe liefern wie der über den Text."""
    from belegwerk.dokumente.text import text_gewinnen

    text = text_gewinnen(dokument.read_bytes()).text
    aus_pdf = extrahieren(text)
    aus_text = extrahieren((GUTACHTEN / f"{dokument.stem}.txt").read_text(encoding="utf-8"))
    for feld in ("aktenzeichen", "vin", "restwert", "wiederbeschaffungswert_brutto", "schadenfall"):
        assert aus_pdf.werte[feld].wert == aus_text.werte[feld].wert, feld


def test_fundstelle_nennt_seite_und_ausschnitt() -> None:
    extraktion = extrahieren(als_text(Gutachten()))
    stelle = extraktion.fundstelle("restwert")
    assert stelle is not None
    assert stelle.seite == 1
    assert "Restwert" in stelle.ausschnitt


def test_nicht_gefundenes_pflichtfeld_ist_selbst_ein_ergebnis() -> None:
    text = als_text(Gutachten()).replace("Restwert", "Rest-Wert")
    extraktion = extrahieren(text)
    assert "restwert" in extraktion.fehlende_pflichtfelder
    assert extraktion.konfidenz < 1.0


def test_mandantenmuster_haben_vorrang() -> None:
    """Todo 1.4: eigene Muster gehen den globalen vor."""
    text = als_text(Gutachten()).replace("Restwert", "Veraeusserungswert")
    ohne = extrahieren(text)
    assert ohne.werte["restwert"].wert is None
    mit = extrahieren(text, {"restwert": [r"Veraeusserungswert"]})
    assert mit.werte["restwert"].wert == Decimal("5200.00")


# --- Regeln ---------------------------------------------------------------


def test_startkatalog_hat_zwanzig_regeln() -> None:
    katalog = startkatalog()
    assert len(katalog) == 20
    assert {r.nummer for r in katalog} == set(range(1, 21))
    for regel in katalog:
        assert regel.meldung
        assert regel.titel


def test_jede_regel_hat_ein_paar() -> None:
    """Wer eine Regel ergänzt, ergänzt auch ihre beiden Fälle."""
    assert {r.id for r in startkatalog()} == set(regelfaelle())


@pytest.mark.parametrize("regel_id", sorted(regelfaelle()))
def test_regel_loest_aus(regel_id: str) -> None:
    positiv, _ = regelfaelle()[regel_id]
    muster = r"\d{4}/\d{4}[A-Z]{2}" if regel_id == "aktenzeichen_format" else None
    ergebnis = _pruefen(positiv, muster)
    assert regel_id in {b.regel_id for b in ergebnis.befunde}, [
        b.regel_id for b in ergebnis.befunde
    ]


@pytest.mark.parametrize("regel_id", sorted(regelfaelle()))
def test_regel_loest_nicht_aus(regel_id: str) -> None:
    _, negativ = regelfaelle()[regel_id]
    muster = r"\d{4}/\d{4}[A-Z]{2}" if regel_id == "aktenzeichen_format" else None
    ergebnis = _pruefen(negativ, muster)
    assert regel_id not in {b.regel_id for b in ergebnis.befunde}


def test_sauberes_gutachten_hat_keine_befunde() -> None:
    ergebnis = _pruefen(Gutachten())
    assert ergebnis.ohne_befund, [b.regel_id for b in ergebnis.befunde]
    assert ergebnis.geprueft == 20


def test_befund_traegt_fundort_und_werte() -> None:
    ergebnis = _pruefen(Gutachten(restwert=Decimal("13000.00")))
    befund = next(b for b in ergebnis.befunde if b.regel_id == "restwert_ueber_wbw")
    assert befund.fundstelle is not None
    assert befund.fundstelle.seite >= 1
    assert befund.feldwerte["restwert"] == "13.000,00 €"
    assert befund.schwere is Schwere.FEHLER


def test_befunde_sind_nach_schwere_sortiert() -> None:
    ergebnis = _pruefen(
        Gutachten(
            restwert=Decimal("13000.00"),
            wertminderung=Decimal("1500.00"),
            erstzulassung=date(2016, 1, 1),
        )
    )
    raenge = [b.schwere.rang for b in ergebnis.befunde]
    assert raenge == sorted(raenge)


def test_regel_meldet_nichts_wenn_ein_wert_fehlt() -> None:
    """Ein nicht auslesbarer Wert darf keinen Befund erzeugen."""
    text = als_text(Gutachten()).replace("Restwert", "Rest-Wert")
    extraktion = extrahieren(text)
    ergebnis = ausfuehren(extraktion, ableiten(extraktion.als_felder(), heute=HEUTE))
    assert "restwert_ueber_wbw" not in {b.regel_id for b in ergebnis.befunde}
    assert "restwert_ueber_wbw" in ergebnis.nicht_entscheidbar


def test_meldungen_sind_rueckfragen_keine_feststellungen() -> None:
    """RDG-Grenze: das Werkzeug fragt, es stellt nicht fest."""
    verboten = ("Sie haben Anspruch", "Sie müssen", "Sie mussen", "ist rechtswidrig")
    for regel in startkatalog():
        for wendung in verboten:
            assert wendung not in regel.meldung, regel.id


# --- Ableitungen ----------------------------------------------------------


def test_ableitungen_rechnen_in_decimal() -> None:
    felder = ableiten(
        {
            "wiederbeschaffungswert_brutto": Decimal("12800.00"),
            "wiederbeschaffungswert_netto": Decimal("10756.30"),
            "reparaturkosten_brutto": Decimal("16000.00"),
            "wertminderung": Decimal("800.00"),
            "erstzulassung": date(2020, 8, 28),
            "schadendatum": date(2026, 3, 1),
            "besichtigungsdatum": date(2026, 3, 15),
            "vin": "WVWZZZAUZMW123456",
        },
        heute=HEUTE,
    )
    assert felder["wbw_aufschlag_prozent"] == Decimal("19.00")
    assert felder["reparaturkosten_anteil_wbw"] == Decimal("125.00")
    assert felder["wertminderung_anteil_wbw"] == Decimal("6.25")
    assert felder["fahrzeugalter_jahre"] == Decimal("6.00")
    assert felder["tage_bis_besichtigung"] == Decimal("14")
    assert felder["vin_unplausibel"] is False
    for wert in felder.values():
        assert not isinstance(wert, float)


def test_vin_mit_verbotenen_zeichen_ist_unplausibel() -> None:
    felder = ableiten({"vin": "WVWZZZAUZMW12345O"}, heute=HEUTE)
    assert felder["vin_unplausibel"] is True


def test_kennzeichenvergleich_ignoriert_schreibweise() -> None:
    felder = ableiten(
        {"kennzeichen": "OL-AB 1234", "kennzeichen_text": "ol-ab1234 wurde besichtigt"},
        heute=HEUTE,
    )
    assert felder["kennzeichen_abweichend"] is False


def test_kaputtes_aktenzeichenmuster_erzeugt_keinen_befund() -> None:
    felder = ableiten({"aktenzeichen": "0326/1147TG"}, heute=HEUTE, aktenzeichen_muster="[")
    assert felder["aktenzeichen_muster_verletzt"] is None


# --- Oberflaeche und Persistenz -------------------------------------------


def _anmelden(klient: Any, email: str, passwort: str) -> None:
    klient.get("/anmelden")
    klient.post(
        "/anmelden",
        data={
            "email": email,
            "passwort": passwort,
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "weiter": "",
        },
        follow_redirects=False,
    )


PASSWORT = "Kotfluegel-vorn-links-2026"


@pytest.fixture()
def angemeldet(klient: Any, migrierte_datenbank: str) -> Any:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient, "nord@example.de", PASSWORT)
    return klient


def test_pruefansicht_nennt_die_zahl_der_regeln(angemeldet: Any) -> None:
    antwort = angemeldet.get("/app/check")
    assert antwort.status_code == 200
    assert "20 Regeln prüfen" in antwort.text
    assert "Noch keine Prüfung" in antwort.text


def test_upload_erzeugt_protokoll_mit_befund(angemeldet: Any) -> None:
    text = als_text(Gutachten(restwert=Decimal("13000.00")))
    antwort = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", text.encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    assert antwort.status_code == 200
    assert "Prüfprotokoll" in antwort.text
    assert "Restwert liegt auf oder über" in antwort.text
    assert "20 Regeln geprüft" in antwort.text


def test_sauberes_gutachten_meldet_zahl_der_regeln(angemeldet: Any) -> None:
    antwort = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", als_text(Gutachten()).encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    assert "20 Regeln geprüft, keine Befunde" in antwort.text
    assert "widerspruchsfrei nach 20 Regeln" in antwort.text


def test_quittierung_braucht_eine_begruendung(angemeldet: Any) -> None:
    text = als_text(Gutachten(restwert=Decimal("13000.00")))
    protokoll = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", text.encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    import re as _re

    befund_id = _re.search(r"/app/check/befund/([0-9a-f-]{36})/quittieren", protokoll.text)
    pruefung_id = _re.search(r"/app/check/pruefung/([0-9a-f-]{36})", protokoll.text)
    assert befund_id and pruefung_id

    ohne = angemeldet.post(
        f"/app/check/befund/{befund_id.group(1)}/quittieren",
        data={
            "csrf_token": angemeldet.cookies.get("belegwerk_csrf"),
            "grund": "   ",
            "pruefung_id": pruefung_id.group(1),
        },
        follow_redirects=True,
    )
    assert "gehört eine Begründung" in ohne.text

    mit = angemeldet.post(
        f"/app/check/befund/{befund_id.group(1)}/quittieren",
        data={
            "csrf_token": angemeldet.cookies.get("belegwerk_csrf"),
            "grund": "Restwertangebot lag über dem WBW, bewusst so ausgewiesen.",
            "pruefung_id": pruefung_id.group(1),
        },
        follow_redirects=True,
    )
    assert "Quittiert am" in mit.text
    assert "bewusst so ausgewiesen" in mit.text


def test_protokoll_als_pdf(angemeldet: Any) -> None:
    import re as _re

    protokoll = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", als_text(Gutachten()).encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    pruefung_id = _re.search(r"/app/check/pruefung/([0-9a-f-]{36})", protokoll.text)
    assert pruefung_id
    antwort = angemeldet.get(f"/app/check/pruefung/{pruefung_id.group(1)}/protokoll.pdf")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/pdf"
    assert antwort.content.startswith(b"%PDF-")
    assert len(antwort.content) > 2000


def test_falscher_dateityp_wird_mit_klartext_abgelehnt(angemeldet: Any) -> None:
    antwort = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("bild.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")},
        follow_redirects=True,
    )
    assert "bild" in antwort.text
    assert "zulässig" in antwort.text


def test_regel_abschalten_wirkt_auf_die_naechste_pruefung(angemeldet: Any) -> None:
    angemeldet.post(
        "/app/check/regeln/restwert_ueber_wbw/schalten",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        follow_redirects=True,
    )
    text = als_text(Gutachten(restwert=Decimal("13000.00")))
    antwort = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", text.encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    assert "19 Regeln geprüft" in antwort.text
    assert "Restwert liegt auf oder über" not in antwort.text


def test_eigene_regel_mit_python_code_wird_abgewiesen(angemeldet: Any) -> None:
    antwort = angemeldet.post(
        "/app/check/regeln/eigene",
        data={
            "csrf_token": angemeldet.cookies.get("belegwerk_csrf"),
            "kennung": "boese_regel",
            "titel": "Boese Regel",
            "schwere": "fehler",
            "wenn": "__import__('os').system('id')",
            "meldung": "Prüfen Sie das.",
        },
        follow_redirects=True,
    )
    assert "angelegt" not in antwort.text
    assert "Unerwartetes Zeichen" in antwort.text or "nicht zulässig" in antwort.text


def test_eigene_regel_wird_mitgeprueft(angemeldet: Any) -> None:
    angemeldet.post(
        "/app/check/regeln/eigene",
        data={
            "csrf_token": angemeldet.cookies.get("belegwerk_csrf"),
            "kennung": "restwert_sehr_hoch",
            "titel": "Restwert über 60 Prozent des WBW",
            "schwere": "warnung",
            "wenn": "restwert > 60 % von wiederbeschaffungswert_brutto",
            "meldung": "Prüfen Sie das Restwertangebot.",
        },
        follow_redirects=True,
    )
    antwort = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={
            "datei": (
                "gutachten.txt",
                als_text(Gutachten(restwert=Decimal("9000.00"))).encode("utf-8"),
                "text/plain",
            )
        },
        follow_redirects=True,
    )
    assert "21 Regeln geprüft" in antwort.text
    assert "Prüfen Sie das Restwertangebot." in antwort.text


def test_historie_vergleicht_mit_der_vorversion(angemeldet: Any) -> None:
    schlecht = als_text(Gutachten(aktenzeichen="0326/1147TG", restwert=Decimal("13000.00")))
    gut = als_text(Gutachten(aktenzeichen="0326/1147TG"))
    for inhalt in (schlecht, gut):
        angemeldet.post(
            "/app/check",
            data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
            files={"datei": ("gutachten.txt", inhalt.encode("utf-8"), "text/plain")},
            follow_redirects=True,
        )
    zweite = angemeldet.post(
        "/app/check",
        data={"csrf_token": angemeldet.cookies.get("belegwerk_csrf")},
        files={"datei": ("gutachten.txt", gut.encode("utf-8"), "text/plain")},
        follow_redirects=True,
    )
    assert "Vergleich zur Prüfung vom" in zweite.text
    assert "behoben" in zweite.text

    historie = angemeldet.get("/app/check/historie?suche=0326")
    assert historie.status_code == 200
    assert "0326/1147TG" in historie.text


def test_pruefungen_bleiben_beim_eigenen_buero(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    buero_anlegen(migrierte_datenbank, "Büro Süd", "sued@example.de", PASSWORT)

    _anmelden(klient, "nord@example.de", PASSWORT)
    klient.post(
        "/app/check",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf")},
        files={
            "datei": (
                "gutachten.txt",
                als_text(Gutachten(aktenzeichen="NORD-1")).encode("utf-8"),
                "text/plain",
            )
        },
        follow_redirects=True,
    )
    nord = klient.get("/app/check/historie").text
    assert "NORD-1" in nord

    klient.cookies.clear()
    _anmelden(klient, "sued@example.de", PASSWORT)
    sued = klient.get("/app/check/historie").text
    assert "NORD-1" not in sued
    assert "Noch keine Prüfung" in sued
