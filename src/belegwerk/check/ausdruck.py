"""Sicherer Ausdrucksauswerter für den Regelkatalog (Check-Todo 2.1).

**Kein ``eval``.** Eine kleine, geschlossene Grammatik mit eigenem Parser:
Vergleiche, ``und``/``oder``/``nicht``, Grundrechenarten, Prozentrechnung sowie
``vorhanden``/``fehlt``. Alles andere ist ein Syntaxfehler — auch dann, wenn es
gültiges Python wäre.

Dreiwertige Logik
-----------------
Ein Vergleich, an dem ein nicht gefundenes Feld beteiligt ist, ergibt weder
wahr noch falsch, sondern ``None`` (unbekannt). Eine Regel mit unbekanntem
Ergebnis meldet **nichts**. Das ist der Unterschied zwischen „das Gutachten hat
einen Widerspruch" und „ein Wert war nicht auslesbar" — die zweite Aussage
gehört in die Extraktionsmeldung, nicht in einen Befund.

Grammatik
---------
::

    ausdruck   := oder
    oder       := und { 'oder' und }
    und        := nicht { 'und' nicht }
    nicht      := 'nicht' nicht | vergleich
    vergleich  := summe [ ('='|'=='|'!='|'<>'|'<'|'<='|'>'|'>=') summe ]
    summe      := produkt { ('+'|'-') produkt }
    produkt    := prozent { ('*'|'/') prozent }
    prozent    := unaer [ '%' 'von' unaer ]
    unaer      := '-' unaer | primaer
    primaer    := ZAHL | TEXT | BEZEICHNER | 'wahr' | 'falsch'
                | 'vorhanden' '(' BEZEICHNER ')' | 'fehlt' '(' BEZEICHNER ')'
                | '(' ausdruck ')'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Union

Wert = Union[Decimal, str, bool, date, None]


class AusdruckFehler(Exception):
    """Syntax- oder Auswertungsfehler. Die Meldung nennt die Stelle."""


# ---------------------------------------------------------------------------
# Zerlegung
# ---------------------------------------------------------------------------

SCHLUESSELWOERTER = frozenset(
    {"und", "oder", "nicht", "von", "vorhanden", "fehlt", "wahr", "falsch"}
)

_MARKEN = [
    ("leer", r"\s+"),
    ("zahl", r"\d+(?:\.\d{3})*,\d+|\d+(?:\.\d+)?"),
    ("text", r"'[^']*'|\"[^\"]*\""),
    ("name", r"[A-Za-zÄÖÜäöüß_][A-Za-zÄÖÜäöüß0-9_]*"),
    ("operator", r"<=|>=|==|!=|<>|[<>=+\-*/%()]"),
]
_MARKENMUSTER = re.compile("|".join(f"(?P<{name}>{muster})" for name, muster in _MARKEN))


@dataclass(frozen=True, slots=True)
class Marke:
    art: str
    text: str
    stelle: int


def zerlegen(quelle: str) -> list[Marke]:
    marken: list[Marke] = []
    stelle = 0
    while stelle < len(quelle):
        treffer = _MARKENMUSTER.match(quelle, stelle)
        if treffer is None:
            raise AusdruckFehler(
                f"Unerwartetes Zeichen „{quelle[stelle]}“ an Stelle {stelle + 1}. "
                "Erlaubt sind Namen, Zahlen, Vergleiche und die Wörter und/oder/nicht."
            )
        art = treffer.lastgroup or ""
        text = treffer.group()
        stelle = treffer.end()
        if art == "leer":
            continue
        if art == "name" and text.lower() in SCHLUESSELWOERTER:
            art = text.lower()
        marken.append(Marke(art, text, treffer.start()))
    return marken


# ---------------------------------------------------------------------------
# Syntaxbaum
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Konstante:
    wert: Wert


@dataclass(frozen=True, slots=True)
class Feld:
    name: str


@dataclass(frozen=True, slots=True)
class Vorhanden:
    name: str
    verneint: bool


@dataclass(frozen=True, slots=True)
class Rechnung:
    operator: str
    links: "Knoten"
    rechts: "Knoten"


@dataclass(frozen=True, slots=True)
class Vergleich:
    operator: str
    links: "Knoten"
    rechts: "Knoten"


@dataclass(frozen=True, slots=True)
class Verknuepfung:
    operator: str  # 'und' | 'oder'
    links: "Knoten"
    rechts: "Knoten"


@dataclass(frozen=True, slots=True)
class Verneinung:
    inhalt: "Knoten"


@dataclass(frozen=True, slots=True)
class ProzentVon:
    anteil: "Knoten"
    grundwert: "Knoten"


Knoten = Union[
    Konstante, Feld, Vorhanden, Rechnung, Vergleich, Verknuepfung, Verneinung, ProzentVon
]


# ---------------------------------------------------------------------------
# Parser (rekursiver Abstieg)
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, marken: list[Marke], quelle: str) -> None:
        self.marken = marken
        self.quelle = quelle
        self.stelle = 0

    def _schau(self) -> Marke | None:
        return self.marken[self.stelle] if self.stelle < len(self.marken) else None

    def _nimm(self) -> Marke:
        marke = self._schau()
        if marke is None:
            raise AusdruckFehler(f"Der Ausdruck endet unerwartet: „{self.quelle}“")
        self.stelle += 1
        return marke

    def _erwarte(self, text: str) -> Marke:
        marke = self._nimm()
        if marke.text != text and marke.art != text:
            raise AusdruckFehler(
                f"Erwartet wurde „{text}“, gefunden „{marke.text}“ an Stelle {marke.stelle + 1}."
            )
        return marke

    def _ist(self, *arten: str) -> bool:
        marke = self._schau()
        return marke is not None and (marke.art in arten or marke.text in arten)

    def parsen(self) -> Knoten:
        knoten = self.oder()
        rest = self._schau()
        if rest is not None:
            raise AusdruckFehler(
                f"Nach dem Ausdruck steht noch „{rest.text}“ (Stelle {rest.stelle + 1})."
            )
        return knoten

    def oder(self) -> Knoten:
        knoten = self.und()
        while self._ist("oder"):
            self._nimm()
            knoten = Verknuepfung("oder", knoten, self.und())
        return knoten

    def und(self) -> Knoten:
        knoten = self.nicht()
        while self._ist("und"):
            self._nimm()
            knoten = Verknuepfung("und", knoten, self.nicht())
        return knoten

    def nicht(self) -> Knoten:
        if self._ist("nicht"):
            self._nimm()
            return Verneinung(self.nicht())
        return self.vergleich()

    def vergleich(self) -> Knoten:
        links = self.summe()
        marke = self._schau()
        if marke is not None and marke.text in {"=", "==", "!=", "<>", "<", "<=", ">", ">="}:
            self._nimm()
            operator = {"=": "==", "<>": "!="}.get(marke.text, marke.text)
            return Vergleich(operator, links, self.summe())
        return links

    def summe(self) -> Knoten:
        knoten = self.produkt()
        while self._ist("+", "-"):
            operator = self._nimm().text
            knoten = Rechnung(operator, knoten, self.produkt())
        return knoten

    def produkt(self) -> Knoten:
        knoten = self.prozent()
        while self._ist("*", "/"):
            operator = self._nimm().text
            knoten = Rechnung(operator, knoten, self.prozent())
        return knoten

    def prozent(self) -> Knoten:
        knoten = self.unaer()
        if self._ist("%"):
            self._nimm()
            self._erwarte("von")
            return ProzentVon(knoten, self.unaer())
        return knoten

    def unaer(self) -> Knoten:
        if self._ist("-"):
            self._nimm()
            return Rechnung("-", Konstante(Decimal(0)), self.unaer())
        return self.primaer()

    def primaer(self) -> Knoten:
        marke = self._nimm()
        if marke.art == "zahl":
            return Konstante(_zahl_lesen(marke.text))
        if marke.art == "text":
            return Konstante(marke.text[1:-1])
        if marke.art == "wahr":
            return Konstante(True)
        if marke.art == "falsch":
            return Konstante(False)
        if marke.art in {"vorhanden", "fehlt"}:
            self._erwarte("(")
            name = self._nimm()
            if name.art != "name":
                raise AusdruckFehler(
                    f"„{marke.text}" + f"“ erwartet einen Feldnamen, gefunden „{name.text}“."
                )
            self._erwarte(")")
            return Vorhanden(name.text, verneint=marke.art == "fehlt")
        if marke.art == "name":
            return Feld(marke.text)
        if marke.text == "(":
            knoten = self.oder()
            self._erwarte(")")
            return knoten
        raise AusdruckFehler(
            f"„{marke.text}“ ist an Stelle {marke.stelle + 1} nicht zulässig."
        )


def _zahl_lesen(text: str) -> Decimal:
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as fehler:  # pragma: no cover — vom Muster ausgeschlossen
        raise AusdruckFehler(f"„{text}“ ist keine Zahl.") from fehler


def uebersetzen(quelle: str) -> Knoten:
    """Übersetzt einen Regelausdruck in einen Syntaxbaum."""
    if not quelle or not quelle.strip():
        raise AusdruckFehler("Der Ausdruck ist leer.")
    return _Parser(zerlegen(quelle), quelle).parsen()


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------


def _als_zahl(wert: Wert) -> Decimal | None:
    if isinstance(wert, bool) or wert is None:
        return None
    if isinstance(wert, Decimal):
        return wert
    return None


def auswerten(knoten: Knoten, felder: dict[str, Wert]) -> Wert:
    """Wertet den Baum gegen die extrahierten Felder aus. ``None`` = unbekannt."""
    if isinstance(knoten, Konstante):
        return knoten.wert

    if isinstance(knoten, Feld):
        return felder.get(knoten.name)

    if isinstance(knoten, Vorhanden):
        da = felder.get(knoten.name) is not None
        return (not da) if knoten.verneint else da

    if isinstance(knoten, Verneinung):
        inhalt = auswerten(knoten.inhalt, felder)
        if inhalt is None:
            return None
        return not _wahrheit(inhalt)

    if isinstance(knoten, Verknuepfung):
        links = auswerten(knoten.links, felder)
        rechts = auswerten(knoten.rechts, felder)
        return _verknuepfen(knoten.operator, links, rechts)

    if isinstance(knoten, ProzentVon):
        anteil = _als_zahl(auswerten(knoten.anteil, felder))
        grund = _als_zahl(auswerten(knoten.grundwert, felder))
        if anteil is None or grund is None:
            return None
        return grund * anteil / Decimal(100)

    if isinstance(knoten, Rechnung):
        links = _als_zahl(auswerten(knoten.links, felder))
        rechts = _als_zahl(auswerten(knoten.rechts, felder))
        if links is None or rechts is None:
            return None
        try:
            if knoten.operator == "+":
                return links + rechts
            if knoten.operator == "-":
                return links - rechts
            if knoten.operator == "*":
                return links * rechts
            if knoten.operator == "/":
                if rechts == 0:
                    return None
                return links / rechts
        except (InvalidOperation, DivisionByZero) as fehler:
            raise AusdruckFehler(f"Rechenfehler: {fehler}") from fehler
        raise AusdruckFehler(f"Unbekannter Operator: {knoten.operator}")

    if isinstance(knoten, Vergleich):
        return _vergleichen(
            knoten.operator, auswerten(knoten.links, felder), auswerten(knoten.rechts, felder)
        )

    raise AusdruckFehler(f"Unbekannter Knoten: {type(knoten).__name__}")  # pragma: no cover


def _wahrheit(wert: Wert) -> bool:
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, Decimal):
        return wert != 0
    if isinstance(wert, str):
        return bool(wert)
    return wert is not None


def _verknuepfen(operator: str, links: Wert, rechts: Wert) -> bool | None:
    lw = None if links is None else _wahrheit(links)
    rw = None if rechts is None else _wahrheit(rechts)
    if operator == "und":
        if lw is False or rw is False:
            return False
        if lw is None or rw is None:
            return None
        return True
    if lw is True or rw is True:
        return True
    if lw is None or rw is None:
        return None
    return False


def _vergleichen(operator: str, links: Wert, rechts: Wert) -> bool | None:
    if links is None or rechts is None:
        return None
    if operator in {"==", "!="}:
        gleich = _gleich(links, rechts)
        return gleich if operator == "==" else not gleich
    lz, rz = _als_zahl(links), _als_zahl(rechts)
    if lz is None or rz is None:
        if isinstance(links, date) and isinstance(rechts, date):
            lz_date, rz_date = links, rechts
            return {
                "<": lz_date < rz_date,
                "<=": lz_date <= rz_date,
                ">": lz_date > rz_date,
                ">=": lz_date >= rz_date,
            }[operator]
        return None
    return {"<": lz < rz, "<=": lz <= rz, ">": lz > rz, ">=": lz >= rz}[operator]


def _gleich(links: Wert, rechts: Wert) -> bool:
    if isinstance(links, str) or isinstance(rechts, str):
        return str(links).strip().lower() == str(rechts).strip().lower()
    lz, rz = _als_zahl(links), _als_zahl(rechts)
    if lz is not None and rz is not None:
        return lz == rz
    return bool(links == rechts)


def pruefen(quelle: str, felder: dict[str, Wert]) -> bool | None:
    """Wertet einen Regelausdruck aus. ``None`` heißt: nicht entscheidbar."""
    ergebnis = auswerten(uebersetzen(quelle), felder)
    if ergebnis is None:
        return None
    return _wahrheit(ergebnis)


def felder_im_ausdruck(quelle: str) -> set[str]:
    """Welche Felder braucht dieser Ausdruck? Für Vorschau und Validierung."""

    def sammeln(knoten: Knoten, ziel: set[str]) -> None:
        if isinstance(knoten, Feld):
            ziel.add(knoten.name)
        elif isinstance(knoten, Vorhanden):
            ziel.add(knoten.name)
        elif isinstance(knoten, Verneinung):
            sammeln(knoten.inhalt, ziel)
        elif isinstance(knoten, ProzentVon):
            sammeln(knoten.anteil, ziel)
            sammeln(knoten.grundwert, ziel)
        elif isinstance(knoten, (Rechnung, Vergleich, Verknuepfung)):
            sammeln(knoten.links, ziel)
            sammeln(knoten.rechts, ziel)

    gefunden: set[str] = set()
    sammeln(uebersetzen(quelle), gefunden)
    return gefunden
