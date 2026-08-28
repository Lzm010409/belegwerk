"""Welcher Adapter passt zu diesem Dokument? (Plattformdatei 4.1)

    Eingabedatei
       ↓ Dateiendung + Textsignatur der ersten Seiten
       ↓ Adapter
    Normalisiertes Modell

Die Auswahl geschieht über Signaturpunkte, nicht über die Dateiendung allein:
DAT liefert der Lesbarkeit halber meist PDF aus, und ein als `.txt` benannter
Prüfbericht bleibt ein Prüfbericht.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from belegwerk.dokumente.adapter import dat_vxs
from belegwerk.dokumente.adapter.tabellen import lesen as tabellen_lesen
from belegwerk.dokumente.konfidenz import SCHWELLE_KORREKTUR
from belegwerk.dokumente.modell import Kalkulation
from belegwerk.dokumente.profile import Profil, alle_profile
from belegwerk.dokumente.text import text_aus_bytes
from belegwerk.kern.dateipruefung import DateiAbgelehnt, art_bestimmen

_log = logging.getLogger(__name__)

ERLAUBTE_ARTEN = frozenset({"pdf", "text", "xml"})


class KeinAdapter(Exception):
    """Kein Profil passt. Die Meldung nennt, was gesucht wurde."""


@dataclass(frozen=True, slots=True)
class Erkennung:
    adapter: str
    profil: str
    quellformat: str
    punkte: int
    kandidaten: dict[str, int]


def _quellformat(art: str, unterart: str | None) -> str:
    if art == "pdf":
        return "pdf"
    if art == "xml":
        return "vxs"
    return "txt"


def erkennen(daten: bytes) -> tuple[Erkennung, str]:
    """Bestimmt Adapter und liefert den gewonnenen Text gleich mit."""
    befund = art_bestimmen(daten)
    if befund.art not in ERLAUBTE_ARTEN:
        raise DateiAbgelehnt(
            "Verarbeitet werden Kalkulationen und Prüfberichte als PDF, TXT oder VXS. "
            f"Diese Datei ist vom Typ „{befund.art}“."
        )

    if befund.art == "xml":
        if not dat_vxs.erkennt(daten):
            raise KeinAdapter(
                "Die XML-Datei ist keine DAT-VXS-Kalkulation. Erwartet wird ein "
                "Element „DAT_Kalkulation“."
            )
        return (
            Erkennung(
                adapter=dat_vxs.NAME,
                profil=dat_vxs.NAME,
                quellformat="vxs",
                punkte=10,
                kandidaten={dat_vxs.NAME: 10},
            ),
            daten.decode("utf-8", errors="replace"),
        )

    extraktion = text_aus_bytes(daten, befund.art)
    quellformat = _quellformat(befund.art, befund.unterart)

    kandidaten: dict[str, int] = {}
    bester: Profil | None = None
    for profil in alle_profile():
        if quellformat not in profil.formate:
            continue
        punkte = profil.punkte(extraktion.text)
        kandidaten[profil.name] = punkte
        if punkte >= profil.mindestpunkte and (bester is None or punkte > kandidaten[bester.name]):
            bester = profil

    if bester is None:
        gepruefte = ", ".join(sorted(kandidaten)) or "keine"
        raise KeinAdapter(
            "Das Dokument passt zu keinem bekannten Layout. Geprüft wurden die "
            f"Profile: {gepruefte}. Kommt dieses Layout häufiger vor, kann ein "
            "Profil dafür ergänzt werden."
        )

    _log.info(
        "Adapter gewählt",
        extra={"adapter": bester.adaptername(quellformat), "quellformat": quellformat, "kandidaten": kandidaten},
    )
    return (
        Erkennung(
            adapter=bester.adaptername(quellformat),
            profil=bester.name,
            quellformat=quellformat,
            punkte=kandidaten[bester.name],
            kandidaten=kandidaten,
        ),
        extraktion.text,
    )


def verarbeiten(daten: bytes) -> Kalkulation:
    """Der einzige Einstieg für alles außerhalb dieses Pakets."""
    from belegwerk.dokumente.profile import profil as profil_holen

    erkennung, text = erkennen(daten)
    if erkennung.profil == dat_vxs.NAME:
        return dat_vxs.lesen(daten)

    from belegwerk.dokumente.text import guete_bewerten

    profil = profil_holen(erkennung.profil)
    return tabellen_lesen(profil, text, erkennung.quellformat, guete_bewerten(text))


def braucht_korrektur(kalkulation: Kalkulation) -> bool:
    return kalkulation.konfidenz < SCHWELLE_KORREKTUR
