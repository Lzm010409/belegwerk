"""Erzeugt den synthetischen Testkorpus für das Dokumentenpaket.

**Wichtig, damit niemand sich täuscht:** Das sind *keine* echten Dokumente.
Phase 0 der Briefings verlangt 30 anonymisierte Echtdokumente je Format und
15 echte Prüfberichte; die liegen dem bauenden Agenten nicht vor. Dieser
Generator baut stattdessen einen deterministischen Korpus in den Layouts, die
die Profile beschreiben — er prüft damit die Parserlogik, die Rechenwege und
die Kontrollrechnungen, **nicht** die Robustheit gegen echte Layoutvielfalt.

Die Abbruchentscheidung aus Todo 0.3 ist damit ausdrücklich **nicht**
getroffen. Sobald echte Dokumente vorliegen, gehören sie anonymisiert in
dasselbe Verzeichnis; die Golden-Tests laufen dann gegen beide Bestände.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

VERZEICHNIS = Path(__file__).parent / "dokumente"

HERSTELLER = [
    ("VOLKSWAGEN", "Golf VIII 2.0 TDI"),
    ("BMW", "320d Touring"),
    ("MERCEDES-BENZ", "C 220 d T-Modell"),
    ("AUDI", "A4 Avant 40 TDI"),
    ("SKODA", "Octavia Combi 1.5 TSI"),
    ("FORD", "Focus Turnier 1.0 EcoBoost"),
    ("OPEL", "Astra K 1.4 Turbo"),
    ("TOYOTA", "Corolla Touring Sports"),
    ("SEAT", "Leon ST 1.5 TSI"),
    ("RENAULT", "Megane Grandtour"),
]

ERSATZTEILE = [
    ("Motorhaube", "5H0823031"),
    ("Kotfluegel vorn links", "5H0821021"),
    ("Kotfluegel vorn rechts", "5H0821022"),
    ("Stossfaenger vorn", "5H0807221"),
    ("Scheinwerfer links", "5H0941005"),
    ("Scheinwerfer rechts", "5H0941006"),
    ("Tuer vorn links", "5H0831055"),
    ("Aussenspiegel links", "5H0857507"),
    ("Kuehlergrill", "5H0853651"),
    ("Querträger vorn", "5H0805594"),
    ("Radhausschale vorn links", "5H0809957"),
    ("Nebelscheinwerfer links", "5H0941699"),
]

ARBEITEN = [
    ("Motorhaube ersetzen", "karosserie"),
    ("Kotfluegel vorn links ersetzen", "karosserie"),
    ("Stossfaenger vorn aus- und einbauen", "mechanik"),
    ("Scheinwerfer links ersetzen", "elektrik"),
    ("Frontklappe einstellen", "karosserie"),
    ("Achsvermessung durchfuehren", "mechanik"),
    ("Airbagsteuergeraet auslesen", "elektrik"),
    ("Tuer vorn links instand setzen", "karosserie"),
]

LACKARBEITEN = [
    ("Motorhaube lackieren", 3),
    ("Kotfluegel vorn links lackieren", 3),
    ("Stossfaenger vorn lackieren", 2),
    ("Tuer vorn links lackieren", 3),
    ("Beilackierung Seitenwand links", 1),
]

NEBENKOSTEN = [
    "Verbringungskosten",
    "Probefahrt",
    "Fahrzeugreinigung",
    "Entsorgung Altteile",
]

ZENT = Decimal("0.01")


def _r(wert: Decimal) -> Decimal:
    return wert.quantize(ZENT, rounding=ROUND_HALF_UP)


def _de(wert: Decimal | None, stellen: int = 2) -> str:
    if wert is None:
        return ""
    text = f"{wert.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP):,.{stellen}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


@dataclass
class Zeile:
    nummer: int
    art: str
    bezeichnung: str
    betrag: Decimal
    teilenummer: str | None = None
    arbeitswerte: Decimal | None = None
    stundensatz: Decimal | None = None
    lackstufe: int | None = None
    einzelpreis: Decimal | None = None
    aufschlag_prozent: Decimal | None = None


@dataclass
class Fall:
    aktenzeichen: str
    hersteller: str
    modell: str
    vin: str
    kennzeichen: str
    erstzulassung: date
    laufleistung: int
    saetze: dict[str, Decimal]
    zeilen: list[Zeile]
    mwst_satz: Decimal

    def summe(self, art: str) -> Decimal:
        return _r(sum((z.betrag for z in self.zeilen if z.art == art), Decimal("0")))

    @property
    def netto(self) -> Decimal:
        return _r(sum((z.betrag for z in self.zeilen), Decimal("0")))

    @property
    def mehrwertsteuer(self) -> Decimal:
        return _r(self.netto * self.mwst_satz / Decimal("100"))

    @property
    def brutto(self) -> Decimal:
        return _r(self.netto + self.mehrwertsteuer)


def _vin(zufall: random.Random) -> str:
    zeichen = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    return "WVWZZZ" + "".join(zufall.choice(zeichen) for _ in range(11))


def fall_erzeugen(zufall: random.Random, nummer: int) -> Fall:
    hersteller, modell = zufall.choice(HERSTELLER)
    saetze = {
        "mechanik": Decimal(zufall.randrange(11000, 17500, 100)) / 100,
        "karosserie": Decimal(zufall.randrange(12000, 18500, 100)) / 100,
        "elektrik": Decimal(zufall.randrange(11500, 18000, 100)) / 100,
        "lack_lohn": Decimal(zufall.randrange(12000, 17500, 100)) / 100,
        "lack_material_prozent": Decimal(zufall.randrange(300, 460, 5)) / 10,
        "upe_aufschlag_prozent": Decimal(zufall.randrange(0, 260, 10)) / 10,
        "verbringung": Decimal(zufall.randrange(6000, 18000, 500)) / 100,
    }

    zeilen: list[Zeile] = []
    laufnummer = 1
    for bezeichnung, teil in zufall.sample(ERSATZTEILE, zufall.randint(3, 7)):
        upe = Decimal(zufall.randrange(4500, 120000, 5)) / 100
        aufschlag = saetze["upe_aufschlag_prozent"]
        betrag = _r(upe * (Decimal("100") + aufschlag) / Decimal("100"))
        zeilen.append(
            Zeile(
                nummer=laufnummer,
                art="ERSATZTEIL",
                bezeichnung=bezeichnung,
                teilenummer=f"{teil}{chr(65 + nummer % 20)}",
                einzelpreis=upe,
                aufschlag_prozent=aufschlag,
                betrag=betrag,
            )
        )
        laufnummer += 1

    laufnummer = 11
    for bezeichnung, gewerk in zufall.sample(ARBEITEN, zufall.randint(3, 6)):
        aw = Decimal(zufall.randrange(5, 145)) / 10
        satz = saetze[gewerk]
        zeilen.append(
            Zeile(
                nummer=laufnummer,
                art="ARBEIT",
                bezeichnung=bezeichnung,
                arbeitswerte=aw,
                stundensatz=satz,
                betrag=_r(aw * satz / Decimal("10")),
            )
        )
        laufnummer += 1

    laufnummer = 21
    for bezeichnung, stufe in zufall.sample(LACKARBEITEN, zufall.randint(2, 4)):
        aw = Decimal(zufall.randrange(20, 180)) / 10
        satz = saetze["lack_lohn"]
        lohn = aw * satz / Decimal("10")
        material = lohn * saetze["lack_material_prozent"] / Decimal("100")
        zeilen.append(
            Zeile(
                nummer=laufnummer,
                art="LACK",
                bezeichnung=bezeichnung,
                arbeitswerte=aw,
                stundensatz=satz,
                lackstufe=stufe,
                betrag=_r(lohn + material),
            )
        )
        laufnummer += 1

    laufnummer = 31
    posten = ["Verbringungskosten"] + zufall.sample(NEBENKOSTEN[1:], zufall.randint(0, 2))
    for bezeichnung in posten:
        betrag = (
            saetze["verbringung"]
            if bezeichnung == "Verbringungskosten"
            else Decimal(zufall.randrange(2500, 15000, 100)) / 100
        )
        zeilen.append(Zeile(nummer=laufnummer, art="NEBENKOSTEN", bezeichnung=bezeichnung, betrag=betrag))
        laufnummer += 1

    return Fall(
        aktenzeichen=f"{zufall.randint(100, 999):04d}/{zufall.randint(1000, 9999)}TG",
        hersteller=hersteller,
        modell=modell,
        vin=_vin(zufall),
        kennzeichen=f"OL-{chr(65 + zufall.randrange(26))}{chr(65 + zufall.randrange(26))} {zufall.randint(1, 9999)}",
        erstzulassung=date(2026, 1, 1) - timedelta(days=zufall.randint(400, 3200)),
        laufleistung=zufall.randrange(8000, 220000, 10),
        saetze=saetze,
        zeilen=zeilen,
        mwst_satz=Decimal("19.0"),
    )


# ---------------------------------------------------------------------------
# Darstellungen
# ---------------------------------------------------------------------------


def _kopf(fall: Fall, titel: str, absender: str) -> list[str]:
    return [
        f"{absender:<62}Seite 1",
        "",
        titel,
        f"Vorgangsnummer      {fall.aktenzeichen}",
        "",
        "Fahrzeug",
        f"Hersteller / Typ    {fall.hersteller} {fall.modell}",
        f"Fahrgestellnummer   {fall.vin}",
        f"Amtl. Kennzeichen   {fall.kennzeichen}",
        f"Erstzulassung       {fall.erstzulassung.strftime('%d.%m.%Y')}",
        f"Laufleistung        {_de(Decimal(fall.laufleistung), 0)} km",
        "",
    ]


def _saetze_block(fall: Fall) -> list[str]:
    s = fall.saetze
    return [
        "Verrechnungssaetze",
        f"Lohn Mechanik                 {_de(s['mechanik']):>10} EUR/Std",
        f"Lohn Karosserie               {_de(s['karosserie']):>10} EUR/Std",
        f"Lohn Elektrik                 {_de(s['elektrik']):>10} EUR/Std",
        f"Lohn Lackierung               {_de(s['lack_lohn']):>10} EUR/Std",
        f"Lackmaterial                  {_de(s['lack_material_prozent'], 1):>10} %",
        f"UPE-Aufschlag                 {_de(s['upe_aufschlag_prozent'], 1):>10} %",
        f"Verbringungskosten            {_de(s['verbringung']):>10} EUR",
        "",
    ]


def als_dat_text(fall: Fall) -> str:
    zeilen = _kopf(fall, f"Kalkulation zum Vorgang {fall.aktenzeichen}", "DAT Deutschland - SilverDAT 3")
    zeilen += _saetze_block(fall)

    zeilen += ["Ersatzteile", "Pos Teilenummer          Bezeichnung                            UPE   Aufschlag        Betrag"]
    for z in (x for x in fall.zeilen if x.art == "ERSATZTEIL"):
        zeilen.append(
            f"{z.nummer:>3} {z.teilenummer:<20} {z.bezeichnung:<32}"
            f"{_de(z.einzelpreis):>9}  {_de(z.aufschlag_prozent, 1):>7} %  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Ersatzteile':<64}{_de(fall.summe('ERSATZTEIL')):>12}", ""]

    zeilen += ["Arbeitslohn", "Pos     AW  Beschreibung                                       Satz         Betrag"]
    for z in (x for x in fall.zeilen if x.art == "ARBEIT"):
        zeilen.append(
            f"{z.nummer:>3}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<44}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Arbeitslohn':<64}{_de(fall.summe('ARBEIT')):>12}", ""]

    zeilen += ["Lackierung", "Pos Stufe     AW  Beschreibung                                   Satz         Betrag"]
    for z in (x for x in fall.zeilen if x.art == "LACK"):
        zeilen.append(
            f"{z.nummer:>3}  {z.lackstufe:>4}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<40}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Lackierung':<64}{_de(fall.summe('LACK')):>12}", ""]

    zeilen += ["Nebenkosten", "Pos Beschreibung                                                            Betrag"]
    for z in (x for x in fall.zeilen if x.art == "NEBENKOSTEN"):
        zeilen.append(f"{z.nummer:>3}  {z.bezeichnung:<62}{_de(z.betrag):>12}")
    zeilen += [f"{'Summe Nebenkosten':<64}{_de(fall.summe('NEBENKOSTEN')):>12}", ""]

    zeilen += [
        "Kalkulationsergebnis",
        f"{'Summe netto':<64}{_de(fall.netto):>12}",
        f"{'Mehrwertsteuer ' + _de(fall.mwst_satz, 1) + ' %':<64}{_de(fall.mehrwertsteuer):>12}",
        f"{'Gesamtbetrag brutto':<64}{_de(fall.brutto):>12}",
        "",
    ]
    return "\n".join(zeilen) + "\n"


def als_audatex_text(fall: Fall) -> str:
    """Audatex nennt dieselben Dinge anders — genau das muss der Parser aushalten."""
    zeilen = _kopf(fall, f"Reparaturkalkulation {fall.aktenzeichen}", "Audatex AudaPad Web")
    s = fall.saetze
    zeilen += [
        "Stundenverrechnungssaetze",
        f"AZ-Satz Mechanik              {_de(s['mechanik']):>10} EUR",
        f"AZ-Satz Karosserie            {_de(s['karosserie']):>10} EUR",
        f"AZ-Satz Elektrik              {_de(s['elektrik']):>10} EUR",
        f"AZ-Satz Lack                  {_de(s['lack_lohn']):>10} EUR",
        f"Lackmaterialindex             {_de(s['lack_material_prozent'], 1):>10} %",
        f"Teileaufschlag                {_de(s['upe_aufschlag_prozent'], 1):>10} %",
        f"Verbringung                   {_de(s['verbringung']):>10} EUR",
        "",
        "Teilepositionen",
        "Pos Teile-Nr.             Benennung                              UPE   Aufschlag        Betrag",
    ]
    for z in (x for x in fall.zeilen if x.art == "ERSATZTEIL"):
        zeilen.append(
            f"{z.nummer:>3} {z.teilenummer:<20} {z.bezeichnung:<32}"
            f"{_de(z.einzelpreis):>9}  {_de(z.aufschlag_prozent, 1):>7} %  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Teile gesamt':<64}{_de(fall.summe('ERSATZTEIL')):>12}", ""]

    zeilen += ["Arbeitspositionen", "Pos     AZ  Benennung                                          Satz         Betrag"]
    for z in (x for x in fall.zeilen if x.art == "ARBEIT"):
        zeilen.append(
            f"{z.nummer:>3}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<44}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Arbeit gesamt':<64}{_de(fall.summe('ARBEIT')):>12}", ""]

    zeilen += ["Lackpositionen", "Pos Stufe     AZ  Benennung                                      Satz         Betrag"]
    for z in (x for x in fall.zeilen if x.art == "LACK"):
        zeilen.append(
            f"{z.nummer:>3}  {z.lackstufe:>4}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<40}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Lack gesamt':<64}{_de(fall.summe('LACK')):>12}", ""]

    zeilen += ["Nebenkosten", "Pos Benennung                                                              Betrag"]
    for z in (x for x in fall.zeilen if x.art == "NEBENKOSTEN"):
        zeilen.append(f"{z.nummer:>3}  {z.bezeichnung:<62}{_de(z.betrag):>12}")
    zeilen += [f"{'Nebenkosten gesamt':<64}{_de(fall.summe('NEBENKOSTEN')):>12}", ""]

    zeilen += [
        "Kalkulationssumme",
        f"{'Reparaturkosten netto':<64}{_de(fall.netto):>12}",
        f"{'zzgl. MwSt ' + _de(fall.mwst_satz, 1) + ' %':<64}{_de(fall.mehrwertsteuer):>12}",
        f"{'Reparaturkosten brutto':<64}{_de(fall.brutto):>12}",
        "",
    ]
    return "\n".join(zeilen) + "\n"


def als_vxs(fall: Fall) -> str:
    """VXS ist strukturell am saubersten — deshalb hier der einfachste Adapter."""
    wurzel = ET.Element("DAT_Kalkulation", {"version": "3.0"})
    kopf = ET.SubElement(wurzel, "Vorgang")
    ET.SubElement(kopf, "Vorgangsnummer").text = fall.aktenzeichen
    fahrzeug = ET.SubElement(wurzel, "Fahrzeug")
    ET.SubElement(fahrzeug, "Hersteller").text = fall.hersteller
    ET.SubElement(fahrzeug, "Typ").text = fall.modell
    ET.SubElement(fahrzeug, "FIN").text = fall.vin
    ET.SubElement(fahrzeug, "Kennzeichen").text = fall.kennzeichen
    ET.SubElement(fahrzeug, "Erstzulassung").text = fall.erstzulassung.isoformat()
    ET.SubElement(fahrzeug, "Laufleistung", {"einheit": "km"}).text = str(fall.laufleistung)

    saetze = ET.SubElement(wurzel, "Verrechnungssaetze")
    for name, schluessel in [
        ("LohnMechanik", "mechanik"),
        ("LohnKarosserie", "karosserie"),
        ("LohnElektrik", "elektrik"),
        ("LohnLack", "lack_lohn"),
        ("LackmaterialProzent", "lack_material_prozent"),
        ("UPEAufschlagProzent", "upe_aufschlag_prozent"),
        ("Verbringung", "verbringung"),
    ]:
        ET.SubElement(saetze, name).text = str(fall.saetze[schluessel])

    positionen = ET.SubElement(wurzel, "Positionen")
    for z in fall.zeilen:
        eintrag = ET.SubElement(positionen, "Position", {"art": z.art, "nr": str(z.nummer)})
        ET.SubElement(eintrag, "Bezeichnung").text = z.bezeichnung
        if z.teilenummer:
            ET.SubElement(eintrag, "Teilenummer").text = z.teilenummer
        if z.arbeitswerte is not None:
            ET.SubElement(eintrag, "Arbeitswerte").text = str(z.arbeitswerte)
        if z.stundensatz is not None:
            ET.SubElement(eintrag, "Stundensatz").text = str(z.stundensatz)
        if z.lackstufe is not None:
            ET.SubElement(eintrag, "Lackstufe").text = str(z.lackstufe)
        if z.einzelpreis is not None:
            ET.SubElement(eintrag, "Einzelpreis").text = str(z.einzelpreis)
        if z.aufschlag_prozent is not None:
            ET.SubElement(eintrag, "AufschlagProzent").text = str(z.aufschlag_prozent)
        ET.SubElement(eintrag, "Betrag").text = str(z.betrag)

    summen = ET.SubElement(wurzel, "Summen")
    ET.SubElement(summen, "Ersatzteile").text = str(fall.summe("ERSATZTEIL"))
    ET.SubElement(summen, "Arbeit").text = str(fall.summe("ARBEIT"))
    ET.SubElement(summen, "Lack").text = str(fall.summe("LACK"))
    ET.SubElement(summen, "Nebenkosten").text = str(fall.summe("NEBENKOSTEN"))
    ET.SubElement(summen, "Netto").text = str(fall.netto)
    ET.SubElement(summen, "Mehrwertsteuer", {"satz": str(fall.mwst_satz)}).text = str(fall.mehrwertsteuer)
    ET.SubElement(summen, "Brutto").text = str(fall.brutto)

    ET.indent(wurzel, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(wurzel, encoding="unicode") + "\n"


# ---------------------------------------------------------------------------
# Prüfbericht: derselbe Fall, nach der Prüfung des Versicherers
# ---------------------------------------------------------------------------


@dataclass
class Kuerzung:
    klasse: str
    bezeichnung: str
    wert_eigen: str
    wert_pruefbericht: str


def kuerzung_anwenden(fall: Fall, zufall: random.Random) -> tuple[Fall, list[Kuerzung]]:
    """Erzeugt die geprüfte Fassung eines Falls mit den typischen Kürzungen."""
    kuerzungen: list[Kuerzung] = []
    saetze = dict(fall.saetze)
    zeilen = [Zeile(**vars(z)) for z in fall.zeilen]

    # UPE-Aufschlag gestrichen
    if saetze["upe_aufschlag_prozent"] > 0:
        alt = saetze["upe_aufschlag_prozent"]
        saetze["upe_aufschlag_prozent"] = Decimal("0.0")
        for z in zeilen:
            if z.art == "ERSATZTEIL" and z.einzelpreis is not None:
                z.aufschlag_prozent = Decimal("0.0")
                z.betrag = _r(z.einzelpreis)
        kuerzungen.append(Kuerzung("UPE_GEKUERZT", "UPE-Aufschlag", _de(alt, 1), "0,0"))

    # Stundensatz Karosserie gesenkt
    alt_satz = saetze["karosserie"]
    neu_satz = _r(alt_satz * Decimal("0.85"))
    if neu_satz < alt_satz:
        saetze["karosserie"] = neu_satz
        for z in zeilen:
            if z.art == "ARBEIT" and z.stundensatz == alt_satz and z.arbeitswerte is not None:
                z.stundensatz = neu_satz
                z.betrag = _r(z.arbeitswerte * neu_satz / Decimal("10"))
        kuerzungen.append(Kuerzung("SATZ_GESENKT", "Lohn Karosserie", _de(alt_satz), _de(neu_satz)))

    # Lackmaterialindex gesenkt
    alt_index = saetze["lack_material_prozent"]
    neu_index = _r(alt_index - Decimal("8.0"))
    if neu_index > 0:
        saetze["lack_material_prozent"] = neu_index
        for z in zeilen:
            if z.art == "LACK" and z.arbeitswerte is not None and z.stundensatz is not None:
                lohn = z.arbeitswerte * z.stundensatz / Decimal("10")
                z.betrag = _r(lohn + lohn * neu_index / Decimal("100"))
        kuerzungen.append(
            Kuerzung("LACKMATERIAL_GEKUERZT", "Lackmaterial", _de(alt_index, 1), _de(neu_index, 1))
        )

    # Eine Arbeitsposition in den Arbeitswerten gekürzt
    arbeiten = [z for z in zeilen if z.art == "ARBEIT" and (z.arbeitswerte or 0) > 2]
    if arbeiten:
        ziel = zufall.choice(arbeiten)
        alt_aw = ziel.arbeitswerte
        assert alt_aw is not None and ziel.stundensatz is not None
        ziel.arbeitswerte = _r(alt_aw * Decimal("0.6")).quantize(Decimal("0.1"))
        ziel.betrag = _r(ziel.arbeitswerte * ziel.stundensatz / Decimal("10"))
        kuerzungen.append(
            Kuerzung("AW_REDUZIERT", ziel.bezeichnung, _de(alt_aw, 1), _de(ziel.arbeitswerte, 1))
        )

    # Eine Lackposition in der Stufe herabgesetzt
    lack = [z for z in zeilen if z.art == "LACK" and (z.lackstufe or 0) > 1]
    if lack:
        ziel = zufall.choice(lack)
        alt_stufe = ziel.lackstufe
        assert alt_stufe is not None and ziel.arbeitswerte is not None and ziel.stundensatz is not None
        ziel.lackstufe = alt_stufe - 1
        ziel.arbeitswerte = _r(ziel.arbeitswerte * Decimal("0.8")).quantize(Decimal("0.1"))
        lohn = ziel.arbeitswerte * ziel.stundensatz / Decimal("10")
        ziel.betrag = _r(lohn + lohn * saetze["lack_material_prozent"] / Decimal("100"))
        kuerzungen.append(
            Kuerzung("LACKSTUFE_GESENKT", ziel.bezeichnung, str(alt_stufe), str(ziel.lackstufe))
        )

    # Eine Ersatzteilposition vollständig gestrichen
    teile = [z for z in zeilen if z.art == "ERSATZTEIL"]
    if len(teile) > 3:
        gestrichen = zufall.choice(teile)
        zeilen.remove(gestrichen)
        kuerzungen.append(
            Kuerzung("POS_ENTFALLEN", gestrichen.bezeichnung, _de(gestrichen.betrag), "0,00")
        )

    # Verbringungskosten gestrichen
    verbringung = [z for z in zeilen if z.bezeichnung == "Verbringungskosten"]
    if verbringung:
        zeilen.remove(verbringung[0])
        saetze["verbringung"] = Decimal("0.00")
        kuerzungen.append(
            Kuerzung("VERBRINGUNG_ENTFALLEN", "Verbringungskosten", _de(verbringung[0].betrag), "0,00")
        )

    geprueft = Fall(
        aktenzeichen=fall.aktenzeichen,
        hersteller=fall.hersteller,
        modell=fall.modell,
        vin=fall.vin,
        kennzeichen=fall.kennzeichen,
        erstzulassung=fall.erstzulassung,
        laufleistung=fall.laufleistung,
        saetze=saetze,
        zeilen=zeilen,
        mwst_satz=fall.mwst_satz,
    )
    return geprueft, kuerzungen


def als_pruefbericht_text(geprueft: Fall, eigen: Fall, absender: str) -> str:
    controlexpert = absender == "controlexpert"
    kopfzeile = (
        "ControlExpert GmbH - Rechnungspruefung"
        if controlexpert
        else "Eucon Digital GmbH - Pruefbericht Kalkulation"
    )
    s = geprueft.saetze
    zeilen = [
        f"{kopfzeile:<62}Seite 1",
        "",
        "Pruefbericht zur Schadenkalkulation",
        f"Schadennummer       {geprueft.aktenzeichen}",
        f"Fahrgestellnummer   {geprueft.vin}",
        f"Amtl. Kennzeichen   {geprueft.kennzeichen}",
        "",
        "Anerkannte Verrechnungssaetze",
        f"Lohn Mechanik                 {_de(s['mechanik']):>10} EUR/Std",
        f"Lohn Karosserie               {_de(s['karosserie']):>10} EUR/Std",
        f"Lohn Elektrik                 {_de(s['elektrik']):>10} EUR/Std",
        f"Lohn Lackierung               {_de(s['lack_lohn']):>10} EUR/Std",
        f"Lackmaterial                  {_de(s['lack_material_prozent'], 1):>10} %",
        f"UPE-Aufschlag                 {_de(s['upe_aufschlag_prozent'], 1):>10} %",
        f"Verbringungskosten            {_de(s['verbringung']):>10} EUR",
        "",
        "Anerkannte Ersatzteile",
        "Pos Teilenummer          Bezeichnung                            UPE   Aufschlag        Betrag",
    ]
    for z in (x for x in geprueft.zeilen if x.art == "ERSATZTEIL"):
        zeilen.append(
            f"{z.nummer:>3} {z.teilenummer:<20} {z.bezeichnung:<32}"
            f"{_de(z.einzelpreis):>9}  {_de(z.aufschlag_prozent, 1):>7} %  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Ersatzteile':<64}{_de(geprueft.summe('ERSATZTEIL')):>12}", ""]

    zeilen += [
        "Anerkannter Arbeitslohn",
        "Pos     AW  Beschreibung                                       Satz         Betrag",
    ]
    for z in (x for x in geprueft.zeilen if x.art == "ARBEIT"):
        zeilen.append(
            f"{z.nummer:>3}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<44}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Arbeitslohn':<64}{_de(geprueft.summe('ARBEIT')):>12}", ""]

    zeilen += [
        "Anerkannte Lackierung",
        "Pos Stufe     AW  Beschreibung                                   Satz         Betrag",
    ]
    for z in (x for x in geprueft.zeilen if x.art == "LACK"):
        zeilen.append(
            f"{z.nummer:>3}  {z.lackstufe:>4}  {_de(z.arbeitswerte, 1):>7}  {z.bezeichnung:<40}"
            f"{_de(z.stundensatz):>9}  {_de(z.betrag):>12}"
        )
    zeilen += [f"{'Summe Lackierung':<64}{_de(geprueft.summe('LACK')):>12}", ""]

    zeilen += ["Anerkannte Nebenkosten", "Pos Beschreibung                                                            Betrag"]
    for z in (x for x in geprueft.zeilen if x.art == "NEBENKOSTEN"):
        zeilen.append(f"{z.nummer:>3}  {z.bezeichnung:<62}{_de(z.betrag):>12}")
    zeilen += [f"{'Summe Nebenkosten':<64}{_de(geprueft.summe('NEBENKOSTEN')):>12}", ""]

    zeilen += [
        "Pruefergebnis",
        f"{'Kalkulierte Reparaturkosten netto':<64}{_de(eigen.netto):>12}",
        f"{'Summe netto':<64}{_de(geprueft.netto):>12}",
        f"{'Mehrwertsteuer ' + _de(geprueft.mwst_satz, 1) + ' %':<64}{_de(geprueft.mehrwertsteuer):>12}",
        f"{'Gesamtbetrag brutto':<64}{_de(geprueft.brutto):>12}",
        "",
        "Die Pruefung erfolgte anhand der uebermittelten Kalkulation.",
        "",
    ]
    return "\n".join(zeilen) + "\n"


# ---------------------------------------------------------------------------
# PDF-Ausgabe und Ablage
# ---------------------------------------------------------------------------


def text_als_pdf(text: str) -> bytes:
    """Rendert den Ausdruck als PDF — bewusst in einer Monospace-Schrift.

    So bleibt die Spaltenstruktur erhalten, die beide Extraktionspfade
    auswerten. Kalkulationsausdrucke sehen in der Praxis genauso aus.
    """
    from html import escape

    from weasyprint import HTML  # lokal importiert: nur der Generator braucht es

    html = (
        "<html><head><meta charset='utf-8'><style>"
        "@page { size: A4 landscape; margin: 10mm; }"
        "pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 7.2pt; "
        "line-height: 1.25; white-space: pre; }"
        "</style></head><body><pre>" + escape(text) + "</pre></body></html>"
    )
    return bytes(HTML(string=html).write_pdf())


def golden(fall: Fall, quelle: str, quellformat: str, adapter: str) -> dict[str, Any]:
    """Das erwartete normalisierte Modell — Grundlage der Golden-Tests."""
    return {
        "quelle": quelle,
        "quellformat": quellformat,
        "adapter": adapter,
        "aktenzeichen": fall.aktenzeichen,
        "fahrzeug": {
            "hersteller": fall.hersteller,
            "modell": fall.modell,
            "vin": fall.vin,
            "kennzeichen": fall.kennzeichen,
            "erstzulassung": fall.erstzulassung.isoformat(),
            "laufleistung_km": fall.laufleistung,
        },
        "saetze": {
            "mechanik": str(fall.saetze["mechanik"]),
            "karosserie": str(fall.saetze["karosserie"]),
            "elektrik": str(fall.saetze["elektrik"]),
            "lack_lohn": str(fall.saetze["lack_lohn"]),
            "lack_material_prozent": str(fall.saetze["lack_material_prozent"]),
            "upe_aufschlag_prozent": str(fall.saetze["upe_aufschlag_prozent"]),
            "verbringung": str(fall.saetze["verbringung"]),
        },
        "positionen": [
            {
                "laufnummer": z.nummer,
                "art": z.art,
                "bezeichnung": z.bezeichnung,
                "teilenummer": z.teilenummer,
                "arbeitswerte": str(z.arbeitswerte) if z.arbeitswerte is not None else None,
                "stundensatz": str(z.stundensatz) if z.stundensatz is not None else None,
                "lackstufe": z.lackstufe,
                "einzelpreis": str(z.einzelpreis) if z.einzelpreis is not None else None,
                "aufschlag_prozent": (
                    str(z.aufschlag_prozent) if z.aufschlag_prozent is not None else None
                ),
                "betrag": str(z.betrag),
            }
            for z in fall.zeilen
        ],
        "summen": {
            "ersatzteile": str(fall.summe("ERSATZTEIL")),
            "arbeit": str(fall.summe("ARBEIT")),
            "lack": str(fall.summe("LACK")),
            "nebenkosten": str(fall.summe("NEBENKOSTEN")),
            "netto": str(fall.netto),
            "mehrwertsteuer": str(fall.mehrwertsteuer),
            "brutto": str(fall.brutto),
        },
    }


def _schreiben(name: str, inhalt: str | bytes, golden_daten: dict[str, Any]) -> None:
    ziel = VERZEICHNIS / name
    if isinstance(inhalt, bytes):
        ziel.write_bytes(inhalt)
    else:
        ziel.write_text(inhalt, encoding="utf-8")
    (VERZEICHNIS / f"{ziel.stem}.golden.json").write_text(
        json.dumps(golden_daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def erzeugen(mit_pdf: bool = True) -> list[str]:
    """Baut den vollständigen Korpus. Deterministisch über feste Startwerte."""
    VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    for alt in VERZEICHNIS.glob("*"):
        alt.unlink()
    erzeugt: list[str] = []
    paare: list[dict[str, Any]] = []

    # 30 DAT-Dokumente: je zehn als TXT, PDF und VXS.
    for i in range(10):
        fall = fall_erzeugen(random.Random(1000 + i), i)
        _schreiben(f"dat_{i:02d}.txt", als_dat_text(fall), golden(fall, "DAT", "txt", "dat_txt"))
        erzeugt.append(f"dat_{i:02d}.txt")

    for i in range(10, 20):
        fall = fall_erzeugen(random.Random(1000 + i), i)
        text = als_dat_text(fall)
        if mit_pdf:
            _schreiben(f"dat_{i:02d}.pdf", text_als_pdf(text), golden(fall, "DAT", "pdf", "dat_pdf"))
            erzeugt.append(f"dat_{i:02d}.pdf")

    for i in range(20, 30):
        fall = fall_erzeugen(random.Random(1000 + i), i)
        _schreiben(f"dat_{i:02d}.vxs", als_vxs(fall), golden(fall, "DAT", "vxs", "dat_vxs"))
        erzeugt.append(f"dat_{i:02d}.vxs")

    # 10 Audatex-Dokumente als PDF.
    for i in range(10):
        fall = fall_erzeugen(random.Random(2000 + i), i)
        text = als_audatex_text(fall)
        if mit_pdf:
            _schreiben(
                f"audatex_{i:02d}.pdf",
                text_als_pdf(text),
                golden(fall, "AUDATEX", "pdf", "audatex_pdf"),
            )
            erzeugt.append(f"audatex_{i:02d}.pdf")

    # 15 Prüfberichte von zwei Absendern, jeweils mit der zugehörigen
    # eigenen Kalkulation als Paar für die Delta-Tests.
    for i in range(15):
        zufall = random.Random(3000 + i)
        eigen = fall_erzeugen(zufall, i)
        geprueft, kuerzungen = kuerzung_anwenden(eigen, zufall)
        absender = "controlexpert" if i < 8 else "eucon"
        adapter = f"pruefbericht_{'controlexpert' if i < 8 else 'generisch'}"

        eigen_name = f"paar_{i:02d}_eigen.txt"
        _schreiben(eigen_name, als_dat_text(eigen), golden(eigen, "DAT", "txt", "dat_txt"))
        bericht_name = f"paar_{i:02d}_pruefbericht.txt"
        _schreiben(
            bericht_name,
            als_pruefbericht_text(geprueft, eigen, absender),
            golden(geprueft, "PRUEFBERICHT", "txt", adapter),
        )
        erzeugt += [eigen_name, bericht_name]
        paare.append(
            {
                "eigen": eigen_name,
                "pruefbericht": bericht_name,
                "absender": absender,
                "differenz_netto": str(_r(eigen.netto - geprueft.netto)),
                "kuerzungen": [vars(k) for k in kuerzungen],
            }
        )

    (VERZEICHNIS / "paare.json").write_text(
        json.dumps(paare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return erzeugt


if __name__ == "__main__":
    dateien = erzeugen()
    print(f"{len(dateien)} Fixtures in {VERZEICHNIS}")
