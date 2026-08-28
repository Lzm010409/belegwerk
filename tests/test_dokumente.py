"""Golden-Tests über den gesamten Fixture-Korpus.

Dokument rein, erwartetes Modell als JSON daneben, Vergleich auf Feldebene
(Plattformdatei 4.4). Der Korpus ist synthetisch — siehe den Hinweis in
``tests/fixtures/generator.py``. Er prüft Parserlogik und Rechenwege, nicht die
Robustheit gegen echte Layoutvielfalt.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from belegwerk.dokumente.erkennung import KeinAdapter, braucht_korrektur, erkennen, verarbeiten
from belegwerk.dokumente.konfidenz import SCHWELLE_KORREKTUR
from belegwerk.dokumente.modell import Kalkulation, PositionsArt

FIXTURES = Path(__file__).parent / "fixtures" / "dokumente"
DOKUMENTE = sorted(p for p in FIXTURES.glob("*") if p.suffix in {".txt", ".pdf", ".vxs"})


def _golden(dokument: Path) -> dict[str, object]:
    return json.loads((FIXTURES / f"{dokument.stem}.golden.json").read_text(encoding="utf-8"))


def test_korpus_ist_vollstaendig() -> None:
    """Phase 0 verlangt 30 DAT-Dokumente je Format und 15 Prüfberichte."""
    dat = [p for p in DOKUMENTE if p.name.startswith("dat_")]
    audatex = [p for p in DOKUMENTE if p.name.startswith("audatex_")]
    berichte = [p for p in DOKUMENTE if p.name.endswith("_pruefbericht.txt")]
    assert len(dat) == 30
    assert {p.suffix for p in dat} == {".txt", ".pdf", ".vxs"}
    assert len(audatex) == 10
    assert len(berichte) == 15


@pytest.mark.parametrize("dokument", DOKUMENTE, ids=lambda p: p.name)
def test_erkennung_waehlt_den_erwarteten_adapter(dokument: Path) -> None:
    """Todo 2.2: alle Fixtures werden korrekt zugeordnet."""
    erkennung, _ = erkennen(dokument.read_bytes())
    assert erkennung.adapter == _golden(dokument)["adapter"]


@pytest.mark.parametrize("dokument", DOKUMENTE, ids=lambda p: p.name)
def test_golden_modell_stimmt_feldweise(dokument: Path) -> None:
    erwartet = _golden(dokument)
    kalkulation = verarbeiten(dokument.read_bytes())

    assert kalkulation.quelle.value == erwartet["quelle"]
    assert kalkulation.quellformat == erwartet["quellformat"]
    assert kalkulation.aktenzeichen == erwartet["aktenzeichen"]

    fahrzeug = erwartet["fahrzeug"]
    assert kalkulation.fahrzeug.vin == fahrzeug["vin"]
    assert kalkulation.fahrzeug.kennzeichen == fahrzeug["kennzeichen"]

    saetze = erwartet["saetze"]
    for name, wert in saetze.items():
        gefunden = getattr(kalkulation.saetze, name)
        assert gefunden == Decimal(wert), f"{name}: {gefunden} statt {wert}"

    assert len(kalkulation.positionen) == len(erwartet["positionen"])
    for gefunden, soll in zip(kalkulation.positionen, erwartet["positionen"], strict=True):
        assert gefunden.laufnummer == soll["laufnummer"]
        assert gefunden.art.value == soll["art"]
        assert gefunden.bezeichnung == soll["bezeichnung"]
        assert gefunden.betrag == Decimal(soll["betrag"])
        assert gefunden.teilenummer == soll["teilenummer"]
        for feld in ("arbeitswerte", "stundensatz", "einzelpreis", "aufschlag_prozent"):
            erwarteter = soll[feld]
            assert getattr(gefunden, feld) == (
                Decimal(erwarteter) if erwarteter is not None else None
            ), f"{soll['laufnummer']} {feld}"
        assert gefunden.lackstufe == soll["lackstufe"]

    summen = erwartet["summen"]
    assert kalkulation.summen.netto == Decimal(summen["netto"])
    assert kalkulation.summen.brutto == Decimal(summen["brutto"])
    assert kalkulation.summen.mehrwertsteuer == Decimal(summen["mehrwertsteuer"])


@pytest.mark.parametrize("dokument", DOKUMENTE, ids=lambda p: p.name)
def test_kontrollrechnung_geht_auf(dokument: Path) -> None:
    """Die Summe der Positionen muss der ausgewiesenen Nettosumme entsprechen."""
    kalkulation = verarbeiten(dokument.read_bytes())
    assert kalkulation.summen.netto is not None
    assert kalkulation.summe_der_positionen() == kalkulation.summen.netto


@pytest.mark.parametrize("dokument", DOKUMENTE, ids=lambda p: p.name)
def test_konfidenz_ueber_der_korrekturschwelle(dokument: Path) -> None:
    kalkulation = verarbeiten(dokument.read_bytes())
    assert kalkulation.konfidenz >= SCHWELLE_KORREKTUR, kalkulation.hinweise
    assert not braucht_korrektur(kalkulation)


def test_alle_geldwerte_sind_decimal() -> None:
    """Definition of Done, Punkt 3: keine float in Geldpfaden."""
    kalkulation = verarbeiten((FIXTURES / "dat_00.txt").read_bytes())
    for position in kalkulation.positionen:
        assert isinstance(position.betrag, Decimal)
        for feld in ("arbeitswerte", "stundensatz", "einzelpreis", "aufschlag_prozent"):
            wert = getattr(position, feld)
            assert wert is None or isinstance(wert, Decimal)
    for feld in ("ersatzteile", "arbeit", "lack", "nebenkosten", "netto", "brutto"):
        wert = getattr(kalkulation.summen, feld)
        assert wert is None or isinstance(wert, Decimal)


def test_positionsarten_werden_getrennt() -> None:
    kalkulation = verarbeiten((FIXTURES / "dat_00.txt").read_bytes())
    je_art = kalkulation.summe_je_art()
    assert je_art[PositionsArt.ERSATZTEIL] == kalkulation.summen.ersatzteile
    assert je_art[PositionsArt.ARBEIT] == kalkulation.summen.arbeit
    assert je_art[PositionsArt.LACK] == kalkulation.summen.lack
    assert je_art[PositionsArt.NEBENKOSTEN] == kalkulation.summen.nebenkosten


# ---------------------------------------------------------------------------
# Beschädigte Dokumente: die Konfidenz muss fallen (Todo 2.8)
# ---------------------------------------------------------------------------


def _beschaedigen(text: str, was: str) -> str:
    if was == "position_geloescht":
        zeilen = text.splitlines()
        for nummer, zeile in enumerate(zeilen):
            if zeile.strip().startswith("2 5H"):
                del zeilen[nummer]
                break
        return "\n".join(zeilen)
    if was == "betrag_verfaelscht":
        return text.replace("Summe netto", "Summe netto ").replace(
            "Gesamtbetrag brutto", "Gesamtbetrag brutto"
        )
    raise AssertionError(was)


def test_geloeschte_position_drueckt_die_konfidenz_unter_die_schwelle() -> None:
    text = (FIXTURES / "dat_00.txt").read_text(encoding="utf-8")
    beschaedigt = _beschaedigen(text, "position_geloescht")
    kalkulation = verarbeiten(beschaedigt.encode("utf-8"))
    assert kalkulation.konfidenz < SCHWELLE_KORREKTUR
    assert braucht_korrektur(kalkulation)
    assert any("weicht um" in hinweis for hinweis in kalkulation.hinweise)


def test_fehlender_positionsblock_drueckt_die_konfidenz() -> None:
    text = (FIXTURES / "dat_00.txt").read_text(encoding="utf-8")
    ohne_lack = "\n".join(
        zeile for zeile in text.splitlines() if not zeile.strip().startswith(("21", "22", "23", "24"))
    )
    kalkulation = verarbeiten(ohne_lack.encode("utf-8"))
    assert kalkulation.konfidenz < SCHWELLE_KORREKTUR
    assert any("LACK" in hinweis for hinweis in kalkulation.hinweise)


def test_unbekanntes_layout_nennt_die_geprueften_profile() -> None:
    with pytest.raises(KeinAdapter) as fehler:
        verarbeiten(b"Irgendein Text ohne jede Kalkulationsstruktur.\nNoch eine Zeile.\n")
    text = str(fehler.value)
    assert "Profile" in text and "dat" in text


def test_kaputtes_xml_meldet_klartext() -> None:
    from belegwerk.dokumente.adapter.dat_vxs import VxsFehler, lesen

    with pytest.raises(VxsFehler) as fehler:
        lesen(b"<?xml version='1.0'?><DAT_Kalkulation><unvollstaendig>")
    assert "kein lesbares XML" in str(fehler.value)


def test_modell_serialisiert_ohne_float() -> None:
    kalkulation: Kalkulation = verarbeiten((FIXTURES / "dat_20.vxs").read_bytes())
    daten = kalkulation.als_dict()
    roh = json.dumps(daten)
    assert "rohtext" not in daten
    for position in daten["positionen"]:
        assert isinstance(position["betrag"], str)
    assert json.loads(roh)["summen"]["netto"] == str(kalkulation.summen.netto)
