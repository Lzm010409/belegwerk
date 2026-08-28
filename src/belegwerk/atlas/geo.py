"""Umkreissuche über PLZ-Mittelpunkte (Atlas-Todo 0.3 und 3.1).

Haversine auf einer Kugel mit dem mittleren Erdradius. Für Entfernungen bis
etwa 300 km liegt der Fehler gegenüber einer Ellipsoidrechnung deutlich unter
einem halben Prozent — für eine Umkreissuche ist das mehr als genug, und es
erspart eine PostGIS-Abhängigkeit.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

TABELLE = Path(__file__).parent / "daten" / "plz_mittelpunkte.csv"
ERDRADIUS_KM = 6371.0088


class PlzUnbekannt(Exception):
    """Die Meldung sagt, was zu tun ist — nicht nur, dass etwas fehlt."""

    def __init__(self, plz: str) -> None:
        super().__init__(
            f"Für die Postleitzahl {plz} liegt kein Mittelpunkt vor. Bitte eine "
            "benachbarte Postleitzahl verwenden."
        )
        self.plz = plz


@dataclass(frozen=True, slots=True)
class Punkt:
    plz: str
    ort: str
    lat: float
    lon: float
    genauigkeit: str  # 'amtlich' | 'ort' | 'leitregion'

    @property
    def ist_genau(self) -> bool:
        return self.genauigkeit in {"amtlich", "ort"}


@lru_cache(maxsize=1)
def mittelpunkte() -> dict[str, Punkt]:
    punkte: dict[str, Punkt] = {}
    with TABELLE.open(encoding="utf-8", newline="") as datei:
        for zeile in csv.DictReader(datei):
            plz = zeile["plz"].strip()
            # Koordinaten sind bewusst float: hier geht es um Winkelgrade,
            # nicht um Geld. Alles Geldliche bleibt Decimal.
            punkte[plz] = Punkt(
                plz=plz,
                ort=zeile["ort"].strip(),
                lat=float(zeile["lat"]),
                lon=float(zeile["lon"]),
                genauigkeit=zeile["genauigkeit"].strip(),
            )
    return punkte


def punkt(plz: str) -> Punkt:
    gesaeubert = plz.strip()
    gefunden = mittelpunkte().get(gesaeubert)
    if gefunden is None:
        raise PlzUnbekannt(gesaeubert)
    return gefunden


def bekannt(plz: str) -> bool:
    return plz.strip() in mittelpunkte()


def entfernung_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Großkreisentfernung in Kilometern."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = phi2 - phi1
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * ERDRADIUS_KM * asin(sqrt(min(1.0, a)))


def entfernung_zwischen(a: Punkt, b: Punkt) -> float:
    return entfernung_km(a.lat, a.lon, b.lat, b.lon)


def plz_im_umkreis(zentrum: str, radius_km: float) -> dict[str, float]:
    """Alle Postleitzahlen im Radius, mit ihrer Entfernung.

    Vorfilterung über ein Rechteck in Grad, damit nicht für 8.000 Einträge die
    volle Trigonometrie läuft.
    """
    mitte = punkt(zentrum)
    grad_lat = radius_km / 111.2
    grad_lon = radius_km / max(1.0, 111.2 * cos(radians(mitte.lat)))
    ergebnis: dict[str, float] = {}
    for kandidat in mittelpunkte().values():
        if abs(kandidat.lat - mitte.lat) > grad_lat or abs(kandidat.lon - mitte.lon) > grad_lon:
            continue
        strecke = entfernung_zwischen(mitte, kandidat)
        if strecke <= radius_km:
            ergebnis[kandidat.plz] = round(strecke, 1)
    return ergebnis
