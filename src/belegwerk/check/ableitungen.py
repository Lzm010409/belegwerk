"""Abgeleitete Größen für den Regelkatalog.

Diese Werte werden **gerechnet**, nicht extrahiert — in ``Decimal``, mit
sichtbarem Rechenweg. Sie in den Regelausdruck zu schreiben wäre möglich
gewesen; hier stehen sie, weil eine Regel lesbar bleiben soll und weil die
Rechnung genau einmal existieren muss.

Die Leitplanke aus Plattformdatei Abschnitt 8 gilt: kein Sprachmodell erzeugt,
schätzt oder korrigiert eine dieser Zahlen.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

# Fahrgestellnummern verwenden I, O und Q nicht, um Verwechslungen mit 1 und 0
# auszuschließen (ISO 3779).
VIN_ZEICHEN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
VIN_UNGUELTIG = re.compile(r"[IOQ]")


def _zahl(wert: Any) -> Decimal | None:
    return wert if isinstance(wert, Decimal) else None


def _anteil(teil: Decimal | None, ganzes: Decimal | None) -> Decimal | None:
    if teil is None or ganzes is None or ganzes == 0:
        return None
    return (teil / ganzes * Decimal(100)).quantize(Decimal("0.01"))


def ableiten(
    felder: dict[str, Any], *, heute: date | None = None, aktenzeichen_muster: str | None = None
) -> dict[str, Any]:
    """Ergänzt die extrahierten Felder um die gerechneten Größen."""
    heute = heute or date.today()
    abgeleitet: dict[str, Any] = dict(felder)

    erstzulassung = felder.get("erstzulassung")
    if isinstance(erstzulassung, date):
        tage = (heute - erstzulassung).days
        abgeleitet["fahrzeugalter_jahre"] = (
            Decimal(tage) / Decimal("365.25")
        ).quantize(Decimal("0.01"))

    wbw_brutto = _zahl(felder.get("wiederbeschaffungswert_brutto"))
    wbw_netto = _zahl(felder.get("wiederbeschaffungswert_netto"))

    # Für den Vergleich mit dem Wiederbeschaffungswert zählen die Reparaturkosten
    # in derselben Betrachtungsebene; brutto, wenn ausgewiesen.
    reparatur = _zahl(felder.get("reparaturkosten_brutto")) or _zahl(
        felder.get("reparaturkosten_netto")
    )
    abgeleitet["reparaturkosten_vergleich"] = reparatur
    abgeleitet["reparaturkosten_anteil_wbw"] = _anteil(reparatur, wbw_brutto)

    if wbw_brutto is not None and wbw_netto is not None and wbw_netto != 0:
        abgeleitet["wbw_aufschlag_prozent"] = (
            (wbw_brutto - wbw_netto) / wbw_netto * Decimal(100)
        ).quantize(Decimal("0.01"))

    abgeleitet["wertminderung_anteil_wbw"] = _anteil(_zahl(felder.get("wertminderung")), wbw_brutto)

    schaden = felder.get("schadendatum")
    besichtigung = felder.get("besichtigungsdatum")
    if isinstance(schaden, date) and isinstance(besichtigung, date):
        abgeleitet["tage_bis_besichtigung"] = Decimal((besichtigung - schaden).days)

    vin = felder.get("vin")
    if isinstance(vin, str):
        gesaeubert = vin.strip().upper()
        abgeleitet["vin_laenge"] = Decimal(len(gesaeubert))
        abgeleitet["vin_unplausibel"] = not bool(VIN_ZEICHEN.match(gesaeubert))

    kennzeichen = felder.get("kennzeichen")
    im_text = felder.get("kennzeichen_text")
    if isinstance(kennzeichen, str) and isinstance(im_text, str):
        abgeleitet["kennzeichen_abweichend"] = _kennzeichen_schluessel(
            kennzeichen
        ) != _kennzeichen_schluessel(im_text)

    aktenzeichen = felder.get("aktenzeichen")
    if aktenzeichen_muster and isinstance(aktenzeichen, str):
        try:
            abgeleitet["aktenzeichen_muster_verletzt"] = not bool(
                re.fullmatch(aktenzeichen_muster, aktenzeichen.strip())
            )
        except re.error:
            # Ein kaputtes Muster in den Einstellungen darf keinen Befund erzeugen.
            abgeleitet["aktenzeichen_muster_verletzt"] = None

    return abgeleitet


def _kennzeichen_schluessel(text: str) -> str:
    """Vergleichsform: ohne Leerzeichen, Bindestriche und Groß-/Kleinschreibung."""
    treffer = re.search(r"[A-ZÄÖÜ]{1,3}\s?-?\s?[A-Z]{1,2}\s?\d{1,4}\s?[EH]?", text.upper())
    roh = treffer.group() if treffer else text
    return re.sub(r"[^A-Z0-9ÄÖÜ]", "", roh.upper())
