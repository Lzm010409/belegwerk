"""Deutsche Zahl- und Datumsformate (Querschnitt 8.6)."""

from __future__ import annotations

import random
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from belegwerk.kern.formate import datum, datum_zeit, geld, prozent, zahl, zahl_lesen


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        (Decimal("1234.56"), "1.234,56 €"),
        (Decimal("0"), "0,00 €"),
        (Decimal("-89.9"), "-89,90 €"),
        (Decimal("1234567.891"), "1.234.567,89 €"),
        (None, "—"),
    ],
)
def test_geld_deutsch(eingabe: Decimal | None, erwartet: str) -> None:
    assert geld(eingabe) == erwartet


def test_prozent_und_zahl() -> None:
    assert prozent(Decimal("17.5")) == "17,5 %"
    assert zahl(Decimal("10"), 0) == "10"


def test_datum_deutsch() -> None:
    assert datum(date(2026, 8, 28)) == "28.08.2026"
    assert datum(None) == "—"
    assert datum_zeit(datetime(2026, 1, 5, 12, 30, tzinfo=timezone.utc)) == "05.01.2026 13:30"


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("0,00", Decimal("0")),
        ("12.345", Decimal("12345")),
        ("12.34", Decimal("12.34")),
        ("1234.56", Decimal("1234.56")),
        ("-89,90", Decimal("-89.90")),
        ("1.234,56 €", Decimal("1234.56")),
        ("EUR 1.234,56", Decimal("1234.56")),
        ("", None),
        ("keine Zahl", None),
        (None, None),
    ],
)
def test_zahl_lesen(text: str | None, erwartet: Decimal | None) -> None:
    assert zahl_lesen(text) == erwartet


def test_zahl_lesen_ist_umkehrbar_ueber_1000_zufallsbetraege() -> None:
    """Todo 2.1: Property-Test ueber 1.000 zufaellige Betraege."""
    zufall = random.Random(20260828)
    for _ in range(1000):
        betrag = Decimal(zufall.randrange(-99_999_999, 99_999_999)) / Decimal(100)
        formatiert = geld(betrag)
        assert zahl_lesen(formatiert) == betrag, formatiert
