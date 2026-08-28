"""Rate-Limit auf Anmeldung, Passwortrücksetzung und Upload (Querschnitt 8.3).

Gleitendes Fenster im Prozessspeicher. Bei einem Anwendungscontainer ist das
ausreichend und hat keine weitere Abhängigkeit; bei mehreren Replicas müsste
der Zähler in die Datenbank wandern. Der Schlüssel ist gehasht, damit keine
IP-Adresse im Speicher steht.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass


class ZuVieleVersuche(Exception):
    def __init__(self, wartezeit_sekunden: int) -> None:
        minuten = max(1, round(wartezeit_sekunden / 60))
        super().__init__(
            "Zu viele Versuche. Zum Schutz des Kontos ist dieser Vorgang für "
            f"etwa {minuten} Minuten gesperrt."
        )
        self.wartezeit_sekunden = wartezeit_sekunden


@dataclass(frozen=True, slots=True)
class Grenze:
    versuche: int
    fenster_sekunden: int


ANMELDUNG = Grenze(versuche=8, fenster_sekunden=15 * 60)
PASSWORT_ZURUECK = Grenze(versuche=5, fenster_sekunden=60 * 60)
UPLOAD = Grenze(versuche=60, fenster_sekunden=60 * 60)
OEFFENTLICHE_PRUEFUNG = Grenze(versuche=5, fenster_sekunden=60 * 60)

_zaehler: dict[str, deque[float]] = defaultdict(deque)


def _schluessel(bereich: str, kennung: str) -> str:
    return f"{bereich}:{hashlib.sha256(kennung.encode()).hexdigest()[:32]}"


def pruefen_und_zaehlen(bereich: str, kennung: str, grenze: Grenze) -> None:
    """Zählt einen Versuch. Wirft ``ZuVieleVersuche``, wenn die Grenze fällt."""
    jetzt = time.monotonic()
    eintraege = _zaehler[_schluessel(bereich, kennung)]
    while eintraege and jetzt - eintraege[0] > grenze.fenster_sekunden:
        eintraege.popleft()
    if len(eintraege) >= grenze.versuche:
        rest = grenze.fenster_sekunden - (jetzt - eintraege[0])
        raise ZuVieleVersuche(int(rest))
    eintraege.append(jetzt)


def zuruecksetzen(bereich: str, kennung: str) -> None:
    """Nach erfolgreicher Anmeldung zählt der Fehlversuchsspeicher nicht weiter."""
    _zaehler.pop(_schluessel(bereich, kennung), None)


def alles_zuruecksetzen() -> None:
    _zaehler.clear()
