"""Labelbasierte Extraktion der Kennzahlen (Check-Todo 1.2 bis 1.5).

Vorgehen je Feld: Label suchen, Wert in Leserichtung rechts davon oder in den
beiden folgenden Zeilen aufnehmen, in den deklarierten Typ wandeln. Der Fundort
(Seite und Textausschnitt) wird mitgeführt — ohne ihn ist ein Befund für den
Sachverständigen nicht überprüfbar.

Mandantenmuster haben Vorrang vor den globalen Mustern des Katalogs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from belegwerk.kern.formate import zahl_lesen

KATALOGDATEI = Path(__file__).parent / "felder.yaml"

_JA = re.compile(r"\b(ja|vorhanden|festgestellt|liegt vor|bejaht)\b", re.IGNORECASE)
_NEIN = re.compile(r"\b(nein|keine?|nicht|ohne|verneint|nicht festgestellt)\b", re.IGNORECASE)
_GELD = re.compile(
    r"-?\d{1,3}(?:\.\d{3})+,\d+"  # 1.234,56
    r"|-?\d+,\d+"                  # 19,0
    r"|-?\d{1,3}(?:\.\d{3})+"      # 48.320
    r"|-?\d+"                       # 5
)
_DATUM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


class KatalogFehler(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Felddefinition:
    feld: str
    typ: str
    label: str
    label_muster: tuple[re.Pattern[str], ...]
    werte: tuple[str, ...] = ()
    werte_muster: dict[str, tuple[re.Pattern[str], ...]] = field(default_factory=dict)
    pflicht_bei: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Fundstelle:
    seite: int
    zeile: int
    ausschnitt: str


@dataclass(frozen=True, slots=True)
class Feldwert:
    feld: str
    wert: Decimal | str | date | bool | None
    roh: str | None
    fundstelle: Fundstelle | None
    muster: str | None

    @property
    def gefunden(self) -> bool:
        return self.wert is not None


@dataclass(slots=True)
class Extraktionsergebnis:
    werte: dict[str, Feldwert]
    fehlende_pflichtfelder: tuple[str, ...]
    gutachtenart: str | None
    seiten: int
    konfidenz: float

    def als_felder(self) -> dict[str, Any]:
        """Die Umgebung für die Regelmaschine."""
        return {name: eintrag.wert for name, eintrag in self.werte.items()}

    def fundstelle(self, feld: str) -> Fundstelle | None:
        eintrag = self.werte.get(feld)
        return eintrag.fundstelle if eintrag else None


def _kompilieren(muster: list[str] | None, wo: str) -> tuple[re.Pattern[str], ...]:
    gebaut: list[re.Pattern[str]] = []
    for eintrag in muster or []:
        try:
            gebaut.append(re.compile(eintrag, re.IGNORECASE))
        except re.error as fehler:
            raise KatalogFehler(f"{wo}: ungültiges Muster „{eintrag}“ ({fehler})") from fehler
    return tuple(gebaut)


def katalog_aus_dict(daten: dict[str, Any]) -> tuple[Felddefinition, ...]:
    felder: list[Felddefinition] = []
    for eintrag in daten.get("felder", []):
        name = eintrag.get("feld")
        if not name:
            raise KatalogFehler("Ein Eintrag ohne „feld“ ist nicht verwertbar.")
        typ = eintrag.get("typ", "text")
        if typ not in {"geld", "zahl", "datum", "text", "auswahl", "ja_nein", "vorhandensein"}:
            raise KatalogFehler(f"{name}: unbekannter Typ „{typ}“.")
        felder.append(
            Felddefinition(
                feld=name,
                typ=typ,
                label=eintrag.get("label", name),
                label_muster=_kompilieren(eintrag.get("label_muster"), name),
                werte=tuple(eintrag.get("werte", ())),
                werte_muster={
                    schluessel: _kompilieren(wert, f"{name}.{schluessel}")
                    for schluessel, wert in (eintrag.get("werte_muster") or {}).items()
                },
                pflicht_bei=tuple(eintrag.get("pflicht_bei", ())),
            )
        )
    if not felder:
        raise KatalogFehler("Der Feldkatalog enthält keine Felder.")
    return tuple(felder)


@lru_cache(maxsize=1)
def globaler_katalog() -> tuple[Felddefinition, ...]:
    return katalog_aus_dict(yaml.safe_load(KATALOGDATEI.read_text(encoding="utf-8")))


def katalog_mit_mandantenmustern(
    zusatz: dict[str, list[str]] | None,
) -> tuple[Felddefinition, ...]:
    """Mandantenmuster stehen vor den globalen (Todo 1.4)."""
    if not zusatz:
        return globaler_katalog()
    ergebnis: list[Felddefinition] = []
    for definition in globaler_katalog():
        eigene = zusatz.get(definition.feld)
        if not eigene:
            ergebnis.append(definition)
            continue
        ergebnis.append(
            Felddefinition(
                feld=definition.feld,
                typ=definition.typ,
                label=definition.label,
                label_muster=_kompilieren(eigene, f"mandant.{definition.feld}")
                + definition.label_muster,
                werte=definition.werte,
                werte_muster=definition.werte_muster,
                pflicht_bei=definition.pflicht_bei,
            )
        )
    return tuple(ergebnis)


# ---------------------------------------------------------------------------
# Typwandlung
# ---------------------------------------------------------------------------


def _geld(text: str) -> tuple[Decimal | None, str | None]:
    treffer = _GELD.search(text)
    if treffer is None:
        return None, None
    return zahl_lesen(treffer.group()), treffer.group()


def _datum(text: str) -> tuple[date | None, str | None]:
    treffer = _DATUM.search(text)
    if treffer is None:
        return None, None
    tag, monat, jahr = (int(teil) for teil in treffer.groups())
    if jahr < 100:
        jahr += 2000
    try:
        return datetime(jahr, monat, tag).date(), treffer.group()
    except ValueError:
        return None, treffer.group()


def _ja_nein(text: str) -> tuple[bool | None, str | None]:
    # „nicht" und „keine" zuerst: „keine Vorschäden" ist ein Nein, kein Ja.
    nein = _NEIN.search(text)
    ja = _JA.search(text)
    if nein and (not ja or nein.start() < ja.start()):
        return False, nein.group()
    if ja:
        return True, ja.group()
    return None, None


def _auswahl(definition: Felddefinition, umgebung: str) -> tuple[str | None, str | None]:
    for wert in definition.werte:
        for muster in definition.werte_muster.get(wert, ()):  # gepflegte Reihenfolge
            treffer = muster.search(umgebung)
            if treffer:
                return wert, treffer.group()
    return None, None


def _wert_wandeln(
    definition: Felddefinition, rest: str, umgebung: str
) -> tuple[Decimal | str | date | bool | None, str | None]:
    if definition.typ in {"geld", "zahl"}:
        return _geld(rest)
    if definition.typ == "datum":
        return _datum(rest)
    if definition.typ == "ja_nein":
        # Erst rechts vom Label, dann die Umgebung: „Vorschaeden  keine" steht
        # in derselben Zeile, und eine spaetere Zeile darf sie nicht ueberstimmen.
        ja_wert, ja_roh = _ja_nein(rest)
        return (ja_wert, ja_roh) if ja_wert is not None else _ja_nein(umgebung)
    if definition.typ == "auswahl":
        auswahl_wert, auswahl_roh = _auswahl(definition, rest)
        if auswahl_wert is not None:
            return auswahl_wert, auswahl_roh
        return _auswahl(definition, umgebung)
    if definition.typ == "vorhandensein":
        # „Wird das Thema ueberhaupt angesprochen?" — die Formulierung ist frei,
        # deshalb zaehlt allein, dass das Label mit Inhalt dahinter vorkommt.
        inhalt = rest.strip(" :\t.-")
        return (True, inhalt[:120]) if inhalt else (None, None)
    gesaeubert = rest.strip(" :\t.-")
    return (gesaeubert or None), (gesaeubert or None)


# ---------------------------------------------------------------------------
# Extraktion
# ---------------------------------------------------------------------------


def _seitenzuordnung(text: str) -> list[tuple[int, int, str]]:
    """(Seite, Zeilennummer, Zeile) für den gesamten Text."""
    ergebnis: list[tuple[int, int, str]] = []
    seite = 1
    nummer = 0
    for zeile in text.splitlines():
        while "\f" in zeile:
            vor, _, zeile = zeile.partition("\f")
            if vor.strip():
                nummer += 1
                ergebnis.append((seite, nummer, vor))
            seite += 1
        nummer += 1
        ergebnis.append((seite, nummer, zeile))
    return ergebnis


def _feld_suchen(
    definition: Felddefinition, zeilen: list[tuple[int, int, str]]
) -> Feldwert:
    """Sucht das Feld — erst dort, wo der Wert neben dem Label steht.

    Erst im zweiten Durchgang wird ein Wert *unter* dem Label akzeptiert. Ohne
    diese Reihenfolge fängt eine Überschrift wie „2. Schadenhergang und
    Besichtigung" das Label ab und liefert den Wert der nächsten Zeile — also
    das Schadendatum als Besichtigungsdatum.
    """
    for mit_folgezeilen in (False, True):
        for muster in definition.label_muster:
            for stelle, (seite, nummer, zeile) in enumerate(zeilen):
                treffer = muster.search(zeile)
                if treffer is None:
                    continue
                rest = zeile[treffer.end() :]
                umgebung = " ".join(inhalt for _, _, inhalt in zeilen[stelle : stelle + 3])
                wert, roh = _wert_wandeln(definition, rest, umgebung)
                if (
                    wert is None
                    and mit_folgezeilen
                    and definition.typ in {"geld", "zahl", "datum"}
                ):
                    for _, _, folgezeile in zeilen[stelle + 1 : stelle + 3]:
                        wert, roh = _wert_wandeln(definition, folgezeile, folgezeile)
                        if wert is not None:
                            break
                if wert is None:
                    continue
                return Feldwert(
                    feld=definition.feld,
                    wert=wert,
                    roh=roh,
                    fundstelle=Fundstelle(
                        seite=seite, zeile=nummer, ausschnitt=zeile.strip()[:200]
                    ),
                    muster=muster.pattern,
                )
    return Feldwert(feld=definition.feld, wert=None, roh=None, fundstelle=None, muster=None)


def extrahieren(
    text: str, mandantenmuster: dict[str, list[str]] | None = None
) -> Extraktionsergebnis:
    katalog = katalog_mit_mandantenmustern(mandantenmuster)
    zeilen = _seitenzuordnung(text)
    seiten = max((seite for seite, _, _ in zeilen), default=1)

    werte = {definition.feld: _feld_suchen(definition, zeilen) for definition in katalog}

    art_wert = werte.get("gutachtenart")
    gutachtenart = art_wert.wert if art_wert and isinstance(art_wert.wert, str) else None

    fehlend = tuple(
        definition.feld
        for definition in katalog
        if definition.pflicht_bei
        and (gutachtenart is None or gutachtenart in definition.pflicht_bei)
        and not werte[definition.feld].gefunden
    )

    pflichtige = [definition for definition in katalog if definition.pflicht_bei]
    konfidenz = (
        round(1 - len(fehlend) / len(pflichtige), 4) if pflichtige else 1.0
    )

    return Extraktionsergebnis(
        werte=werte,
        fehlende_pflichtfelder=fehlend,
        gutachtenart=gutachtenart,
        seiten=seiten,
        konfidenz=konfidenz,
    )
