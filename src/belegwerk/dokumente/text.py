"""Textgewinnung aus PDF über zwei Pfade (Plattformdatei Abschnitt 2).

``pdfplumber`` erhält das Layout und liefert Wortkoordinaten. ``pdftotext
-layout`` (poppler) liefert bei manchen DAT-Ausgaben sauberere Spalten. Beide
Pfade werden ausgeführt, ein Qualitätsscore entscheidet — nicht eine Annahme
darüber, welches Werkzeug „besser" ist.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

_log = logging.getLogger(__name__)

# Eine Zeile, die wie eine Positionszeile aussieht: irgendwo eine laufende
# Nummer und mindestens ein Betrag im deutschen Format.
_BETRAG = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
_LAUFNUMMER = re.compile(r"^\s{0,6}(\d{1,3})[\s.)]")
_SPALTENLUECKE = re.compile(r"\S {2,}\S")


@dataclass(frozen=True, slots=True)
class Extraktion:
    """Ergebnis eines Extraktionspfads."""

    pfad: str  # 'pdfplumber' | 'pdftotext'
    text: str
    seiten: int
    guete: float

    @property
    def zeilen(self) -> list[str]:
        return self.text.splitlines()


def guete_bewerten(text: str) -> float:
    """Wie brauchbar ist dieser Text für einen zeilenweisen Parser? 0..1.

    Bewertet drei Dinge, die für Kalkulationsausdrucke tatsächlich zählen:
    wie viele Zeilen Beträge tragen, wie viele davon eine laufende Nummer
    beginnt, und ob die Spalten durch Mehrfachleerzeichen erhalten blieben.
    """
    zeilen = [z for z in text.splitlines() if z.strip()]
    if not zeilen:
        return 0.0
    mit_betrag = sum(1 for z in zeilen if _BETRAG.search(z))
    if mit_betrag == 0:
        return 0.0
    mit_nummer = sum(1 for z in zeilen if _BETRAG.search(z) and _LAUFNUMMER.match(z))
    mit_spalten = sum(1 for z in zeilen if _BETRAG.search(z) and _SPALTENLUECKE.search(z))

    anteil_betrag = min(1.0, mit_betrag / max(12, len(zeilen) * 0.2))
    anteil_nummer = mit_nummer / mit_betrag
    anteil_spalten = mit_spalten / mit_betrag
    return round(0.4 * anteil_betrag + 0.35 * anteil_nummer + 0.25 * anteil_spalten, 4)


def _mit_pdfplumber(daten: bytes) -> Extraktion | None:
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as datei:
            datei.write(daten)
            datei.flush()
            with pdfplumber.open(datei.name) as dokument:
                seiten = len(dokument.pages)
                teile = [
                    seite.extract_text(layout=True, x_density=4.5, y_density=9) or ""
                    for seite in dokument.pages
                ]
    except Exception as fehler:  # noqa: BLE001 — ein Pfad darf ausfallen
        _log.warning("pdfplumber fehlgeschlagen", extra={"fehlerart": type(fehler).__name__})
        return None
    text = "\n".join(teile)
    return Extraktion("pdfplumber", text, seiten, guete_bewerten(text))


def _mit_pdftotext(daten: bytes) -> Extraktion | None:
    werkzeug = shutil.which("pdftotext")
    if werkzeug is None:
        return None
    with tempfile.TemporaryDirectory() as ordner:
        quelle = Path(ordner) / "eingabe.pdf"
        quelle.write_bytes(daten)
        try:
            ergebnis = subprocess.run(
                [werkzeug, "-layout", "-enc", "UTF-8", str(quelle), "-"],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as fehler:
            _log.warning("pdftotext fehlgeschlagen", extra={"fehlerart": type(fehler).__name__})
            return None
    if ergebnis.returncode != 0:
        return None
    text = ergebnis.stdout.decode("utf-8", errors="replace")
    seiten = text.count("\f") or 1
    return Extraktion("pdftotext", text, seiten, guete_bewerten(text))


def text_gewinnen(daten: bytes) -> Extraktion:
    """Führt beide Pfade aus und nimmt den mit der höheren Güte."""
    kandidaten = [k for k in (_mit_pdfplumber(daten), _mit_pdftotext(daten)) if k is not None]
    if not kandidaten:
        return Extraktion("keiner", "", 0, 0.0)
    bester = max(kandidaten, key=lambda k: k.guete)
    _log.info(
        "Textgewinnung",
        extra={
            "gewaehlt": bester.pfad,
            "guete": bester.guete,
            "kandidaten": {k.pfad: k.guete for k in kandidaten},
        },
    )
    return bester


def text_aus_bytes(daten: bytes, art: str) -> Extraktion:
    """Einheitlicher Einstieg für PDF, Text und XML."""
    if art == "pdf":
        return text_gewinnen(daten)
    for kodierung in ("utf-8", "cp1252", "latin-1"):
        try:
            text = daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
        return Extraktion(f"dekodiert:{kodierung}", text, 1, guete_bewerten(text))
    text = daten.decode("utf-8", errors="replace")
    return Extraktion("dekodiert:ersatz", text, 1, guete_bewerten(text))
