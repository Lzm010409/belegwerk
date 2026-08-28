"""Konfidenzberechnung je Adapter (Delta-Todo 2.8).

Unter 0,85 zeigt die Oberfläche die Korrekturansicht. Das ist Kernfunktion,
kein Notbehelf: ein Werkzeug, das bei 90 % Treffern schweigt und bei 10 %
falsch liegt, ist gefährlicher als eins, das seine Unsicherheit zeigt.

Bewertet werden vier Dinge, jedes mit einem Gewicht:

1. **Kontrollrechnung** (0,40) — stimmt die Summe der erkannten Positionen mit
   der im Dokument ausgewiesenen Nettosumme überein? Das ist der härteste
   Nachweis dafür, dass nichts übersehen wurde.
2. **Pflichtfelder** (0,25) — Aktenzeichen, Fahrzeugkennungen, Endsummen.
3. **Abschnitte** (0,20) — hat jeder nicht-optionale Positionsblock Zeilen
   geliefert?
4. **Textgüte** (0,15) — wie gut war der Extraktionspfad überhaupt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from belegwerk.dokumente.modell import Kalkulation

SCHWELLE_KORREKTUR = 0.85
TOLERANZ = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class Konfidenzbefund:
    wert: float
    kontrollrechnung: bool
    unerklaerter_rest: Decimal | None
    fehlende_felder: tuple[str, ...]
    leere_abschnitte: tuple[str, ...]
    textguete: float

    @property
    def braucht_korrektur(self) -> bool:
        return self.wert < SCHWELLE_KORREKTUR


def berechnen(
    kalkulation: Kalkulation,
    *,
    pflichtfelder: tuple[str, ...],
    erwartete_abschnitte: tuple[str, ...],
    gefundene_abschnitte: set[str],
    textguete: float,
) -> Konfidenzbefund:
    fehlend: list[str] = []
    for feld in pflichtfelder:
        wert = {
            "aktenzeichen": kalkulation.aktenzeichen,
            "vin": kalkulation.fahrzeug.vin,
            "kennzeichen": kalkulation.fahrzeug.kennzeichen,
            "netto": kalkulation.summen.netto,
        }.get(feld, "unbekannt")
        if not wert:
            fehlend.append(feld)

    rest: Decimal | None = None
    stimmt = False
    if kalkulation.summen.netto is not None and kalkulation.positionen:
        rest = kalkulation.summe_der_positionen() - kalkulation.summen.netto
        stimmt = abs(rest) <= TOLERANZ

    leer = tuple(sorted(set(erwartete_abschnitte) - gefundene_abschnitte))

    punkte = 0.0
    punkte += 0.40 if stimmt else 0.0
    if pflichtfelder:
        punkte += 0.25 * (1 - len(fehlend) / len(pflichtfelder))
    else:
        punkte += 0.25
    if erwartete_abschnitte:
        punkte += 0.20 * (1 - len(leer) / len(erwartete_abschnitte))
    else:
        punkte += 0.20
    punkte += 0.15 * min(1.0, max(0.0, textguete))

    if not kalkulation.positionen:
        punkte = min(punkte, 0.20)

    return Konfidenzbefund(
        wert=round(min(1.0, max(0.0, punkte)), 4),
        kontrollrechnung=stimmt,
        unerklaerter_rest=rest if not stimmt else None,
        fehlende_felder=tuple(fehlend),
        leere_abschnitte=leer,
        textguete=textguete,
    )
