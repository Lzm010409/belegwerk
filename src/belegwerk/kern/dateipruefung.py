"""Uploadgrenzen und Typprüfung per Magic Bytes (Querschnitt 8.4).

Die Dateiendung ist eine Behauptung des Absenders. Geprüft wird der Inhalt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from belegwerk.konfiguration import einstellungen


class DateiAbgelehnt(Exception):
    """Grund in Klartext, damit die Meldung sagt, was zu tun ist."""


@dataclass(frozen=True, slots=True)
class DateiBefund:
    art: str  # 'pdf' | 'xml' | 'text' | 'bild'
    unterart: str | None  # z. B. 'jpeg', 'png', 'vxs'
    groesse: int


_XML_KOPF = re.compile(rb"^\s*(<\?xml|<!DOCTYPE|<[A-Za-z_])")


def art_bestimmen(inhalt: bytes) -> DateiBefund:
    groesse = len(inhalt)
    if inhalt.startswith(b"%PDF-"):
        return DateiBefund("pdf", None, groesse)
    if inhalt.startswith(b"\xff\xd8\xff"):
        return DateiBefund("bild", "jpeg", groesse)
    if inhalt.startswith(b"\x89PNG\r\n\x1a\n"):
        return DateiBefund("bild", "png", groesse)
    kopf = inhalt[:4096].lstrip(b"\xef\xbb\xbf")
    if _XML_KOPF.match(kopf):
        return DateiBefund("xml", None, groesse)
    try:
        inhalt[:8192].decode("utf-8")
    except UnicodeDecodeError:
        try:
            inhalt[:8192].decode("cp1252")
        except UnicodeDecodeError as fehler:
            raise DateiAbgelehnt(
                "Der Dateityp wurde nicht erkannt. Zulässig sind PDF, TXT, XML/VXS "
                "sowie JPEG und PNG."
            ) from fehler
    return DateiBefund("text", None, groesse)


def pruefen(
    inhalt: bytes,
    erlaubte_arten: frozenset[str],
    max_bytes: int | None = None,
) -> DateiBefund:
    """Prüft Größe und tatsächlichen Typ. Wirft ``DateiAbgelehnt`` mit Klartext."""
    grenze = max_bytes or einstellungen().max_upload_bytes
    if not inhalt:
        raise DateiAbgelehnt("Die Datei ist leer.")
    if len(inhalt) > grenze:
        raise DateiAbgelehnt(
            f"Die Datei ist {len(inhalt) / 1_048_576:.1f} MB groß. "
            f"Zulässig sind {grenze / 1_048_576:.0f} MB."
        )
    befund = art_bestimmen(inhalt)
    if befund.art not in erlaubte_arten:
        lesbar = ", ".join(sorted(erlaubte_arten))
        raise DateiAbgelehnt(
            f"Die Datei ist vom Typ „{befund.art}“. An dieser Stelle sind zulässig: {lesbar}."
        )
    return befund


def seitenzahl_pruefen(seiten: int) -> None:
    grenze = einstellungen().max_seiten
    if seiten > grenze:
        raise DateiAbgelehnt(
            f"Das Dokument hat {seiten} Seiten. Verarbeitet werden bis zu {grenze} Seiten."
        )
