"""Deutsche Datums- und Zahlformate (Querschnitt 8.6).

Alle Geldbetraege sind ``Decimal``. Ausgabe durchgehend ``1.234,56 EUR`` und
``28.08.2026``, Zeitzone Europe/Berlin.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def jetzt() -> datetime:
    """Aktueller Zeitpunkt in UTC, zeitzonenbehaftet."""
    return datetime.now(tz=timezone.utc)


def nach_berlin(wert: datetime) -> datetime:
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(BERLIN)


def zahl(wert: Decimal | int | float | None, stellen: int = 2) -> str:
    """Formatiert eine Zahl deutsch: 1.234,56."""
    if wert is None:
        return "—"
    if not isinstance(wert, Decimal):
        wert = Decimal(str(wert))
    quantisiert = wert.quantize(Decimal(1).scaleb(-stellen)) if stellen else wert.to_integral_value()
    text = f"{quantisiert:,.{stellen}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def geld(wert: Decimal | None) -> str:
    """Formatiert einen Geldbetrag deutsch mit Waehrungszeichen."""
    if wert is None:
        return "—"
    return f"{zahl(wert)} €"


def prozent(wert: Decimal | None, stellen: int = 1) -> str:
    if wert is None:
        return "—"
    return f"{zahl(wert, stellen)} %"


def datum(wert: date | datetime | None) -> str:
    if wert is None:
        return "—"
    if isinstance(wert, datetime):
        wert = nach_berlin(wert).date()
    return wert.strftime("%d.%m.%Y")


def datum_zeit(wert: datetime | None) -> str:
    if wert is None:
        return "—"
    return nach_berlin(wert).strftime("%d.%m.%Y %H:%M")


def zahl_lesen(text: str | None) -> Decimal | None:
    """Liest eine deutsche Zahl (``1.234,56``) als ``Decimal``.

    Erkennt auch das englische Format, sofern es eindeutig ist. Gibt ``None``
    zurueck, wenn der Text keine Zahl enthaelt — niemals einen geratenen Wert.
    """
    if text is None:
        return None
    roh = text.strip()
    if not roh:
        return None
    negativ = roh.startswith("-") or (roh.startswith("(") and roh.endswith(")"))
    erlaubt = "0123456789.,"
    kern = "".join(z for z in roh if z in erlaubt)
    if not any(z.isdigit() for z in kern):
        return None

    hat_komma = "," in kern
    hat_punkt = "." in kern
    if hat_komma and hat_punkt:
        # Das zuletzt stehende Zeichen ist das Dezimaltrennzeichen.
        if kern.rfind(",") > kern.rfind("."):
            kern = kern.replace(".", "").replace(",", ".")
        else:
            kern = kern.replace(",", "")
    elif hat_komma:
        teile = kern.split(",")
        if len(teile) > 2:
            # 1,234,567 — mehrere Kommata koennen nur Tausendertrenner sein.
            kern = kern.replace(",", "")
        else:
            kern = kern.replace(",", ".")
    elif hat_punkt:
        teile = kern.split(".")
        if len(teile) > 2 or (len(teile) == 2 and len(teile[1]) == 3 and len(teile[0]) <= 3):
            kern = kern.replace(".", "")
    try:
        wert = Decimal(kern)
    except InvalidOperation:
        return None
    return -wert if negativ and wert > 0 else wert
