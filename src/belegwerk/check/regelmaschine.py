"""Regelkatalog laden und ausführen (Check-Todo 2.2 und 2.4).

Jeder Befund trägt seinen Fundort im Dokument — Seitenzahl und Textausschnitt.
Ohne ihn kann der Sachverständige den Befund nicht überprüfen, und ein Befund,
den man nicht überprüfen kann, wird weggeklickt.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from belegwerk.check.ausdruck import AusdruckFehler, Knoten, auswerten, uebersetzen
from belegwerk.check.extraktion import Extraktionsergebnis, Fundstelle
from belegwerk.kern.formate import datum, geld, zahl

REGELDATEI = Path(__file__).parent / "regeln.yaml"


class Schwere(str, enum.Enum):
    FEHLER = "fehler"
    WARNUNG = "warnung"
    HINWEIS = "hinweis"

    @property
    def beschriftung(self) -> str:
        return {"fehler": "Fehler", "warnung": "Warnung", "hinweis": "Hinweis"}[self.value]

    @property
    def rang(self) -> int:
        return {"fehler": 0, "warnung": 1, "hinweis": 2}[self.value]


class RegelFehler(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Regel:
    id: str
    nummer: int
    schwere: Schwere
    titel: str
    wenn: str
    meldung: str
    felder: tuple[str, ...]
    baum: Knoten
    mandant_eigen: bool = False

    @property
    def gepruefte_felder(self) -> tuple[str, ...]:
        return self.felder


@dataclass(frozen=True, slots=True)
class Befund:
    regel_id: str
    nummer: int
    schwere: Schwere
    titel: str
    meldung: str
    feldwerte: dict[str, str]
    fundstelle: Fundstelle | None


@dataclass(frozen=True, slots=True)
class Pruefergebnis:
    befunde: tuple[Befund, ...]
    geprueft: int
    nicht_entscheidbar: tuple[str, ...]
    fehlende_pflichtfelder: tuple[str, ...]

    @property
    def anzahl_fehler(self) -> int:
        return sum(1 for b in self.befunde if b.schwere is Schwere.FEHLER)

    @property
    def ohne_befund(self) -> bool:
        return not self.befunde

    def nach_schwere(self) -> dict[Schwere, list[Befund]]:
        gruppen: dict[Schwere, list[Befund]] = {s: [] for s in Schwere}
        for befund in self.befunde:
            gruppen[befund.schwere].append(befund)
        return gruppen


def regel_aus_dict(eintrag: dict[str, Any], mandant_eigen: bool = False) -> Regel:
    for pflicht in ("id", "schwere", "wenn", "meldung"):
        if not eintrag.get(pflicht):
            raise RegelFehler(f"Der Regel fehlt die Angabe „{pflicht}“.")
    schwere_roh = str(eintrag["schwere"]).lower()
    if schwere_roh not in {s.value for s in Schwere}:
        raise RegelFehler(
            f"„{schwere_roh}“ ist kein Schweregrad. Zulässig: fehler, warnung, hinweis."
        )
    try:
        baum = uebersetzen(str(eintrag["wenn"]))
    except AusdruckFehler as fehler:
        raise RegelFehler(f"Regel {eintrag['id']}: {fehler}") from fehler
    return Regel(
        id=str(eintrag["id"]),
        nummer=int(eintrag.get("nummer", 0)),
        schwere=Schwere(schwere_roh),
        titel=str(eintrag.get("titel", eintrag["id"])),
        wenn=str(eintrag["wenn"]),
        meldung=" ".join(str(eintrag["meldung"]).split()),
        felder=tuple(eintrag.get("felder", ())),
        baum=baum,
        mandant_eigen=mandant_eigen,
    )


@lru_cache(maxsize=1)
def startkatalog() -> tuple[Regel, ...]:
    daten = yaml.safe_load(REGELDATEI.read_text(encoding="utf-8"))
    regeln = tuple(regel_aus_dict(eintrag) for eintrag in daten.get("regeln", []))
    if len(regeln) < 20:
        raise RegelFehler(f"Der Startkatalog hat nur {len(regeln)} Regeln, erwartet sind 20.")
    kennungen = [r.id for r in regeln]
    if len(set(kennungen)) != len(kennungen):
        raise RegelFehler("Doppelte Regelkennung im Startkatalog.")
    return regeln


def _darstellen(wert: Any) -> str:
    if wert is None:
        return "nicht gefunden"
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    if isinstance(wert, Decimal):
        return geld(wert) if abs(wert) >= 100 else zahl(wert)
    if hasattr(wert, "isoformat"):
        return datum(wert)
    return str(wert)


def _fundstelle_waehlen(
    regel: Regel, extraktion: Extraktionsergebnis
) -> Fundstelle | None:
    """Die erste Fundstelle eines beteiligten Feldes — dorthin schaut der Prüfer."""
    for feld in regel.felder:
        stelle = extraktion.fundstelle(feld)
        if stelle is not None:
            return stelle
    return None


def ausfuehren(
    extraktion: Extraktionsergebnis,
    felder: dict[str, Any],
    regeln: tuple[Regel, ...] | None = None,
) -> Pruefergebnis:
    """Führt den Katalog gegen die abgeleiteten Felder aus."""
    aktive = regeln if regeln is not None else startkatalog()
    befunde: list[Befund] = []
    unentscheidbar: list[str] = []

    for regel in aktive:
        try:
            ergebnis = auswerten(regel.baum, felder)
        except AusdruckFehler:
            unentscheidbar.append(regel.id)
            continue
        if ergebnis is None:
            unentscheidbar.append(regel.id)
            continue
        if not _wahr(ergebnis):
            continue
        befunde.append(
            Befund(
                regel_id=regel.id,
                nummer=regel.nummer,
                schwere=regel.schwere,
                titel=regel.titel,
                meldung=regel.meldung,
                feldwerte={name: _darstellen(felder.get(name)) for name in regel.felder},
                fundstelle=_fundstelle_waehlen(regel, extraktion),
            )
        )

    befunde.sort(key=lambda b: (b.schwere.rang, b.nummer))
    return Pruefergebnis(
        befunde=tuple(befunde),
        geprueft=len(aktive),
        nicht_entscheidbar=tuple(unentscheidbar),
        fehlende_pflichtfelder=extraktion.fehlende_pflichtfelder,
    )


def _wahr(wert: Any) -> bool:
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, Decimal):
        return wert != 0
    if isinstance(wert, str):
        return bool(wert)
    return wert is not None
