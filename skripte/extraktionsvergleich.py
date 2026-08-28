#!/usr/bin/env python3
"""Stellt beide Extraktionspfade je Dokument nebeneinander (Delta-Todo 0.2).

    python skripte/extraktionsvergleich.py tests/fixtures/dokumente

Schreibt eine Tabelle nach stdout: je Dokument die Güte beider Pfade, welcher
gewinnt, wie viele Positionszeilen erkannt werden und ob die Kontrollrechnung
aufgeht. Das ist die Grundlage für die Abbruchentscheidung aus Todo 0.3.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from belegwerk.dokumente.erkennung import verarbeiten  # noqa: E402
from belegwerk.dokumente.text import _mit_pdfplumber, _mit_pdftotext  # noqa: E402


def main(verzeichnis: Path) -> int:
    dateien = sorted(p for p in verzeichnis.rglob("*") if p.suffix.lower() in {".pdf", ".txt", ".vxs"})
    if not dateien:
        print(f"Keine Dokumente in {verzeichnis}", file=sys.stderr)
        return 1

    kopf = f"{'Datei':<34}{'plumber':>9}{'poppler':>9}  {'gewaehlt':<10}{'Pos':>5}{'Konf':>7}  Kontrolle"
    print(kopf)
    print("-" * len(kopf))
    tragfaehig = 0
    for datei in dateien:
        daten = datei.read_bytes()
        plumber = poppler = None
        if datei.suffix.lower() == ".pdf":
            a = _mit_pdfplumber(daten)
            b = _mit_pdftotext(daten)
            plumber = a.guete if a else None
            poppler = b.guete if b else None
        try:
            kalkulation = verarbeiten(daten)
        except Exception as fehler:  # noqa: BLE001 — Bestandsaufnahme, kein Abbruch
            print(f"{datei.name:<34}{'':>18}  {type(fehler).__name__}")
            continue
        stimmt = (
            kalkulation.summen.netto is not None
            and abs(kalkulation.summe_der_positionen() - kalkulation.summen.netto) <= 2
        )
        tragfaehig += 1 if stimmt and kalkulation.positionen else 0
        print(
            f"{datei.name:<34}"
            f"{(f'{plumber:.3f}' if plumber is not None else '-'):>9}"
            f"{(f'{poppler:.3f}' if poppler is not None else '-'):>9}  "
            f"{kalkulation.adapter:<10}{len(kalkulation.positionen):>5}{kalkulation.konfidenz:>7.3f}  "
            f"{'geht auf' if stimmt else 'ABWEICHUNG'}"
        )

    quote = tragfaehig / len(dateien)
    print()
    print(f"Tragfaehig: {tragfaehig} von {len(dateien)} = {quote:.0%}")
    print("Todo 0.3 verlangt mindestens 80 % auf ECHTEN Dokumenten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/dokumente")))
