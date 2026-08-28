"""Optionale LLM-Zuordnung, Matching-Stufe 5 (Delta-Todo 5.3).

Die Leitplanke aus Plattformdatei Abschnitt 8 gilt ohne Ausnahme:

    Zahlen werden nie von einem Sprachmodell erzeugt, geschätzt oder korrigiert.
    Ein LLM darf ausschließlich Text zuordnen, klassifizieren oder formulieren.

Hier wird deshalb ausschließlich *zugeordnet*: das Modell bekommt zwei Listen
von Bezeichnungen und gibt Indexpaare zurück. Beträge, Arbeitswerte und
Prozentsätze verlassen die Anwendung nicht und kommen auch nicht zurück. Die
Antwort wird streng geprüft; alles, was kein gültiges Indexpaar ist, fällt weg.

Der Pfad ist pro Mandant abschaltbar. Ist er aus, greift die Korrekturansicht —
ein Büro, das keine Daten außer Haus geben will, muss das Produkt voll nutzen
können.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx

from belegwerk.dokumente.modell import Position
from belegwerk.konfiguration import einstellungen

_log = logging.getLogger(__name__)

ANWEISUNG = (
    "Du ordnest Positionsbezeichnungen aus zwei Kfz-Schadenkalkulationen einander zu. "
    "Antworte ausschließlich mit JSON der Form {\"paare\": [[index_a, index_b], ...]}. "
    "Ordne nur zu, wenn beide Bezeichnungen dieselbe Arbeit oder dasselbe Bauteil meinen. "
    "Nenne keine Zahlen, keine Beträge und keinen weiteren Text."
)


class LlmNichtVerfuegbar(Exception):
    pass


def _liste(positionen: list[Position]) -> str:
    return "\n".join(f"{nummer}: {p.bezeichnung}" for nummer, p in enumerate(positionen))


def _antwort_auswerten(
    rohtext: str, a: list[Position], b: list[Position]
) -> list[tuple[Position, Position]]:
    """Nimmt nur gültige, eindeutige Indexpaare an."""
    try:
        daten = json.loads(rohtext)
    except json.JSONDecodeError:
        _log.info("LLM-Antwort war kein JSON")
        return []
    roh = daten.get("paare") if isinstance(daten, dict) else None
    if not isinstance(roh, list):
        return []

    vergeben_a: set[int] = set()
    vergeben_b: set[int] = set()
    paare: list[tuple[Position, Position]] = []
    for eintrag in roh:
        if not isinstance(eintrag, list) or len(eintrag) != 2:
            continue
        links, rechts = eintrag
        if not isinstance(links, int) or not isinstance(rechts, int):
            continue
        if not (0 <= links < len(a)) or not (0 <= rechts < len(b)):
            continue
        if links in vergeben_a or rechts in vergeben_b:
            continue
        vergeben_a.add(links)
        vergeben_b.add(rechts)
        paare.append((a[links], b[rechts]))
    return paare


def zuordner(aktiv: bool) -> Callable[[list[Position], list[Position]], list[tuple[Position, Position]]] | None:
    """Gibt einen Zuordner zurück — oder ``None``, wenn der Pfad aus ist."""
    konfiguration = einstellungen()
    if not aktiv or not konfiguration.mistral_api_schluessel:
        return None

    def zuordnen(a: list[Position], b: list[Position]) -> list[tuple[Position, Position]]:
        if not a or not b:
            return []
        inhalt = (
            f"Liste A (eigene Kalkulation):\n{_liste(a)}\n\n"
            f"Liste B (Prüfbericht):\n{_liste(b)}"
        )
        try:
            antwort = httpx.post(
                f"{konfiguration.mistral_basis_url}/chat/completions",
                headers={"Authorization": f"Bearer {konfiguration.mistral_api_schluessel}"},
                json={
                    "model": konfiguration.mistral_modell,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": ANWEISUNG},
                        {"role": "user", "content": inhalt},
                    ],
                },
                timeout=30,
            )
            antwort.raise_for_status()
            rohtext = antwort.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as fehler:
            # Der LLM-Pfad ist eine Zugabe. Faellt er aus, bleibt das Ergebnis
            # gueltig — nur mit mehr einseitigen Positionen.
            _log.warning("LLM-Zuordnung nicht möglich", extra={"fehlerart": type(fehler).__name__})
            return []
        paare = _antwort_auswerten(rohtext, a, b)
        _log.info("LLM-Zuordnung", extra={"vorgeschlagen": len(paare)})
        return paare

    return zuordnen
