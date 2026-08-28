"""Summen und die Kontrollrechnung (Delta-Briefing 2.3).

**Nicht verhandelbar:** Die Summe aller Positionsdifferenzen muss der Differenz
der ausgewiesenen Endsummen entsprechen. Weicht sie ab, zeigt die Oberfläche
eine Warnung mit dem unerklärten Restbetrag statt eines scheinbar sauberen
Ergebnisses. Ein stiller Rundungsfehler in einem Dokument, das an den
Versicherer geht, ist der schlimmste denkbare Produktfehler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from belegwerk.delta.klassifikation import Abweichung, Klasse
from belegwerk.dokumente.modell import Kalkulation, PositionsArt

NULL = Decimal("0.00")
TOLERANZ = Decimal("0.02")
REGELSTEUERSATZ = Decimal("19.0")


def _r(wert: Decimal) -> Decimal:
    return wert.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Gruppensumme:
    beschriftung: str
    eigen: Decimal
    pruefbericht: Decimal

    @property
    def differenz(self) -> Decimal:
        return _r(self.eigen - self.pruefbericht)


@dataclass(slots=True)
class Ergebnis:
    abweichungen: list[Abweichung]
    gruppen: list[Gruppensumme]
    eigen_netto: Decimal | None
    pruefbericht_netto: Decimal | None
    differenz_netto: Decimal
    differenz_brutto: Decimal
    mehrwertsteuersatz: Decimal
    kontrolle_geht_auf: bool
    unerklaerter_rest: Decimal
    hinweise: list[str] = field(default_factory=list)

    @property
    def anzahl_je_klasse(self) -> dict[Klasse, int]:
        gezaehlt: dict[Klasse, int] = {}
        for abweichung in self.abweichungen:
            gezaehlt[abweichung.klasse] = gezaehlt.get(abweichung.klasse, 0) + 1
        return gezaehlt

    @property
    def summe_der_abweichungen(self) -> Decimal:
        return _r(sum((a.differenz_netto for a in self.abweichungen), NULL))


def _gruppe(
    abweichungen: list[Abweichung], arten: set[PositionsArt], beschriftung: str
) -> Gruppensumme:
    eigen = NULL
    pruef = NULL
    for abweichung in abweichungen:
        if abweichung.art not in arten:
            continue
        if abweichung.paar.a is not None:
            eigen += abweichung.paar.a.betrag
        if abweichung.paar.b is not None:
            pruef += abweichung.paar.b.betrag
    return Gruppensumme(beschriftung, _r(eigen), _r(pruef))


def auswerten(
    eigen: Kalkulation, pruefbericht: Kalkulation, abweichungen: list[Abweichung]
) -> Ergebnis:
    """Rechnet die Summenzeilen und führt die Kontrollrechnung aus."""
    gruppen = [
        _gruppe(abweichungen, {PositionsArt.ERSATZTEIL}, "Ersatzteile"),
        _gruppe(abweichungen, {PositionsArt.ARBEIT, PositionsArt.LACK}, "Arbeit und Lack"),
        _gruppe(abweichungen, {PositionsArt.NEBENKOSTEN}, "Nebenkosten"),
    ]

    summe_positionen = _r(sum((a.differenz_netto for a in abweichungen), NULL))

    eigen_netto = eigen.summen.netto
    pruef_netto = pruefbericht.summen.netto
    hinweise: list[str] = []

    if eigen_netto is not None and pruef_netto is not None:
        differenz_endsummen = _r(eigen_netto - pruef_netto)
        rest = _r(summe_positionen - differenz_endsummen)
        geht_auf = abs(rest) <= TOLERANZ
        differenz = differenz_endsummen
        if not geht_auf:
            hinweise.append(
                "Die Summe der Positionsdifferenzen ergibt "
                f"{summe_positionen}, die Differenz der ausgewiesenen Endsummen "
                f"{differenz_endsummen}. Unerklärt bleiben {rest}. "
                "Prüfen Sie die Zuordnung, bevor Sie die Anlage verwenden."
            )
    else:
        # Ohne ausgewiesene Endsummen lässt sich nichts kontrollieren — und das
        # ist zu sagen, statt es zu verschweigen.
        differenz = summe_positionen
        rest = NULL
        geht_auf = False
        fehlt = "der eigenen Kalkulation" if eigen_netto is None else "des Prüfberichts"
        hinweise.append(
            f"In {fehlt} ist keine Nettoendsumme erkennbar. Die Kontrollrechnung "
            "konnte deshalb nicht ausgeführt werden; die Gesamtdifferenz ist die "
            "Summe der erkannten Positionsdifferenzen."
        )

    satz = _steuersatz(eigen)
    return Ergebnis(
        abweichungen=abweichungen,
        gruppen=gruppen,
        eigen_netto=eigen_netto,
        pruefbericht_netto=pruef_netto,
        differenz_netto=differenz,
        differenz_brutto=_r(differenz * (Decimal(100) + satz) / Decimal(100)),
        mehrwertsteuersatz=satz,
        kontrolle_geht_auf=geht_auf,
        unerklaerter_rest=rest,
        hinweise=hinweise,
    )


def _steuersatz(kalkulation: Kalkulation) -> Decimal:
    """Der im Dokument ausgewiesene Satz, sonst der Regelsteuersatz.

    Der Satz wird aus den ausgewiesenen Summen zurückgerechnet und nie geraten:
    steht er nicht im Dokument, gilt der Regelsteuersatz, und das steht so in
    der Anlage.
    """
    netto = kalkulation.summen.netto
    steuer = kalkulation.summen.mehrwertsteuer
    if netto and steuer and netto != 0:
        satz = (steuer / netto * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if Decimal("0") < satz <= Decimal("30"):
            return satz
    return REGELSTEUERSATZ


def satzvergleich(eigen: Kalkulation, pruefbericht: Kalkulation) -> list[tuple[str, str, str]]:
    """Verrechnungssätze nebeneinander — die Ursache vieler Positionsdifferenzen."""
    zeilen: list[tuple[str, str, str]] = []
    for (beschriftung, links), (_, rechts) in zip(
        eigen.saetze.als_liste(), pruefbericht.saetze.als_liste(), strict=True
    ):
        if links is None and rechts is None:
            continue
        zeilen.append(
            (
                beschriftung,
                "—" if links is None else str(links),
                "—" if rechts is None else str(rechts),
            )
        )
    return zeilen
