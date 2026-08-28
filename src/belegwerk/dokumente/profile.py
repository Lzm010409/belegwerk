"""Adapterprofile als YAML statt verstreuter Regexe im Code.

Warum als Daten und nicht als Code: Kalkulations- und Prüfbericht-Layouts
unterscheiden sich je Absender und ändern sich, ohne dass jemand Bescheid sagt.
Ein neues Layout muss ein Profil sein, kein Programmierauftrag. Dieselbe
Überlegung wie beim Feldkatalog von Check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from belegwerk.dokumente.modell import PositionsArt, Quelle

PROFILVERZEICHNIS = Path(__file__).parent / "profile"


class ProfilFehler(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Signatur:
    muster: re.Pattern[str]
    gewicht: int


@dataclass(frozen=True, slots=True)
class Abschnitt:
    """Ein Positionsblock im Dokument, etwa „Ersatzteile"."""

    art: PositionsArt
    beginn: re.Pattern[str]
    ende: re.Pattern[str] | None
    zeilenmuster: tuple[re.Pattern[str], ...]
    optional: bool = False


@dataclass(frozen=True, slots=True)
class Profil:
    name: str
    quelle: Quelle
    formate: tuple[str, ...]
    signaturen: tuple[Signatur, ...]
    mindestpunkte: int
    felder: dict[str, tuple[re.Pattern[str], ...]]
    saetze: dict[str, tuple[re.Pattern[str], ...]]
    summen: dict[str, tuple[re.Pattern[str], ...]]
    abschnitte: tuple[Abschnitt, ...]
    adapternamen: dict[str, str] = field(default_factory=dict)
    pflichtfelder: tuple[str, ...] = ()
    hinweise: tuple[str, ...] = field(default=())

    def adaptername(self, quellformat: str) -> str:
        """Der nach außen berichtete Adaptername — je Quellformat einer."""
        return self.adapternamen.get(quellformat, self.name)

    def punkte(self, text: str) -> int:
        """Wie deutlich spricht dieser Text für dieses Profil?"""
        return sum(s.gewicht for s in self.signaturen if s.muster.search(text))

    def passt(self, text: str) -> bool:
        return self.punkte(text) >= self.mindestpunkte


def _muster(werte: Any, name: str) -> tuple[re.Pattern[str], ...]:
    if werte is None:
        return ()
    if isinstance(werte, str):
        werte = [werte]
    if not isinstance(werte, list):
        raise ProfilFehler(f"{name}: Liste von Mustern erwartet, gefunden {type(werte).__name__}")
    gebaut: list[re.Pattern[str]] = []
    for eintrag in werte:
        try:
            gebaut.append(re.compile(eintrag, re.IGNORECASE | re.MULTILINE))
        except re.error as fehler:
            raise ProfilFehler(f"{name}: ungültiger regulärer Ausdruck „{eintrag}“ ({fehler})") from fehler
    return tuple(gebaut)


def profil_aus_dict(daten: dict[str, Any], herkunft: str) -> Profil:
    fehlend = {"name", "quelle", "formate"} - set(daten)
    if fehlend:
        raise ProfilFehler(f"{herkunft}: es fehlen die Angaben {sorted(fehlend)}")

    signaturen = tuple(
        Signatur(muster=_muster(eintrag["muster"], f"{herkunft}.signatur")[0], gewicht=int(eintrag.get("gewicht", 1)))
        for eintrag in daten.get("erkennung", {}).get("signaturen", [])
    )
    abschnitte = tuple(
        Abschnitt(
            art=PositionsArt(eintrag["art"]),
            beginn=_muster(eintrag["beginn"], f"{herkunft}.abschnitt.beginn")[0],
            ende=(_muster(eintrag["ende"], f"{herkunft}.abschnitt.ende")[0] if eintrag.get("ende") else None),
            zeilenmuster=_muster(eintrag["zeile"], f"{herkunft}.abschnitt.zeile"),
            optional=bool(eintrag.get("optional", False)),
        )
        for eintrag in daten.get("abschnitte", [])
    )
    return Profil(
        name=str(daten["name"]),
        quelle=Quelle(daten["quelle"]),
        formate=tuple(daten["formate"]),
        signaturen=signaturen,
        mindestpunkte=int(daten.get("erkennung", {}).get("mindestpunkte", 1)),
        felder={
            schluessel: _muster(wert, f"{herkunft}.felder.{schluessel}")
            for schluessel, wert in (daten.get("felder") or {}).items()
        },
        saetze={
            schluessel: _muster(wert, f"{herkunft}.saetze.{schluessel}")
            for schluessel, wert in (daten.get("saetze") or {}).items()
        },
        summen={
            schluessel: _muster(wert, f"{herkunft}.summen.{schluessel}")
            for schluessel, wert in (daten.get("summen") or {}).items()
        },
        abschnitte=abschnitte,
        adapternamen={str(k): str(v) for k, v in (daten.get("adapter") or {}).items()},
        pflichtfelder=tuple(daten.get("pflichtfelder", ())),
        hinweise=tuple(daten.get("hinweise", ())),
    )


@lru_cache(maxsize=1)
def alle_profile() -> tuple[Profil, ...]:
    profile: list[Profil] = []
    for datei in sorted(PROFILVERZEICHNIS.glob("*.yaml")):
        daten = yaml.safe_load(datei.read_text(encoding="utf-8"))
        profile.append(profil_aus_dict(daten, datei.name))
    if not profile:
        raise ProfilFehler(f"keine Profile in {PROFILVERZEICHNIS}")
    return tuple(profile)


def profil(name: str) -> Profil:
    for eintrag in alle_profile():
        if eintrag.name == name:
            return eintrag
    raise ProfilFehler(f"unbekanntes Profil: {name}")
