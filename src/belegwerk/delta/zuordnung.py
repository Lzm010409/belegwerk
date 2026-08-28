"""Positionsabgleich: die Matching-Kaskade (Delta-Briefing 2.1).

Deterministisch, in fester Reihenfolge. Erster Treffer gewinnt, jede Stufe
vermerkt ihre Herkunft im Ergebnis:

===== ====================================================== ==========
Stufe Kriterium                                              Konfidenz
===== ====================================================== ==========
1     Teilenummer identisch                                       1,00
2     Laufnummer identisch **und** Betrag identisch               0,98
3     Bezeichnung nach Normalisierung identisch                   0,95
4     Bezeichnung Token-Ähnlichkeit ≥ 0,85 (rapidfuzz)            0,80
5     LLM-Zuordnung (optional, abschaltbar)                       0,60
—     kein Treffer → „nur in A" bzw. „nur in B"
===== ====================================================== ==========

Die Zuordnung ist eineindeutig: eine Position aus A wird höchstens einer
Position aus B zugeordnet und umgekehrt. Ohne diese Bedingung erzeugt eine
Kalkulation mit vier gleich benannten Beilackierungen vier Scheintreffer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from belegwerk.dokumente.modell import Position

TABELLE = Path(__file__).parent / "normalisierung.yaml"
AEHNLICHKEIT_SCHWELLE = 85.0
# Wenn beide Seiten eine Teilenummer tragen und diese verschieden sind, ist das
# ein Argument gegen Gleichheit. „Scheinwerfer links" und „Nebelscheinwerfer
# links" liegen bei 88 — ohne diese Verschaerfung waere das ein Scheintreffer.
AEHNLICHKEIT_SCHWELLE_STRENG = 92.0

KONFIDENZ = {1: 1.00, 2: 0.98, 3: 0.95, 4: 0.80, 5: 0.60}


@dataclass(frozen=True, slots=True)
class Paar:
    """Eine zugeordnete oder einseitige Position."""

    a: Position | None
    b: Position | None
    stufe: int | None
    konfidenz: float

    @property
    def nur_in_a(self) -> bool:
        return self.b is None

    @property
    def nur_in_b(self) -> bool:
        return self.a is None

    @property
    def zugeordnet(self) -> bool:
        return self.a is not None and self.b is not None

    @property
    def herkunft(self) -> str:
        if self.stufe is None:
            return "kein Treffer"
        return {
            1: "Teilenummer identisch",
            2: "Laufnummer und Betrag identisch",
            3: "Bezeichnung nach Normalisierung identisch",
            4: "Bezeichnung ähnlich",
            5: "Sprachmodell",
        }[self.stufe]


@lru_cache(maxsize=1)
def _tabelle() -> tuple[dict[str, str], tuple[tuple[str, str], ...], frozenset[str]]:
    """Wortersetzungen, Mehrzeichenersetzungen und Fuellwoerter.

    Kuerzel wie ``a/e`` oder ``aus-/einbau`` enthalten Zeichen, an denen der
    Zerleger trennt. Sie werden deshalb vorher als Zeichenkette ersetzt, nach
    Laenge absteigend, damit ``aus-/einbau`` vor ``a/e`` greift.
    """
    daten = yaml.safe_load(TABELLE.read_text(encoding="utf-8"))
    woerter: dict[str, str] = {}
    phrasen: list[tuple[str, str]] = []
    for schluessel, wert in (daten.get("abkuerzungen") or {}).items():
        kurz = str(schluessel).lower()
        lang = str(wert).lower()
        if re.search(r"[^a-z0-9]", kurz):
            phrasen.append((kurz, lang))
            woerter.setdefault(re.sub(r"[^a-z0-9]", "", kurz), lang)
        else:
            woerter[kurz] = lang
    phrasen.sort(key=lambda eintrag: -len(eintrag[0]))
    fuell = frozenset(str(w).lower() for w in (daten.get("fuellwoerter") or []))
    return woerter, tuple(phrasen), fuell


def _umlaute(text: str) -> str:
    ersetzungen = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for zeichen, ersatz in ersetzungen.items():
        text = text.replace(zeichen, ersatz)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


_TRENNER = re.compile(r"[^a-z0-9]+")


def wortmenge(bezeichnung: str) -> tuple[str, ...]:
    """Zerlegt eine Bezeichnung in normalisierte, sortierte Wörter."""
    abkuerzungen, phrasen, fuell = _tabelle()
    roh = _umlaute(bezeichnung.lower())
    for kurz, lang in phrasen:
        roh = roh.replace(kurz, f" {lang} ")
    woerter: list[str] = []
    for wort in _TRENNER.split(roh):
        if not wort:
            continue
        ersetzt = abkuerzungen.get(wort, wort)
        if ersetzt in fuell:
            continue
        woerter.append(ersetzt)
    return tuple(sorted(woerter))


def normalisieren(bezeichnung: str) -> str:
    """Vergleichsform einer Bezeichnung."""
    return " ".join(wortmenge(bezeichnung))


def aehnlichkeit(links: str, rechts: str) -> float:
    """Token-Ähnlichkeit in Prozent, auf den normalisierten Formen."""
    return float(fuzz.token_sort_ratio(normalisieren(links), normalisieren(rechts)))


def _teilenummer_schluessel(position: Position) -> str | None:
    if not position.teilenummer:
        return None
    gesaeubert = re.sub(r"[^A-Z0-9]", "", position.teilenummer.upper())
    return gesaeubert or None


def _stufe1(a: list[Position], b: list[Position]) -> list[tuple[Position, Position]]:
    nach_nummer: dict[str, list[Position]] = {}
    for position in b:
        schluessel = _teilenummer_schluessel(position)
        if schluessel:
            nach_nummer.setdefault(schluessel, []).append(position)
    paare: list[tuple[Position, Position]] = []
    for position in a:
        schluessel = _teilenummer_schluessel(position)
        if schluessel and nach_nummer.get(schluessel):
            paare.append((position, nach_nummer[schluessel].pop(0)))
    return paare


def _stufe2(a: list[Position], b: list[Position]) -> list[tuple[Position, Position]]:
    offen = list(b)
    paare: list[tuple[Position, Position]] = []
    for position in a:
        for kandidat in offen:
            if kandidat.laufnummer == position.laufnummer and kandidat.betrag == position.betrag:
                paare.append((position, kandidat))
                offen.remove(kandidat)
                break
    return paare


def _stufe3(a: list[Position], b: list[Position]) -> list[tuple[Position, Position]]:
    offen = list(b)
    paare: list[tuple[Position, Position]] = []
    for position in a:
        schluessel = wortmenge(position.bezeichnung)
        for kandidat in offen:
            if wortmenge(kandidat.bezeichnung) == schluessel:
                paare.append((position, kandidat))
                offen.remove(kandidat)
                break
    return paare


def _schwelle(links: Position, rechts: Position) -> float:
    nummer_links = _teilenummer_schluessel(links)
    nummer_rechts = _teilenummer_schluessel(rechts)
    if nummer_links and nummer_rechts and nummer_links != nummer_rechts:
        return AEHNLICHKEIT_SCHWELLE_STRENG
    return AEHNLICHKEIT_SCHWELLE


def _stufe4(a: list[Position], b: list[Position]) -> list[tuple[Position, Position]]:
    """Bestes Paar zuerst — sonst nimmt eine mittelmäßige Zuordnung die gute weg."""
    kandidaten: list[tuple[float, Position, Position]] = []
    for links in a:
        for rechts in b:
            if links.art is not rechts.art:
                # Eine Arbeitsposition ist nie dieselbe Sache wie ein Ersatzteil.
                # Der Wechsel von Ersatz auf Instandsetzung wird als eigene
                # Abweichungsklasse erkannt, nicht als Zuordnung.
                continue
            wert = aehnlichkeit(links.bezeichnung, rechts.bezeichnung)
            if wert >= _schwelle(links, rechts):
                kandidaten.append((wert, links, rechts))
    kandidaten.sort(key=lambda eintrag: -eintrag[0])
    vergeben_a: set[int] = set()
    vergeben_b: set[int] = set()
    paare: list[tuple[Position, Position]] = []
    for _, links, rechts in kandidaten:
        if id(links) in vergeben_a or id(rechts) in vergeben_b:
            continue
        vergeben_a.add(id(links))
        vergeben_b.add(id(rechts))
        paare.append((links, rechts))
    return paare


def zuordnen(
    a: list[Position],
    b: list[Position],
    llm_zuordner: Any = None,
) -> list[Paar]:
    """Führt die Kaskade aus und liefert alle Paare, auch die einseitigen."""
    offen_a = list(a)
    offen_b = list(b)
    ergebnis: list[Paar] = []

    stufen = [(1, _stufe1), (2, _stufe2), (3, _stufe3), (4, _stufe4)]
    for stufe, verfahren in stufen:
        for links, rechts in verfahren(offen_a, offen_b):
            ergebnis.append(Paar(a=links, b=rechts, stufe=stufe, konfidenz=KONFIDENZ[stufe]))
            offen_a.remove(links)
            offen_b.remove(rechts)

    if llm_zuordner is not None and offen_a and offen_b:
        for links, rechts in llm_zuordner(offen_a, offen_b):
            if links in offen_a and rechts in offen_b:
                ergebnis.append(Paar(a=links, b=rechts, stufe=5, konfidenz=KONFIDENZ[5]))
                offen_a.remove(links)
                offen_b.remove(rechts)

    ergebnis += [Paar(a=links, b=None, stufe=None, konfidenz=0.0) for links in offen_a]
    ergebnis += [Paar(a=None, b=rechts, stufe=None, konfidenz=0.0) for rechts in offen_b]

    def sortierschluessel(paar: Paar) -> tuple[int, Decimal]:
        position = paar.a or paar.b
        assert position is not None
        return position.laufnummer, -position.betrag

    ergebnis.sort(key=sortierschluessel)
    return ergebnis
