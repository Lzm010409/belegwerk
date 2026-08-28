"""Das gemeinsame Dokumentenpaket.

Der wichtigste Baustein der Plattform: hier werden DAT-, Audatex- und
Prüfbericht-Dokumente in ein normalisiertes Modell überführt. **Kein Modul
außerhalb dieses Pakets sieht jemals ein PDF** (Plattformdatei 4.1) — Delta,
Atlas und Check arbeiten ausschließlich mit ``modell.Kalkulation``.
"""

from belegwerk.dokumente.modell import (
    Fahrzeug,
    Kalkulation,
    Position,
    PositionsArt,
    Quelle,
    Summen,
    Verrechnungssaetze,
)

__all__ = [
    "Fahrzeug",
    "Kalkulation",
    "Position",
    "PositionsArt",
    "Quelle",
    "Summen",
    "Verrechnungssaetze",
]
