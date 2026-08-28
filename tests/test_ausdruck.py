"""Der Ausdrucksauswerter — Check-Todo 2.1.

Das Sicherheitsversprechen: eine Regel kann keinen Python-Code ausführen.
Dieser Test ist der Nachweis dafür, nicht eine Behauptung im Kommentar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from belegwerk.check.ausdruck import (
    AusdruckFehler,
    felder_im_ausdruck,
    pruefen,
    uebersetzen,
)

FELDER: dict[str, object] = {
    "restwert": Decimal("5200.00"),
    "wiederbeschaffungswert_brutto": Decimal("12800.00"),
    "wiederbeschaffungswert_netto": Decimal("10756.30"),
    "reparaturkosten_netto": Decimal("9400.00"),
    "wertminderung": Decimal("800.00"),
    "umsatzsteuer_regime": "differenzbesteuert",
    "schadendatum": date(2026, 3, 1),
    "besichtigungsdatum": date(2026, 3, 4),
    "vorschaden": True,
    "reparaturdauer": None,
}


# --- Sicherheit -----------------------------------------------------------


@pytest.mark.parametrize(
    "angriff",
    [
        "__import__('os').system('id')",
        "().__class__.__bases__[0]",
        "open('/etc/passwd').read()",
        "restwert.__class__",
        "exec('x=1')",
        "lambda: 1",
        "[x for x in range(10)]",
        "{'a': 1}",
        "restwert if True else 0",
        "globals()",
    ],
)
def test_regel_kann_keinen_python_code_ausfuehren(angriff: str) -> None:
    with pytest.raises(AusdruckFehler):
        pruefen(angriff, dict(FELDER))  # type: ignore[arg-type]


def test_unbekannter_name_ist_nur_ein_unbekanntes_feld() -> None:
    """Ein Tippfehler darf keinen Zugriff auf irgendetwas eröffnen."""
    assert pruefen("os > 1", dict(FELDER)) is None  # type: ignore[arg-type]


def test_punkt_zugriff_ist_syntaxfehler() -> None:
    with pytest.raises(AusdruckFehler) as fehler:
        uebersetzen("restwert.real > 1")
    assert "Unerwartetes Zeichen" in str(fehler.value)


# --- Fachliche Auswertung -------------------------------------------------


@pytest.mark.parametrize(
    ("ausdruck", "erwartet"),
    [
        ("restwert >= wiederbeschaffungswert_brutto", False),
        ("restwert < wiederbeschaffungswert_brutto", True),
        ("reparaturkosten_netto > 130 % von wiederbeschaffungswert_brutto", False),
        ("reparaturkosten_netto > 70 % von wiederbeschaffungswert_brutto", True),
        ("wertminderung > 10 % von wiederbeschaffungswert_brutto", False),
        ("umsatzsteuer_regime == 'differenzbesteuert'", True),
        ("umsatzsteuer_regime == 'regelbesteuert'", False),
        ("umsatzsteuer_regime != 'regelbesteuert'", True),
        ("besichtigungsdatum < schadendatum", False),
        ("besichtigungsdatum >= schadendatum", True),
        ("vorhanden(restwert)", True),
        ("fehlt(reparaturdauer)", True),
        ("vorhanden(reparaturdauer)", False),
        ("fehlt(gibtesnicht)", True),
        ("restwert > 1000 und wertminderung > 500", True),
        ("restwert > 99999 oder wertminderung > 500", True),
        ("nicht (restwert > 99999)", True),
        ("(restwert + wertminderung) >= 6000", True),
        ("(restwert + wertminderung) > 6000", False),
        ("wiederbeschaffungswert_brutto - wiederbeschaffungswert_netto > 2000", True),
        ("vorschaden", True),
    ],
)
def test_auswertung(ausdruck: str, erwartet: bool) -> None:
    assert pruefen(ausdruck, dict(FELDER)) is erwartet  # type: ignore[arg-type]


def test_fehlender_wert_ergibt_unbekannt_und_meldet_nichts() -> None:
    """Ein nicht gefundenes Feld darf keinen Befund auslösen."""
    assert pruefen("reparaturdauer < 5", dict(FELDER)) is None  # type: ignore[arg-type]
    assert pruefen("reparaturdauer < 5 und restwert > 0", dict(FELDER)) is None  # type: ignore[arg-type]
    # Eine Verknüpfung, deren Ergebnis feststeht, bleibt entscheidbar:
    assert pruefen("reparaturdauer < 5 und restwert > 99999", dict(FELDER)) is False  # type: ignore[arg-type]
    assert pruefen("reparaturdauer < 5 oder restwert > 0", dict(FELDER)) is True  # type: ignore[arg-type]


def test_division_durch_null_ergibt_unbekannt_statt_absturz() -> None:
    felder: dict[str, object] = {"a": Decimal("5"), "b": Decimal("0")}
    assert pruefen("a / b > 1", felder) is None  # type: ignore[arg-type]


def test_deutsche_zahlen_im_ausdruck() -> None:
    felder: dict[str, object] = {"betrag": Decimal("1234.56")}
    assert pruefen("betrag == 1.234,56", felder) is True  # type: ignore[arg-type]
    assert pruefen("betrag > 1.000,00", felder) is True  # type: ignore[arg-type]


def test_rechnet_in_decimal_nicht_in_float() -> None:
    """0,1 + 0,2 muss exakt 0,3 sein — sonst wandern Cent."""
    felder: dict[str, object] = {"a": Decimal("0.1"), "b": Decimal("0.2")}
    assert pruefen("a + b == 0,3", felder) is True  # type: ignore[arg-type]


def test_leerer_ausdruck_wird_abgewiesen() -> None:
    with pytest.raises(AusdruckFehler, match="leer"):
        uebersetzen("   ")


def test_unvollstaendiger_ausdruck_nennt_die_stelle() -> None:
    with pytest.raises(AusdruckFehler) as fehler:
        uebersetzen("restwert >")
    assert "endet unerwartet" in str(fehler.value)


def test_felder_im_ausdruck_fuer_die_vorschau() -> None:
    gefunden = felder_im_ausdruck(
        "reparaturkosten_netto > 130 % von wiederbeschaffungswert_brutto und fehlt(reparaturdauer)"
    )
    assert gefunden == {
        "reparaturkosten_netto",
        "wiederbeschaffungswert_brutto",
        "reparaturdauer",
    }
