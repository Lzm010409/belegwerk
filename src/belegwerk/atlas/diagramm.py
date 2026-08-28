"""Verteilungsdiagramm, serverseitig als SVG (Atlas-Todo 3.4).

Kein Chart-JS: das Diagramm gehört in die PDF-Anlage, und was dort steht, muss
auf dem Server entstehen. Dieselbe Datei wird in der Oberfläche eingebettet.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from belegwerk.atlas.statistik import Kennzahlen
from belegwerk.kern.formate import zahl

BREITE = 560
HOEHE = 170
RAND_LINKS = 46
RAND_UNTEN = 30
RAND_OBEN = 14


def _klassen(werte: list[Decimal], anzahl: int) -> tuple[list[int], Decimal, Decimal]:
    kleinster, groesster = min(werte), max(werte)
    if kleinster == groesster:
        return [len(werte)], kleinster, groesster
    spanne = groesster - kleinster
    behaelter = [0] * anzahl
    for wert in werte:
        stelle = int((wert - kleinster) / spanne * anzahl)
        behaelter[min(stelle, anzahl - 1)] += 1
    return behaelter, kleinster, groesster


def verteilung_svg(kennzahl: Kennzahlen, klassen: int = 8) -> str:
    """Balkendiagramm der Werteverteilung als eigenständiges SVG."""
    werte = list(kennzahl.werte)
    titel = f"Verteilung {kennzahl.beschriftung}"
    if not werte:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BREITE} 60" role="img" '
            f'aria-label="{escape(titel)}: keine Werte">'
            f'<text x="8" y="34" font-family="Public Sans, sans-serif" font-size="12" '
            f'fill="#6E747C">Keine Werte im gewählten Umkreis.</text></svg>'
        )

    behaelter, kleinster, groesster = _klassen(werte, min(klassen, max(1, len(set(werte)))))
    hoechste = max(behaelter) or 1
    zeichenbreite = BREITE - RAND_LINKS - 10
    zeichenhoehe = HOEHE - RAND_UNTEN - RAND_OBEN
    balkenbreite = zeichenbreite / len(behaelter)

    teile: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BREITE} {HOEHE}" role="img" '
        f'aria-label="{escape(titel)}, {kennzahl.anzahl} Werte">',
        f"<title>{escape(titel)}</title>",
        f'<line x1="{RAND_LINKS}" y1="{RAND_OBEN + zeichenhoehe}" x2="{BREITE - 10}" '
        f'y2="{RAND_OBEN + zeichenhoehe}" stroke="#14181D" stroke-width="1"/>',
    ]

    for nummer, anzahl in enumerate(behaelter):
        hoehe = (anzahl / hoechste) * zeichenhoehe
        x = RAND_LINKS + nummer * balkenbreite
        y = RAND_OBEN + zeichenhoehe - hoehe
        teile.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{balkenbreite - 3:.1f}" height="{hoehe:.1f}" '
            f'fill="#14181D"/>'
        )
        if anzahl:
            teile.append(
                f'<text x="{x + (balkenbreite - 3) / 2:.1f}" y="{y - 3:.1f}" text-anchor="middle" '
                f'font-family="JetBrains Mono, monospace" font-size="9" fill="#4A5058">{anzahl}</text>'
            )

    if kennzahl.median is not None and groesster != kleinster:
        anteil = float((kennzahl.median - kleinster) / (groesster - kleinster))
        x = RAND_LINKS + anteil * zeichenbreite
        teile.append(
            f'<line x1="{x:.1f}" y1="{RAND_OBEN - 4}" x2="{x:.1f}" y2="{RAND_OBEN + zeichenhoehe}" '
            f'stroke="#C8102E" stroke-width="2"/>'
        )
        teile.append(
            f'<text x="{x:.1f}" y="{RAND_OBEN - 6}" text-anchor="middle" '
            f'font-family="JetBrains Mono, monospace" font-size="9" fill="#C8102E">Median</text>'
        )

    for beschriftung, x, anker in (
        (zahl(kleinster), RAND_LINKS, "start"),
        (zahl(groesster), BREITE - 10, "end"),
    ):
        teile.append(
            f'<text x="{x}" y="{HOEHE - 10}" text-anchor="{anker}" '
            f'font-family="JetBrains Mono, monospace" font-size="10" fill="#4A5058">'
            f"{escape(beschriftung)}</text>"
        )
    teile.append(
        f'<text x="6" y="{RAND_OBEN + 10}" font-family="JetBrains Mono, monospace" '
        f'font-size="10" fill="#4A5058">{hoechste}</text>'
    )
    teile.append("</svg>")
    return "".join(teile)
