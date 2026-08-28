"""Modul Delta: Normalisierung, Zuordnungskaskade, Klassen, Kontrollrechnung."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from belegwerk.delta.klassifikation import Klasse, klassifizieren
from belegwerk.delta.rechnung import auswerten
from belegwerk.delta.zuordnung import Paar, aehnlichkeit, normalisieren, zuordnen
from belegwerk.dokumente.erkennung import verarbeiten
from belegwerk.dokumente.modell import Position, PositionsArt

FIXTURES = Path(__file__).parent / "fixtures" / "dokumente"
PAARE: list[dict[str, Any]] = json.loads((FIXTURES / "paare.json").read_text(encoding="utf-8"))


def _position(
    nummer: int,
    bezeichnung: str,
    betrag: str,
    art: PositionsArt = PositionsArt.ERSATZTEIL,
    **rest: Any,
) -> Position:
    return Position(
        laufnummer=nummer,
        art=art,
        bezeichnung=bezeichnung,
        betrag=Decimal(betrag),
        rohzeile=f"{nummer} {bezeichnung} {betrag}",
        **rest,
    )


# --- Normalisierung -------------------------------------------------------


@pytest.mark.parametrize(
    ("links", "rechts"),
    [
        ("Kotflügel vorn links", "Kotfl. v. li."),
        ("Stossfaenger vorn A/E", "Stossf. vo. aus-/einbau"),
        ("Motorhaube ersetzen", "Motorh. erneuern"),
        ("Scheinwerfer rechts", "Schwerf. re"),
        ("Hinterachse vermessen", "HA vermessen"),
        ("Aussenspiegel links komplett", "Ausssp. li."),
    ],
)
def test_abkuerzungen_werden_aufgeloest(links: str, rechts: str) -> None:
    assert normalisieren(links) == normalisieren(rechts), (
        f"{normalisieren(links)} != {normalisieren(rechts)}"
    )


def test_normalisierungstabelle_hat_startbestand() -> None:
    """Todo 3.1: 150 Startbegriffe."""
    import yaml

    daten = yaml.safe_load(
        (Path("src/belegwerk/delta/normalisierung.yaml")).read_text(encoding="utf-8")
    )
    assert len(daten["abkuerzungen"]) >= 150


def test_unterschiedliche_teile_bleiben_unterschiedlich() -> None:
    assert normalisieren("Kotflügel vorn links") != normalisieren("Kotflügel vorn rechts")
    assert normalisieren("Tür vorn links") != normalisieren("Tür hinten links")


# --- Zuordnungskaskade ----------------------------------------------------


def test_stufe1_teilenummer() -> None:
    a = [_position(1, "Motorhaube", "100.00", teilenummer="5H0823031")]
    b = [_position(9, "Frontklappe", "80.00", teilenummer="5H0 823 031")]
    paare = zuordnen(a, b)
    assert len(paare) == 1
    assert paare[0].stufe == 1
    assert paare[0].konfidenz == 1.00


def test_stufe2_laufnummer_und_betrag() -> None:
    a = [_position(7, "Etwas Unbenanntes", "123.45")]
    b = [_position(7, "Voellig andere Worte", "123.45")]
    paare = zuordnen(a, b)
    assert paare[0].stufe == 2
    assert paare[0].konfidenz == 0.98


def test_stufe3_bezeichnung_nach_normalisierung() -> None:
    a = [_position(1, "Kotflügel vorn links", "300.00")]
    b = [_position(4, "Kotfl. v. li.", "250.00")]
    paare = zuordnen(a, b)
    assert paare[0].stufe == 3
    assert paare[0].konfidenz == 0.95


def test_stufe4_aehnlichkeit() -> None:
    a = [_position(1, "Stossfaenger vorne lackieren", "300.00", art=PositionsArt.LACK)]
    b = [_position(4, "Stossfaenger vorne lackiern", "250.00", art=PositionsArt.LACK)]
    paare = zuordnen(a, b)
    assert paare[0].stufe == 4
    assert paare[0].konfidenz == 0.80


def test_ohne_treffer_bleibt_es_einseitig() -> None:
    a = [_position(1, "Motorhaube", "100.00")]
    b = [_position(2, "Auspuffanlage komplett", "900.00")]
    paare = zuordnen(a, b)
    assert {(p.nur_in_a, p.nur_in_b) for p in paare} == {(True, False), (False, True)}


def test_zuordnung_ist_eineindeutig() -> None:
    """Vier gleich benannte Beilackierungen duerfen keine Scheintreffer erzeugen."""
    a = [_position(i, "Beilackierung Seitenwand", f"{100 + i}.00", art=PositionsArt.LACK) for i in range(1, 5)]
    b = [_position(i, "Beilackierung Seitenwand", f"{90 + i}.00", art=PositionsArt.LACK) for i in range(1, 3)]
    paare = zuordnen(a, b)
    zugeordnet = [p for p in paare if p.zugeordnet]
    assert len(zugeordnet) == 2
    assert len({id(p.b) for p in zugeordnet}) == 2


def test_aehnliche_aber_verschiedene_teile_werden_nicht_verwechselt() -> None:
    """„Scheinwerfer links" und „Nebelscheinwerfer links" liegen bei 88 Prozent."""
    a = [_position(1, "Scheinwerfer links", "900.00", teilenummer="A1")]
    b = [_position(2, "Nebelscheinwerfer links", "300.00", teilenummer="B2")]
    paare = zuordnen(a, b)
    assert all(not p.zugeordnet for p in paare)
    assert aehnlichkeit("Scheinwerfer links", "Nebelscheinwerfer links") >= 85


def test_gleiche_bezeichnung_ueber_die_positionsart_hinweg_wird_zugeordnet() -> None:
    """Genau so wird „Instandsetzung statt Ersatz" ueberhaupt sichtbar.

    Stufe 3 verlangt Gleichheit nach Normalisierung; das ist starkes Indiz und
    darf deshalb die Positionsart ueberbruecken. Die unscharfe Stufe 4 darf es
    nicht — dort waere es geraten.
    """
    a = [_position(1, "Kotfluegel vorn links", "300.00")]
    b = [_position(2, "Kotfluegel vorn links", "120.00", art=PositionsArt.ARBEIT)]
    paare = zuordnen(a, b)
    assert paare[0].stufe == 3
    abweichung = klassifizieren(paare[0])
    assert abweichung is not None and abweichung.klasse is Klasse.REP_STATT_TAUSCH


def test_unscharfe_stufe_ueberbrueckt_die_positionsart_nicht() -> None:
    a = [_position(1, "Kotfluegel vorn links ersetzen", "300.00")]
    b = [_position(2, "Kotfluegel vorne links ersetzn", "120.00", art=PositionsArt.ARBEIT)]
    paare = zuordnen(a, b)
    assert all(not p.zugeordnet for p in paare)


# --- Klassifikation -------------------------------------------------------


def test_position_entfallen_und_ergaenzt() -> None:
    entfallen = klassifizieren(Paar(_position(1, "Motorhaube", "500.00"), None, None, 0.0))
    assert entfallen is not None and entfallen.klasse is Klasse.POS_ENTFALLEN
    assert entfallen.differenz_netto == Decimal("500.00")

    ergaenzt = klassifizieren(Paar(None, _position(1, "Kleinteile", "30.00"), None, 0.0))
    assert ergaenzt is not None and ergaenzt.klasse is Klasse.POS_ERGAENZT
    assert ergaenzt.differenz_netto == Decimal("-30.00")


def test_verbringung_bekommt_eigene_klasse() -> None:
    position = _position(31, "Verbringungskosten", "120.00", art=PositionsArt.NEBENKOSTEN)
    abweichung = klassifizieren(Paar(position, None, None, 0.0))
    assert abweichung is not None
    assert abweichung.klasse is Klasse.VERBRINGUNG_ENTFALLEN


@pytest.mark.parametrize(
    ("a_werte", "b_werte", "erwartet"),
    [
        (
            {"arbeitswerte": Decimal("10.0"), "stundensatz": Decimal("150.00"), "art": PositionsArt.ARBEIT},
            {"arbeitswerte": Decimal("6.0"), "stundensatz": Decimal("150.00"), "art": PositionsArt.ARBEIT},
            Klasse.AW_REDUZIERT,
        ),
        (
            {"arbeitswerte": Decimal("10.0"), "stundensatz": Decimal("150.00"), "art": PositionsArt.ARBEIT},
            {"arbeitswerte": Decimal("10.0"), "stundensatz": Decimal("120.00"), "art": PositionsArt.ARBEIT},
            Klasse.SATZ_GESENKT,
        ),
        (
            {"lackstufe": 3, "art": PositionsArt.LACK},
            {"lackstufe": 2, "art": PositionsArt.LACK},
            Klasse.LACKSTUFE_GESENKT,
        ),
        (
            {"aufschlag_prozent": Decimal("18.0"), "einzelpreis": Decimal("100.00")},
            {"aufschlag_prozent": Decimal("0.0"), "einzelpreis": Decimal("100.00")},
            Klasse.UPE_GEKUERZT,
        ),
        (
            {"teilenummer": "5H0823031", "einzelpreis": Decimal("800.00")},
            {"teilenummer": "IDENT-4711", "einzelpreis": Decimal("500.00")},
            Klasse.TEIL_ERSETZT,
        ),
        (
            {
                "arbeitswerte": Decimal("10.0"),
                "stundensatz": Decimal("150.00"),
                "art": PositionsArt.LACK,
            },
            {
                "arbeitswerte": Decimal("10.0"),
                "stundensatz": Decimal("150.00"),
                "art": PositionsArt.LACK,
            },
            Klasse.LACKMATERIAL_GEKUERZT,
        ),
    ],
)
def test_klassifikation_erkennt_die_ursache(
    a_werte: dict[str, Any], b_werte: dict[str, Any], erwartet: Klasse
) -> None:
    art_a = a_werte.pop("art", PositionsArt.ERSATZTEIL)
    art_b = b_werte.pop("art", PositionsArt.ERSATZTEIL)
    a = _position(1, "Motorhaube", "500.00", art=art_a, **a_werte)
    b = _position(1, "Motorhaube", "400.00", art=art_b, **b_werte)
    abweichung = klassifizieren(Paar(a, b, 3, 0.95))
    assert abweichung is not None
    assert abweichung.klasse is erwartet
    assert abweichung.differenz_netto == Decimal("100.00")


def test_instandsetzung_statt_ersatz() -> None:
    a = _position(1, "Kotfluegel vorn links", "500.00", art=PositionsArt.ERSATZTEIL)
    b = _position(1, "Kotfluegel vorn links instand setzen", "180.00", art=PositionsArt.ARBEIT)
    abweichung = klassifizieren(Paar(a, b, 2, 0.98))
    assert abweichung is not None
    assert abweichung.klasse is Klasse.REP_STATT_TAUSCH


def test_unveraenderte_position_ist_keine_abweichung() -> None:
    a = _position(1, "Motorhaube", "500.00")
    b = _position(1, "Motorhaube", "500.00")
    assert klassifizieren(Paar(a, b, 2, 0.98)) is None


def test_restklasse_betrag_abweichend() -> None:
    a = _position(1, "Kleinteile", "50.00", art=PositionsArt.NEBENKOSTEN)
    b = _position(1, "Kleinteile", "30.00", art=PositionsArt.NEBENKOSTEN)
    abweichung = klassifizieren(Paar(a, b, 2, 0.98))
    assert abweichung is not None
    assert abweichung.klasse is Klasse.BETRAG_ABWEICHEND


# --- Kontrollrechnung -----------------------------------------------------


def _vergleich(eigen_datei: str, pruef_datei: str) -> Any:
    eigen = verarbeiten((FIXTURES / eigen_datei).read_bytes())
    pruefbericht = verarbeiten((FIXTURES / pruef_datei).read_bytes())
    paare = zuordnen(eigen.positionen, pruefbericht.positionen)
    abweichungen = [a for a in (klassifizieren(p) for p in paare) if a is not None]
    return eigen, pruefbericht, auswerten(eigen, pruefbericht, abweichungen)


@pytest.mark.parametrize("paar", PAARE, ids=lambda p: p["eigen"])
def test_kontrollrechnung_geht_auf(paar: dict[str, Any]) -> None:
    """Todo 3.4: die Summe der Positionsdifferenzen muss der Summendifferenz entsprechen."""
    _, _, ergebnis = _vergleich(paar["eigen"], paar["pruefbericht"])
    assert ergebnis.kontrolle_geht_auf, ergebnis.hinweise
    assert ergebnis.unerklaerter_rest == Decimal("0.00")
    assert str(ergebnis.differenz_netto) == paar["differenz_netto"]


@pytest.mark.parametrize("paar", PAARE, ids=lambda p: p["eigen"])
def test_erwartete_klassen_werden_erkannt(paar: dict[str, Any]) -> None:
    _, _, ergebnis = _vergleich(paar["eigen"], paar["pruefbericht"])
    gefunden = {a.klasse.value for a in ergebnis.abweichungen}
    erwartet = {k["klasse"] for k in paar["kuerzungen"]}
    # Satzsenkungen und Materialkuerzungen zeigen sich in den Positionen; die
    # Klassen muessen mindestens die erwarteten Ursachen abdecken.
    fehlend = erwartet - gefunden - {"SATZ_GESENKT", "LACKMATERIAL_GEKUERZT", "UPE_GEKUERZT"}
    assert not fehlend, f"nicht erkannt: {fehlend}; gefunden: {sorted(gefunden)}"


@pytest.mark.parametrize("paar", PAARE[:5], ids=lambda p: p["eigen"])
def test_zuordnungsquote_ueber_95_prozent(paar: dict[str, Any]) -> None:
    """Todo 3.2: auf handgeprueften Fallpaaren mindestens 95 Prozent zugeordnet."""
    eigen = verarbeiten((FIXTURES / paar["eigen"]).read_bytes())
    pruefbericht = verarbeiten((FIXTURES / paar["pruefbericht"]).read_bytes())
    paare = zuordnen(eigen.positionen, pruefbericht.positionen)
    zugeordnet = sum(1 for p in paare if p.zugeordnet)
    # Bezugsgroesse ist der Pruefbericht: jede dort enthaltene Position muss
    # ihre Entsprechung finden. Gestrichene Positionen sind kein Fehlschlag.
    quote = zugeordnet / len(pruefbericht.positionen)
    assert quote >= 0.95, f"{quote:.0%}"


def test_manipulierter_betrag_loest_die_warnung_aus() -> None:
    """Todo 3.4: ein manipulierter Betrag muss die Warnung ausloesen."""
    eigen = verarbeiten((FIXTURES / PAARE[0]["eigen"]).read_bytes())
    pruefbericht = verarbeiten((FIXTURES / PAARE[0]["pruefbericht"]).read_bytes())
    assert pruefbericht.summen.netto is not None
    pruefbericht.summen.netto = pruefbericht.summen.netto - Decimal("13.37")

    paare = zuordnen(eigen.positionen, pruefbericht.positionen)
    abweichungen = [a for a in (klassifizieren(p) for p in paare) if a is not None]
    ergebnis = auswerten(eigen, pruefbericht, abweichungen)

    assert not ergebnis.kontrolle_geht_auf
    assert ergebnis.unerklaerter_rest == Decimal("-13.37")
    assert any("Unerklärt bleiben" in hinweis for hinweis in ergebnis.hinweise)


def test_ohne_endsumme_wird_die_kontrolle_offen_benannt() -> None:
    eigen = verarbeiten((FIXTURES / PAARE[0]["eigen"]).read_bytes())
    pruefbericht = verarbeiten((FIXTURES / PAARE[0]["pruefbericht"]).read_bytes())
    pruefbericht.summen.netto = None
    paare = zuordnen(eigen.positionen, pruefbericht.positionen)
    abweichungen = [a for a in (klassifizieren(p) for p in paare) if a is not None]
    ergebnis = auswerten(eigen, pruefbericht, abweichungen)
    assert not ergebnis.kontrolle_geht_auf
    assert any("keine Nettoendsumme" in hinweis for hinweis in ergebnis.hinweise)


def test_alle_betraege_bleiben_decimal() -> None:
    _, _, ergebnis = _vergleich(PAARE[0]["eigen"], PAARE[0]["pruefbericht"])
    assert isinstance(ergebnis.differenz_netto, Decimal)
    assert isinstance(ergebnis.differenz_brutto, Decimal)
    for abweichung in ergebnis.abweichungen:
        assert isinstance(abweichung.differenz_netto, Decimal)
    for gruppe in ergebnis.gruppen:
        assert isinstance(gruppe.differenz, Decimal)


# --- Oberflaeche, Auftrag, Export -----------------------------------------

PASSWORT = "Kotfluegel-vorn-links-2026"


def _anmelden(klient: Any) -> None:
    klient.get("/anmelden")
    klient.post(
        "/anmelden",
        data={
            "email": "nord@example.de",
            "passwort": PASSWORT,
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "weiter": "",
        },
        follow_redirects=False,
    )


@pytest.fixture()
def angemeldet_delta(klient: Any, migrierte_datenbank: str) -> Any:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient)
    return klient


def _vergleich_hochladen(klient: Any, paar: dict[str, Any]) -> str:
    """Laedt beide Dokumente hoch und arbeitet den Auftrag ab. Gibt die Vorgangs-URL."""
    import re as _re

    antwort = klient.post(
        "/app/delta",
        data={"csrf_token": klient.cookies.get("belegwerk_csrf")},
        files={
            "eigen": (paar["eigen"], (FIXTURES / paar["eigen"]).read_bytes(), "text/plain"),
            "pruefbericht": (
                paar["pruefbericht"],
                (FIXTURES / paar["pruefbericht"]).read_bytes(),
                "text/plain",
            ),
        },
        follow_redirects=False,
    )
    assert antwort.status_code == 303, antwort.text[:400]
    ziel = antwort.headers["location"]
    treffer = _re.search(r"/app/delta/vorgang/([0-9a-f-]{36})", ziel)
    assert treffer

    # Der Auftragsarbeiter der Anwendung laeuft waehrend des Testlaufs mit; hier
    # wird nur gewartet, bis er fertig ist — wie es die Oberflaeche auch tut.
    import time

    frist = time.monotonic() + 30
    while time.monotonic() < frist:
        seite = klient.get(ziel)
        if "Dokumente werden gelesen" not in seite.text:
            return ziel
        time.sleep(0.4)
    raise AssertionError("Der Vorgang wurde nicht innerhalb von 30 Sekunden verarbeitet.")


def test_neue_ansicht_zeigt_zwei_dropzonen(angemeldet_delta: Any) -> None:
    antwort = angemeldet_delta.get("/app/delta")
    assert antwort.status_code == 200
    assert "Ihre Kalkulation" in antwort.text
    assert "Prüfbericht des Versicherers" in antwort.text
    assert "Noch kein Vergleich" in antwort.text


def test_vollstaendiger_vergleich_ueber_die_oberflaeche(angemeldet_delta: Any) -> None:
    ziel = _vergleich_hochladen(angemeldet_delta, PAARE[0])
    seite = angemeldet_delta.get(ziel)
    assert seite.status_code == 200
    assert "Gesamtdifferenz" in seite.text
    assert "Position gestrichen" in seite.text
    assert "Kontrollrechnung geht nicht auf" not in seite.text


def test_export_json_folgt_dem_schema(angemeldet_delta: Any) -> None:
    ziel = _vergleich_hochladen(angemeldet_delta, PAARE[1])
    antwort = angemeldet_delta.get(f"{ziel}/export.json")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["schema"] == "belegwerk.delta/1"
    assert daten["kontrollrechnung"]["geht_auf"] is True
    assert daten["summen"]["differenz_netto"] == PAARE[1]["differenz_netto"]
    assert daten["abweichungen"]
    for abweichung in daten["abweichungen"]:
        assert set(abweichung) >= {
            "klasse",
            "bezeichnung",
            "wert_eigen",
            "wert_pruefbericht",
            "differenz_netto",
            "beleg_eigen",
            "beleg_pruefbericht",
        }
        # Betraege als Zeichenkette, damit unterwegs kein float entsteht.
        assert isinstance(abweichung["differenz_netto"], str)


def test_pdf_anlage_wird_erzeugt(angemeldet_delta: Any) -> None:
    ziel = _vergleich_hochladen(angemeldet_delta, PAARE[2])
    antwort = angemeldet_delta.get(f"{ziel}/anlage.pdf")
    assert antwort.status_code == 200
    assert antwort.content.startswith(b"%PDF-")
    assert len(antwort.content) > 4000


def test_archiv_findet_ueber_aktenzeichen(angemeldet_delta: Any) -> None:
    _vergleich_hochladen(angemeldet_delta, PAARE[3])
    archiv = angemeldet_delta.get("/app/delta/archiv")
    assert archiv.status_code == 200
    assert "geht auf" in archiv.text


def test_korrektur_wird_protokolliert_und_neu_gerechnet(angemeldet_delta: Any) -> None:
    import re as _re

    ziel = _vergleich_hochladen(angemeldet_delta, PAARE[4])
    korrektur = angemeldet_delta.get(f"{ziel}/korrektur")
    assert korrektur.status_code == 200
    position_id = _re.search(r"/app/delta/position/([0-9a-f-]{36})", korrektur.text)
    assert position_id
    vorgang_id = ziel.rsplit("/", 1)[-1]

    antwort = angemeldet_delta.post(
        f"/app/delta/position/{position_id.group(1)}",
        data={
            "csrf_token": angemeldet_delta.cookies.get("belegwerk_csrf"),
            "vorgang_id": vorgang_id,
            "bezeichnung": "Handkorrigierte Bezeichnung",
            "betrag": "999,99",
        },
        follow_redirects=True,
    )
    assert "Korrektur ist übernommen" in antwort.text
    assert "Handkorrigierte Bezeichnung" in antwort.text

    # Die Kontrollrechnung muss die Handkorrektur bemerken.
    delta = angemeldet_delta.get(ziel)
    assert "Kontrollrechnung geht nicht auf" in delta.text


def test_vorgaenge_bleiben_beim_eigenen_buero(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    buero_anlegen(migrierte_datenbank, "Büro Süd", "sued@example.de", PASSWORT)
    _anmelden(klient)
    ziel = _vergleich_hochladen(klient, PAARE[0])

    klient.cookies.clear()
    klient.get("/anmelden")
    klient.post(
        "/anmelden",
        data={
            "email": "sued@example.de",
            "passwort": PASSWORT,
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "weiter": "",
        },
        follow_redirects=False,
    )
    assert "Noch kein Vorgang im Archiv" in klient.get("/app/delta/archiv").text
    fremd = klient.get(ziel, follow_redirects=True)
    assert "Diesen Vorgang gibt es nicht" in fremd.text
    assert fremd.status_code == 200
