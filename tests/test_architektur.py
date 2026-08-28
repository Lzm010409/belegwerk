"""Architekturregeln, die sich still verletzen lassen — deshalb als Test.

1. Kein Modul außerhalb von ``dokumente`` sieht jemals ein PDF
   (Plattformdatei 4.1).
2. Die mandantenumgehende Sitzung wird nur an den Stellen benutzt, die
   mandantenübergreifend arbeiten müssen.
3. Keine ``float`` in Geldpfaden (Definition of Done, Punkt 3).
"""

from __future__ import annotations

import ast
from pathlib import Path

QUELLE = Path(__file__).resolve().parents[1] / "src" / "belegwerk"

PDF_BIBLIOTHEKEN = {"pdfplumber", "pypdf", "fitz", "pdfminer"}

# Diese Stellen dürfen mandantenübergreifend arbeiten und sind einzeln begründet.
ROH_ERLAUBT = {
    "datenbank.py",  # stellt die Funktion bereit
    "kern/anmeldung.py",  # vor der Anmeldung ist kein Mandant bekannt
    "kern/auftraege.py",  # der Arbeiter holt Aufträge aller Mandanten
    "kern/wartung.py",  # Aufbewahrungs- und Löschjobs
    "kern/erststart.py",  # legt den ersten Mandanten an
    "kern/oeffentlich.py",  # Zugangsanfragen und offene Prüfung ohne Konto
    "atlas/pool.py",  # das einzige mandantenübergreifende Fachfeature
}


def _dateien() -> list[Path]:
    return sorted(p for p in QUELLE.rglob("*.py") if "__pycache__" not in str(p))


def _relativ(pfad: Path) -> str:
    return str(pfad.relative_to(QUELLE))


def test_nur_das_dokumentenpaket_kennt_pdf_bibliotheken() -> None:
    verstoesse: list[str] = []
    for datei in _dateien():
        relativ = _relativ(datei)
        if relativ.startswith("dokumente/"):
            continue
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                namen = {alias.name.split(".")[0] for alias in knoten.names}
            elif isinstance(knoten, ast.ImportFrom):
                namen = {(knoten.module or "").split(".")[0]}
            else:
                continue
            if namen & PDF_BIBLIOTHEKEN:
                verstoesse.append(f"{relativ}: {sorted(namen & PDF_BIBLIOTHEKEN)}")
    assert not verstoesse, (
        "PDF-Bibliotheken gehören ausschließlich in belegwerk/dokumente: " + "; ".join(verstoesse)
    )


def _benutzt_namen(datei: Path, gesucht: str) -> bool:
    """Ob der Name tatsächlich verwendet wird — Erwähnungen im Text zählen nicht."""
    baum = ast.parse(datei.read_text(encoding="utf-8"))
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Name) and knoten.id == gesucht:
            return True
        if isinstance(knoten, ast.Attribute) and knoten.attr == gesucht:
            return True
        if isinstance(knoten, ast.ImportFrom) and any(
            alias.name == gesucht for alias in knoten.names
        ):
            return True
    return False


def test_rohe_sitzung_nur_an_begruendeten_stellen() -> None:
    verstoesse = [
        _relativ(datei)
        for datei in _dateien()
        if _benutzt_namen(datei, "rohe_sitzung") and _relativ(datei) not in ROH_ERLAUBT
    ]
    assert not verstoesse, (
        "rohe_sitzung umgeht die Mandantentrennung und ist hier nicht vorgesehen: "
        + ", ".join(verstoesse)
    )


def test_keine_float_umwandlung_in_geldpfaden() -> None:
    """``float(...)`` auf einem Betrag ist der Weg, wie Cent verschwinden."""
    verdaechtig: list[str] = []
    for datei in _dateien():
        for nummer, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), start=1):
            if "float(" not in zeile:
                continue
            klein = zeile.lower()
            if any(wort in klein for wort in ("betrag", "summe", "preis", "satz", "euro", "geld")):
                verdaechtig.append(f"{_relativ(datei)}:{nummer}")
    assert not verdaechtig, "float in einem Geldpfad: " + ", ".join(verdaechtig)


def test_modellregister_kennt_alle_modellmodule() -> None:
    """Fehlt ein Modul im Register, fehlen seine Tabellen in Migration und Test."""
    import belegwerk.modellregister as register

    quelltext = Path(register.__file__).read_text(encoding="utf-8")
    for datei in _dateien():
        if datei.name != "modelle.py":
            continue
        modul = _relativ(datei).replace("/", ".").removesuffix(".py")
        assert modul in quelltext, f"belegwerk.{modul} fehlt in modellregister.py"
