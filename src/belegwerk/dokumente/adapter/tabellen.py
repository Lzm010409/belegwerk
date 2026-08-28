"""Profilgesteuerter Adapter für zeilenorientierte Dokumente.

DAT, Audatex und die Prüfberichte unterscheiden sich in den Wörtern, nicht in
der Struktur: Kopfdaten, Verrechnungssätze, Positionsblöcke, Summen. Diese
Maschine liest die Struktur, die Wörter stehen im Profil.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal

from belegwerk.dokumente.konfidenz import berechnen
from belegwerk.dokumente.modell import (
    Fahrzeug,
    Kalkulation,
    Position,
    PositionsArt,
    Summen,
    Verrechnungssaetze,
)
from belegwerk.dokumente.profile import Abschnitt, Profil
from belegwerk.kern.formate import zahl_lesen

_log = logging.getLogger(__name__)


def _erster_treffer(text: str, muster: tuple[re.Pattern[str], ...]) -> dict[str, str] | None:
    for regex in muster:
        treffer = regex.search(text)
        if treffer is None:
            continue
        if treffer.groupdict():
            return {name: wert for name, wert in treffer.groupdict().items() if wert is not None}
        return {"wert": treffer.group(1)}
    return None


def _zahl(gruppen: dict[str, str] | None, schluessel: str = "wert") -> Decimal | None:
    if gruppen is None:
        return None
    return zahl_lesen(gruppen.get(schluessel))


def _abschnittszeilen(zeilen: list[str], abschnitt: Abschnitt) -> list[str]:
    """Alle Zeilen zwischen Beginn- und Endemarke, über alle Vorkommen hinweg."""
    gesammelt: list[str] = []
    innerhalb = False
    for zeile in zeilen:
        if not innerhalb:
            if abschnitt.beginn.search(zeile):
                innerhalb = True
            continue
        if abschnitt.ende is not None and abschnitt.ende.search(zeile):
            innerhalb = False
            continue
        gesammelt.append(zeile)
    return gesammelt


def _position_bauen(art: PositionsArt, gruppen: dict[str, str], rohzeile: str) -> Position | None:
    betrag = zahl_lesen(gruppen.get("betrag"))
    if betrag is None:
        return None
    nummer = gruppen.get("nr")
    bezeichnung = (gruppen.get("bezeichnung") or "").strip()
    if not bezeichnung:
        return None
    return Position(
        laufnummer=int(nummer) if nummer and nummer.isdigit() else 0,
        art=art,
        bezeichnung=bezeichnung,
        betrag=betrag,
        teilenummer=(gruppen.get("teilenummer") or "").strip() or None,
        arbeitswerte=zahl_lesen(gruppen.get("aw")),
        stundensatz=zahl_lesen(gruppen.get("satz")),
        lackstufe=int(gruppen["stufe"]) if gruppen.get("stufe", "").isdigit() else None,
        einzelpreis=zahl_lesen(gruppen.get("einzelpreis")),
        aufschlag_prozent=zahl_lesen(gruppen.get("aufschlag")),
        rohzeile=rohzeile.rstrip(),
    )


def lesen(profil: Profil, text: str, quellformat: str, textguete: float) -> Kalkulation:
    zeilen = text.splitlines()

    felder: dict[str, str] = {}
    for muster in profil.felder.values():
        treffer = _erster_treffer(text, muster)
        if treffer:
            felder.update({name: wert for name, wert in treffer.items() if name not in felder})

    erstzulassung = None
    if roh := felder.get("erstzulassung"):
        try:
            erstzulassung = datetime.strptime(roh, "%d.%m.%Y").date()
        except ValueError:
            _log.info("Erstzulassung nicht lesbar", extra={"adapter": profil.name})

    laufleistung = None
    if roh := felder.get("laufleistung"):
        wert = zahl_lesen(roh)
        laufleistung = int(wert) if wert is not None else None

    fahrzeug = Fahrzeug(
        hersteller=(felder.get("hersteller") or "").strip() or None,
        modell=(felder.get("modell") or "").strip() or None,
        vin=(felder.get("vin") or "").strip() or None,
        kennzeichen=(felder.get("kennzeichen") or "").strip() or None,
        erstzulassung=erstzulassung,
        laufleistung_km=laufleistung,
    )

    saetze = Verrechnungssaetze(
        **{
            name: _zahl(_erster_treffer(text, muster))
            for name, muster in profil.saetze.items()
            if name
            in {
                "mechanik",
                "karosserie",
                "elektrik",
                "lack_lohn",
                "lack_material_prozent",
                "upe_aufschlag_prozent",
                "verbringung",
            }
        }
    )

    gefundene_summen = {
        name: _zahl(_erster_treffer(text, muster)) for name, muster in profil.summen.items()
    }
    summen = Summen(
        ersatzteile=gefundene_summen.get("ersatzteile"),
        arbeit=gefundene_summen.get("arbeit"),
        lack=gefundene_summen.get("lack"),
        nebenkosten=gefundene_summen.get("nebenkosten"),
        netto=gefundene_summen.get("netto"),
        mehrwertsteuer=gefundene_summen.get("mehrwertsteuer"),
        brutto=gefundene_summen.get("brutto"),
    )

    positionen: list[Position] = []
    gefundene_abschnitte: set[str] = set()
    erwartete: list[str] = []
    for abschnitt in profil.abschnitte:
        if not abschnitt.optional:
            erwartete.append(abschnitt.art.value)
        vorher = len(positionen)
        for zeile in _abschnittszeilen(zeilen, abschnitt):
            for zeilenmuster in abschnitt.zeilenmuster:
                zeilentreffer = zeilenmuster.match(zeile)
                if zeilentreffer is None:
                    continue
                gruppen = {
                    name: wert
                    for name, wert in zeilentreffer.groupdict().items()
                    if wert is not None
                }
                position = _position_bauen(abschnitt.art, gruppen, zeile)
                if position is not None:
                    positionen.append(position)
                break
        if len(positionen) > vorher:
            gefundene_abschnitte.add(abschnitt.art.value)

    hinweise: list[str] = list(profil.hinweise)
    if vorgelegt := gefundene_summen.get("vorgelegt_netto"):
        hinweise.append(f"Im Dokument genannte vorgelegte Nettosumme: {vorgelegt}")

    kalkulation = Kalkulation(
        quelle=profil.quelle,
        quellformat=quellformat,
        adapter=profil.adaptername(quellformat),
        aktenzeichen=(felder.get("aktenzeichen") or "").strip() or None,
        fahrzeug=fahrzeug,
        saetze=saetze,
        positionen=positionen,
        summen=summen,
        rohtext=text,
        hinweise=hinweise,
    )

    befund = berechnen(
        kalkulation,
        pflichtfelder=profil.pflichtfelder,
        erwartete_abschnitte=tuple(erwartete),
        gefundene_abschnitte=gefundene_abschnitte,
        textguete=textguete,
    )
    kalkulation.konfidenz = befund.wert
    if not befund.kontrollrechnung and befund.unerklaerter_rest is not None:
        kalkulation.hinweise.append(
            "Die Summe der erkannten Positionen weicht um "
            f"{befund.unerklaerter_rest} von der ausgewiesenen Nettosumme ab."
        )
    for feld in befund.fehlende_felder:
        kalkulation.hinweise.append(f"Pflichtfeld nicht gefunden: {feld}")
    for art in befund.leere_abschnitte:
        kalkulation.hinweise.append(f"Abschnitt ohne erkannte Positionen: {art}")
    return kalkulation
