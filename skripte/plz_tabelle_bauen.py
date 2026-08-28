#!/usr/bin/env python3
"""Baut `atlas/daten/plz_mittelpunkte.csv` aus einer Quelldatei.

    python skripte/plz_tabelle_bauen.py quelle.csv

Erwartet eine CSV mit den Spalten `plz`, `ort`, `lat`, `lon` — so liefern es
der GeoNames-Postleitzahlenexport und die OpenStreetMap-Auszüge. Die erzeugte
Tabelle ersetzt die mitgelieferte Näherung (siehe `daten/HERKUNFT.md`).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parents[1] / "src/belegwerk/atlas/daten/plz_mittelpunkte.csv"


def main(quelle: Path) -> int:
    zeilen: list[tuple[str, str, str, str, str]] = []
    with quelle.open(encoding="utf-8", newline="") as datei:
        for satz in csv.DictReader(datei):
            plz = (satz.get("plz") or satz.get("postal_code") or "").strip()
            lat = (satz.get("lat") or satz.get("latitude") or "").strip()
            lon = (satz.get("lon") or satz.get("longitude") or "").strip()
            if len(plz) != 5 or not plz.isdigit() or not lat or not lon:
                continue
            ort = (satz.get("ort") or satz.get("place_name") or "").strip()
            zeilen.append((plz, ort, f"{float(lat):.5f}", f"{float(lon):.5f}", "amtlich"))

    if not zeilen:
        print(f"Keine verwertbaren Zeilen in {quelle}", file=sys.stderr)
        return 1

    zeilen.sort()
    with ZIEL.open("w", encoding="utf-8", newline="") as datei:
        schreiber = csv.writer(datei)
        schreiber.writerow(["plz", "ort", "lat", "lon", "genauigkeit"])
        schreiber.writerows(zeilen)
    print(f"{len(zeilen)} Postleitzahlen nach {ZIEL} geschrieben")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
