"""Das normalisierte Datenmodell (Plattformdatei 4.2).

Alle Geldbeträge sind ``Decimal``, niemals ``float``. Das ist nicht Pedanterie:
eine Rundungsdifferenz von einem Cent in einer Delta-Tabelle, die einem
Versicherer vorgelegt wird, kostet Glaubwürdigkeit.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


class Quelle(str, enum.Enum):
    DAT = "DAT"
    AUDATEX = "AUDATEX"
    PRUEFBERICHT = "PRUEFBERICHT"
    UNBEKANNT = "UNBEKANNT"


class PositionsArt(str, enum.Enum):
    ERSATZTEIL = "ERSATZTEIL"
    ARBEIT = "ARBEIT"
    LACK = "LACK"
    NEBENKOSTEN = "NEBENKOSTEN"


@dataclass(slots=True)
class Fahrzeug:
    hersteller: str | None = None
    modell: str | None = None
    vin: str | None = None
    kennzeichen: str | None = None
    erstzulassung: date | None = None
    laufleistung_km: int | None = None


@dataclass(slots=True)
class Verrechnungssaetze:
    mechanik: Decimal | None = None
    karosserie: Decimal | None = None
    elektrik: Decimal | None = None
    lack_lohn: Decimal | None = None
    lack_material_prozent: Decimal | None = None
    upe_aufschlag_prozent: Decimal | None = None
    verbringung: Decimal | None = None

    def als_liste(self) -> list[tuple[str, Decimal | None]]:
        return [
            ("Mechanik", self.mechanik),
            ("Karosserie", self.karosserie),
            ("Elektrik", self.elektrik),
            ("Lacklohn", self.lack_lohn),
            ("Lackmaterial %", self.lack_material_prozent),
            ("UPE-Aufschlag %", self.upe_aufschlag_prozent),
            ("Verbringung", self.verbringung),
        ]


@dataclass(slots=True)
class Summen:
    ersatzteile: Decimal | None = None
    arbeit: Decimal | None = None
    lack: Decimal | None = None
    nebenkosten: Decimal | None = None
    netto: Decimal | None = None
    mehrwertsteuer: Decimal | None = None
    brutto: Decimal | None = None


@dataclass(slots=True)
class Position:
    laufnummer: int
    art: PositionsArt
    bezeichnung: str
    betrag: Decimal
    teilenummer: str | None = None
    arbeitswerte: Decimal | None = None
    stundensatz: Decimal | None = None
    lackstufe: int | None = None
    einzelpreis: Decimal | None = None
    aufschlag_prozent: Decimal | None = None
    rohzeile: str = ""

    @property
    def schluessel(self) -> str:
        """Menschenlesbare Kennung für Protokolle und Fehlermeldungen."""
        return f"{self.laufnummer:03d} {self.bezeichnung}"


@dataclass(slots=True)
class Kalkulation:
    quelle: Quelle
    quellformat: str  # 'vxs' | 'pdf' | 'txt'
    adapter: str
    aktenzeichen: str | None = None
    fahrzeug: Fahrzeug = field(default_factory=Fahrzeug)
    saetze: Verrechnungssaetze = field(default_factory=Verrechnungssaetze)
    positionen: list[Position] = field(default_factory=list)
    summen: Summen = field(default_factory=Summen)
    rohtext: str = ""
    konfidenz: float = 0.0
    hinweise: list[str] = field(default_factory=list)

    def positionen_nach_art(self, art: PositionsArt) -> list[Position]:
        return [p for p in self.positionen if p.art is art]

    def summe_der_positionen(self) -> Decimal:
        return sum((p.betrag for p in self.positionen), Decimal("0.00"))

    def summe_je_art(self) -> dict[PositionsArt, Decimal]:
        ergebnis = {art: Decimal("0.00") for art in PositionsArt}
        for position in self.positionen:
            ergebnis[position.art] += position.betrag
        return ergebnis

    # -- Serialisierung: Golden-Tests, Persistenz, JSON-Export ---------------

    def als_dict(self, mit_rohtext: bool = False) -> dict[str, Any]:
        daten = asdict(self)
        daten["quelle"] = self.quelle.value
        daten["fahrzeug"]["erstzulassung"] = (
            self.fahrzeug.erstzulassung.isoformat() if self.fahrzeug.erstzulassung else None
        )
        for position, roh in zip(daten["positionen"], self.positionen, strict=True):
            position["art"] = roh.art.value
        if not mit_rohtext:
            daten.pop("rohtext", None)
        umgewandelt: dict[str, Any] = _dezimal_zu_text(daten)
        return umgewandelt


def _dezimal_zu_text(wert: Any) -> Any:
    """``Decimal`` als Zeichenkette serialisieren — kein Umweg über ``float``."""
    if isinstance(wert, Decimal):
        return str(wert)
    if isinstance(wert, dict):
        return {schluessel: _dezimal_zu_text(inhalt) for schluessel, inhalt in wert.items()}
    if isinstance(wert, list):
        return [_dezimal_zu_text(eintrag) for eintrag in wert]
    return wert
