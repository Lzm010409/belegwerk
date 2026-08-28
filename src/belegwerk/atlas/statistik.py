"""Auswertungslogik (Atlas-Briefing Abschnitt 4).

**Statistische Ehrlichkeit ist Produktmerkmal.** Bei weniger als fünf Betrieben
im Umkreis zeigt die Auswertung keinen Median, sondern den Hinweis, dass die
Datenbasis für eine Aussage zu dünn ist. Eine Anlage mit einem „Median" aus drei
Werten fällt dem Sachverständigen in der ersten Auseinandersetzung auf die Füße.

Alle Kennzahlen sind ``Decimal``. Perzentile werden linear interpoliert und auf
zwei Nachkommastellen gerundet; der Rechenweg ist im PDF benannt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

MINDESTANZAHL = 5

SATZARTEN: tuple[tuple[str, str], ...] = (
    ("satz_mechanik", "Stundensatz Mechanik"),
    ("satz_karosserie", "Stundensatz Karosserie"),
    ("satz_elektrik", "Stundensatz Elektrik"),
    ("satz_lack_lohn", "Stundensatz Lack"),
    ("lack_material_prozent", "Lackmaterial in Prozent"),
    ("upe_aufschlag_prozent", "UPE-Aufschlag in Prozent"),
    ("verbringung_pauschale", "Verbringung pauschal"),
    ("entsorgung", "Entsorgung"),
)


def _r(wert: Decimal) -> Decimal:
    return wert.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def perzentil(werte: list[Decimal], anteil: Decimal) -> Decimal:
    """Lineare Interpolation zwischen den Rängen (Methode „linear")."""
    if not werte:
        raise ValueError("Perzentil einer leeren Reihe")
    sortiert = sorted(werte)
    if len(sortiert) == 1:
        return _r(sortiert[0])
    stelle = (Decimal(len(sortiert)) - 1) * anteil
    unten = int(stelle)
    oben = min(unten + 1, len(sortiert) - 1)
    rest = stelle - Decimal(unten)
    return _r(sortiert[unten] + (sortiert[oben] - sortiert[unten]) * rest)


@dataclass(frozen=True, slots=True)
class Kennzahlen:
    feld: str
    beschriftung: str
    anzahl: int
    anzahl_veraltet: int
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    werte: tuple[Decimal, ...] = ()

    @property
    def belastbar(self) -> bool:
        return self.anzahl >= MINDESTANZAHL

    @property
    def hinweis(self) -> str | None:
        if self.belastbar:
            return None
        if self.anzahl == 0:
            return "Für diesen Satz liegt im gewählten Umkreis keine Erhebung vor."
        return (
            f"Im gewählten Umkreis liegen nur {self.anzahl} Erhebungen vor. "
            f"Für eine belastbare Aussage sind mindestens {MINDESTANZAHL} nötig; "
            "es wird deshalb kein Median ausgewiesen."
        )


@dataclass(slots=True)
class Auswertungsergebnis:
    kennzahlen: list[Kennzahlen]
    anzahl_betriebe: int
    anzahl_erhebungen: int
    anzahl_veraltet: int
    stichtag: date
    hinweise: list[str] = field(default_factory=list)

    def nach_feld(self, feld: str) -> Kennzahlen | None:
        for eintrag in self.kennzahlen:
            if eintrag.feld == feld:
                return eintrag
        return None

    @property
    def hat_belastbare_aussage(self) -> bool:
        return any(k.belastbar for k in self.kennzahlen)


def kennzahlen_bilden(
    feld: str, beschriftung: str, aktuelle: list[Decimal], veraltete: int
) -> Kennzahlen:
    if len(aktuelle) < MINDESTANZAHL:
        return Kennzahlen(
            feld=feld,
            beschriftung=beschriftung,
            anzahl=len(aktuelle),
            anzahl_veraltet=veraltete,
            median=None,
            minimum=_r(min(aktuelle)) if aktuelle else None,
            maximum=_r(max(aktuelle)) if aktuelle else None,
            p25=None,
            p75=None,
            werte=tuple(sorted(aktuelle)),
        )
    return Kennzahlen(
        feld=feld,
        beschriftung=beschriftung,
        anzahl=len(aktuelle),
        anzahl_veraltet=veraltete,
        median=perzentil(aktuelle, Decimal("0.5")),
        minimum=_r(min(aktuelle)),
        maximum=_r(max(aktuelle)),
        p25=perzentil(aktuelle, Decimal("0.25")),
        p75=perzentil(aktuelle, Decimal("0.75")),
        werte=tuple(sorted(aktuelle)),
    )
