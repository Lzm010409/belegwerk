"""Abweichungsklassen und Euro-Auswirkung (Delta-Briefing 2.2 und 2.3).

Jede Differenz wird in genau eine Klasse einsortiert. Die Klasse steuert die
Formulierung im Export und den JSON-Schlüssel für ein anschließendes
Stellungnahme-Werkzeug.

Die Reihenfolge der Prüfungen ist die Aussage: die spezifischste erkennbare
Ursache gewinnt. „Der Lackaufwand wurde um eine Stufe gesenkt" ist eine
brauchbare Feststellung; „der Betrag ist kleiner" ist es nicht.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

from belegwerk.delta.zuordnung import Paar, aehnlichkeit
from belegwerk.dokumente.modell import Position, PositionsArt

NULL = Decimal("0.00")


class Klasse(str, enum.Enum):
    POS_ENTFALLEN = "POS_ENTFALLEN"
    POS_ERGAENZT = "POS_ERGAENZT"
    AW_REDUZIERT = "AW_REDUZIERT"
    LACKSTUFE_GESENKT = "LACKSTUFE_GESENKT"
    SATZ_GESENKT = "SATZ_GESENKT"
    UPE_GEKUERZT = "UPE_GEKUERZT"
    VERBRINGUNG_ENTFALLEN = "VERBRINGUNG_ENTFALLEN"
    LACKMATERIAL_GEKUERZT = "LACKMATERIAL_GEKUERZT"
    TEIL_ERSETZT = "TEIL_ERSETZT"
    REP_STATT_TAUSCH = "REP_STATT_TAUSCH"
    BETRAG_ABWEICHEND = "BETRAG_ABWEICHEND"

    @property
    def beschriftung(self) -> str:
        return BESCHRIFTUNG[self]

    @property
    def erlaeuterung(self) -> str:
        return ERLAEUTERUNG[self]


BESCHRIFTUNG = {
    Klasse.POS_ENTFALLEN: "Position gestrichen",
    Klasse.POS_ERGAENZT: "Position hinzugefügt",
    Klasse.AW_REDUZIERT: "Arbeitswerte gekürzt",
    Klasse.LACKSTUFE_GESENKT: "Lackstufe herabgesetzt",
    Klasse.SATZ_GESENKT: "Stundenverrechnungssatz reduziert",
    Klasse.UPE_GEKUERZT: "UPE-Aufschlag gekürzt",
    Klasse.VERBRINGUNG_ENTFALLEN: "Verbringungskosten gestrichen",
    Klasse.LACKMATERIAL_GEKUERZT: "Lackmaterialindex reduziert",
    Klasse.TEIL_ERSETZT: "Auf Ident- oder Gebrauchtteil umgestellt",
    Klasse.REP_STATT_TAUSCH: "Instandsetzung statt Ersatz",
    Klasse.BETRAG_ABWEICHEND: "Betrag weicht ab",
}

ERLAEUTERUNG = {
    Klasse.POS_ENTFALLEN: "Die Position ist im Prüfbericht nicht mehr enthalten.",
    Klasse.POS_ERGAENZT: "Der Prüfbericht führt eine Position, die in der Kalkulation nicht steht.",
    Klasse.AW_REDUZIERT: "Der Prüfbericht setzt weniger Arbeitswerte an.",
    Klasse.LACKSTUFE_GESENKT: "Der Prüfbericht setzt eine niedrigere Lackstufe an.",
    Klasse.SATZ_GESENKT: "Der Prüfbericht rechnet mit einem niedrigeren Stundenverrechnungssatz.",
    Klasse.UPE_GEKUERZT: "Der Prüfbericht kürzt oder streicht den UPE-Aufschlag.",
    Klasse.VERBRINGUNG_ENTFALLEN: "Die Verbringungskosten sind im Prüfbericht nicht enthalten.",
    Klasse.LACKMATERIAL_GEKUERZT: "Der Prüfbericht rechnet mit einem niedrigeren Materialindex.",
    Klasse.TEIL_ERSETZT: "Die Teilenummer weicht ab; angesetzt ist ein anderes Teil.",
    Klasse.REP_STATT_TAUSCH: "Statt des Ersatzteils ist eine Instandsetzung angesetzt.",
    Klasse.BETRAG_ABWEICHEND: "Der Betrag weicht ab, ohne dass eine Ursache erkennbar ist.",
}


@dataclass(frozen=True, slots=True)
class Abweichung:
    klasse: Klasse
    paar: Paar
    differenz_netto: Decimal
    bezeichnung: str
    wert_eigen: str | None
    wert_pruefbericht: str | None

    @property
    def art(self) -> PositionsArt:
        position = self.paar.a or self.paar.b
        assert position is not None
        return position.art

    @property
    def laufnummer(self) -> int:
        position = self.paar.a or self.paar.b
        assert position is not None
        return position.laufnummer

    @property
    def beleg_eigen(self) -> str | None:
        return self.paar.a.rohzeile if self.paar.a else None

    @property
    def beleg_pruefbericht(self) -> str | None:
        return self.paar.b.rohzeile if self.paar.b else None


def _ist_verbringung(position: Position) -> bool:
    from belegwerk.delta.zuordnung import wortmenge

    return "verbringung" in wortmenge(position.bezeichnung) or "verbringungskosten" in wortmenge(
        position.bezeichnung
    )


def _kleiner(neu: Decimal | int | None, alt: Decimal | int | None) -> bool:
    return neu is not None and alt is not None and neu < alt


def _text(wert: object) -> str | None:
    if wert is None:
        return None
    return str(wert)


def klassifizieren(paar: Paar) -> Abweichung | None:
    """Ordnet ein Paar genau einer Klasse zu. ``None`` heißt: unverändert."""
    a, b = paar.a, paar.b

    if b is None:
        assert a is not None
        klasse = Klasse.VERBRINGUNG_ENTFALLEN if _ist_verbringung(a) else Klasse.POS_ENTFALLEN
        return Abweichung(
            klasse=klasse,
            paar=paar,
            differenz_netto=a.betrag,
            bezeichnung=a.bezeichnung,
            wert_eigen=_text(a.betrag),
            wert_pruefbericht="0.00",
        )

    if a is None:
        assert b is not None
        return Abweichung(
            klasse=Klasse.POS_ERGAENZT,
            paar=paar,
            differenz_netto=-b.betrag,
            bezeichnung=b.bezeichnung,
            wert_eigen="0.00",
            wert_pruefbericht=_text(b.betrag),
        )

    differenz = a.betrag - b.betrag

    # Instandsetzung statt Ersatz: die Art der Position hat gewechselt.
    if a.art is PositionsArt.ERSATZTEIL and b.art is PositionsArt.ARBEIT:
        return Abweichung(
            Klasse.REP_STATT_TAUSCH, paar, differenz, a.bezeichnung, _text(a.betrag), _text(b.betrag)
        )

    # Anderes Teil bei ähnlicher Bezeichnung.
    if (
        a.teilenummer
        and b.teilenummer
        and a.teilenummer != b.teilenummer
        and aehnlichkeit(a.bezeichnung, b.bezeichnung) >= 80
    ):
        return Abweichung(
            Klasse.TEIL_ERSETZT, paar, differenz, a.bezeichnung, a.teilenummer, b.teilenummer
        )

    if _kleiner(b.lackstufe, a.lackstufe):
        return Abweichung(
            Klasse.LACKSTUFE_GESENKT,
            paar,
            differenz,
            a.bezeichnung,
            _text(a.lackstufe),
            _text(b.lackstufe),
        )

    if _kleiner(b.arbeitswerte, a.arbeitswerte):
        return Abweichung(
            Klasse.AW_REDUZIERT,
            paar,
            differenz,
            a.bezeichnung,
            _text(a.arbeitswerte),
            _text(b.arbeitswerte),
        )

    if _kleiner(b.stundensatz, a.stundensatz):
        return Abweichung(
            Klasse.SATZ_GESENKT,
            paar,
            differenz,
            a.bezeichnung,
            _text(a.stundensatz),
            _text(b.stundensatz),
        )

    if _kleiner(b.aufschlag_prozent, a.aufschlag_prozent):
        return Abweichung(
            Klasse.UPE_GEKUERZT,
            paar,
            differenz,
            a.bezeichnung,
            _text(a.aufschlag_prozent),
            _text(b.aufschlag_prozent),
        )

    # Lackposition, bei der Arbeitswerte und Satz unverändert sind, der Betrag
    # aber niedriger: dann bleibt als Ursache der Materialindex.
    if (
        a.art is PositionsArt.LACK
        and differenz > 0
        and a.arbeitswerte == b.arbeitswerte
        and a.stundensatz == b.stundensatz
    ):
        return Abweichung(
            Klasse.LACKMATERIAL_GEKUERZT,
            paar,
            differenz,
            a.bezeichnung,
            _text(a.betrag),
            _text(b.betrag),
        )

    if differenz != NULL:
        return Abweichung(
            Klasse.BETRAG_ABWEICHEND, paar, differenz, a.bezeichnung, _text(a.betrag), _text(b.betrag)
        )

    return None
