"""Dateiablage mit Mandantenprüfung (Querschnitt 1.4).

Uploads liegen unter ``/data/uploads/<mandant_id>/<uuid>``. Ausgeliefert wird
ausschließlich über einen Endpoint, der die Mandantenzugehörigkeit prüft —
niemals als statischer Pfad. Diese Datei ist die einzige Stelle, die Pfade
zusammensetzt; alles andere arbeitet mit den hier erzeugten Kennungen.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from belegwerk.konfiguration import einstellungen


class AblageFehler(Exception):
    """Zugriff auf eine Datei außerhalb des eigenen Mandantenbereichs."""


@dataclass(frozen=True, slots=True)
class AblageEintrag:
    kennung: uuid.UUID
    pfad: Path
    groesse: int
    sha256: str


def _wurzel(bereich: str) -> Path:
    konfiguration = einstellungen()
    if bereich == "uploads":
        return konfiguration.upload_verzeichnis
    if bereich == "ausgaben":
        return konfiguration.ausgabe_verzeichnis
    raise AblageFehler(f"unbekannter Ablagebereich: {bereich}")


def mandantenverzeichnis(mandant_id: uuid.UUID, bereich: str = "uploads") -> Path:
    verzeichnis = _wurzel(bereich) / str(mandant_id)
    verzeichnis.mkdir(parents=True, exist_ok=True)
    return verzeichnis


def speichern(mandant_id: uuid.UUID, inhalt: bytes, bereich: str = "uploads") -> AblageEintrag:
    kennung = uuid.uuid4()
    ziel = mandantenverzeichnis(mandant_id, bereich) / str(kennung)
    ziel.write_bytes(inhalt)
    return AblageEintrag(
        kennung=kennung,
        pfad=ziel,
        groesse=len(inhalt),
        sha256=hashlib.sha256(inhalt).hexdigest(),
    )


def pfad_pruefen(mandant_id: uuid.UUID, pfad: str | Path, bereich: str = "uploads") -> Path:
    """Gibt den Pfad zurück, wenn er zu diesem Mandanten gehört, sonst Fehler.

    Prüft nach Auflösung aller Symlinks und ``..``-Anteile, damit ein aus der
    Datenbank stammender Pfad den Mandantenbereich nicht verlassen kann.
    """
    verzeichnis = mandantenverzeichnis(mandant_id, bereich).resolve()
    kandidat = Path(pfad).resolve()
    if not kandidat.is_relative_to(verzeichnis):
        raise AblageFehler("Datei gehört nicht zu diesem Mandanten")
    return kandidat


def lesen(mandant_id: uuid.UUID, pfad: str | Path, bereich: str = "uploads") -> bytes:
    return pfad_pruefen(mandant_id, pfad, bereich).read_bytes()


def loeschen(mandant_id: uuid.UUID, pfad: str | Path, bereich: str = "uploads") -> bool:
    try:
        ziel = pfad_pruefen(mandant_id, pfad, bereich)
    except AblageFehler:
        return False
    if ziel.exists():
        ziel.unlink()
        return True
    return False


def mandant_vollstaendig_loeschen(mandant_id: uuid.UUID) -> int:
    """Entfernt alle Dateien eines Mandanten (Kontolöschung, Querschnitt 7.3)."""
    entfernt = 0
    for bereich in ("uploads", "ausgaben"):
        verzeichnis = _wurzel(bereich) / str(mandant_id)
        if verzeichnis.exists():
            entfernt += sum(1 for _ in verzeichnis.rglob("*") if _.is_file())
            shutil.rmtree(verzeichnis)
    return entfernt
