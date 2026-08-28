"""Adapter für DAT-VXS (XML).

VXS ist strukturell am saubersten — deshalb hat dieser Adapter keine
Heuristik und keinen Konfidenzabschlag aus der Textgüte: was im XML steht,
steht dort eindeutig.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from belegwerk.dokumente.konfidenz import berechnen
from belegwerk.dokumente.modell import (
    Fahrzeug,
    Kalkulation,
    Position,
    PositionsArt,
    Quelle,
    Summen,
    Verrechnungssaetze,
)

NAME = "dat_vxs"


class VxsFehler(Exception):
    pass


def _text(knoten: etree._Element | None) -> str | None:
    if knoten is None or knoten.text is None:
        return None
    wert = knoten.text.strip()
    return wert or None


def _dezimal(knoten: etree._Element | None) -> Decimal | None:
    roh = _text(knoten)
    if roh is None:
        return None
    try:
        return Decimal(roh)
    except InvalidOperation:
        return None


def erkennt(daten: bytes) -> bool:
    kopf = daten[:2000].decode("utf-8", errors="ignore")
    return "DAT_Kalkulation" in kopf or "<Kalkulation" in kopf


def lesen(daten: bytes) -> Kalkulation:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        wurzel = etree.fromstring(daten, parser=parser)
    except etree.XMLSyntaxError as fehler:
        raise VxsFehler(f"Die Datei ist kein lesbares XML: {fehler}") from fehler

    fahrzeug_knoten = wurzel.find("Fahrzeug")
    erstzulassung: date | None = None
    if fahrzeug_knoten is not None and (roh := _text(fahrzeug_knoten.find("Erstzulassung"))):
        try:
            erstzulassung = date.fromisoformat(roh)
        except ValueError:
            erstzulassung = None

    laufleistung = None
    if fahrzeug_knoten is not None and (roh := _text(fahrzeug_knoten.find("Laufleistung"))):
        laufleistung = int(roh) if roh.isdigit() else None

    fahrzeug = Fahrzeug(
        hersteller=_text(fahrzeug_knoten.find("Hersteller")) if fahrzeug_knoten is not None else None,
        modell=_text(fahrzeug_knoten.find("Typ")) if fahrzeug_knoten is not None else None,
        vin=_text(fahrzeug_knoten.find("FIN")) if fahrzeug_knoten is not None else None,
        kennzeichen=_text(fahrzeug_knoten.find("Kennzeichen")) if fahrzeug_knoten is not None else None,
        erstzulassung=erstzulassung,
        laufleistung_km=laufleistung,
    )

    satz_knoten = wurzel.find("Verrechnungssaetze")
    saetze = Verrechnungssaetze()
    if satz_knoten is not None:
        saetze = Verrechnungssaetze(
            mechanik=_dezimal(satz_knoten.find("LohnMechanik")),
            karosserie=_dezimal(satz_knoten.find("LohnKarosserie")),
            elektrik=_dezimal(satz_knoten.find("LohnElektrik")),
            lack_lohn=_dezimal(satz_knoten.find("LohnLack")),
            lack_material_prozent=_dezimal(satz_knoten.find("LackmaterialProzent")),
            upe_aufschlag_prozent=_dezimal(satz_knoten.find("UPEAufschlagProzent")),
            verbringung=_dezimal(satz_knoten.find("Verbringung")),
        )

    positionen: list[Position] = []
    gefundene_arten: set[str] = set()
    for eintrag in wurzel.findall("./Positionen/Position"):
        betrag = _dezimal(eintrag.find("Betrag"))
        bezeichnung = _text(eintrag.find("Bezeichnung"))
        art_roh = eintrag.get("art", "")
        if betrag is None or bezeichnung is None or art_roh not in PositionsArt.__members__:
            continue
        art = PositionsArt[art_roh]
        stufe = _text(eintrag.find("Lackstufe"))
        positionen.append(
            Position(
                laufnummer=int(eintrag.get("nr", "0") or 0),
                art=art,
                bezeichnung=bezeichnung,
                betrag=betrag,
                teilenummer=_text(eintrag.find("Teilenummer")),
                arbeitswerte=_dezimal(eintrag.find("Arbeitswerte")),
                stundensatz=_dezimal(eintrag.find("Stundensatz")),
                lackstufe=int(stufe) if stufe and stufe.isdigit() else None,
                einzelpreis=_dezimal(eintrag.find("Einzelpreis")),
                aufschlag_prozent=_dezimal(eintrag.find("AufschlagProzent")),
                rohzeile=etree.tostring(eintrag, encoding="unicode").strip(),
            )
        )
        gefundene_arten.add(art.value)

    summen_knoten = wurzel.find("Summen")
    summen = Summen()
    if summen_knoten is not None:
        summen = Summen(
            ersatzteile=_dezimal(summen_knoten.find("Ersatzteile")),
            arbeit=_dezimal(summen_knoten.find("Arbeit")),
            lack=_dezimal(summen_knoten.find("Lack")),
            nebenkosten=_dezimal(summen_knoten.find("Nebenkosten")),
            netto=_dezimal(summen_knoten.find("Netto")),
            mehrwertsteuer=_dezimal(summen_knoten.find("Mehrwertsteuer")),
            brutto=_dezimal(summen_knoten.find("Brutto")),
        )

    kalkulation = Kalkulation(
        quelle=Quelle.DAT,
        quellformat="vxs",
        adapter=NAME,
        aktenzeichen=_text(wurzel.find("./Vorgang/Vorgangsnummer")),
        fahrzeug=fahrzeug,
        saetze=saetze,
        positionen=positionen,
        summen=summen,
        rohtext=daten.decode("utf-8", errors="replace"),
    )
    befund = berechnen(
        kalkulation,
        pflichtfelder=("aktenzeichen", "vin", "netto"),
        erwartete_abschnitte=("ERSATZTEIL", "ARBEIT", "LACK"),
        gefundene_abschnitte=gefundene_arten,
        textguete=1.0,
    )
    kalkulation.konfidenz = befund.wert
    if not befund.kontrollrechnung and befund.unerklaerter_rest is not None:
        kalkulation.hinweise.append(
            "Die Summe der Positionen weicht um "
            f"{befund.unerklaerter_rest} von der ausgewiesenen Nettosumme ab."
        )
    return kalkulation
