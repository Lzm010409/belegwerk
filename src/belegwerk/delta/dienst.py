"""Fachlicher Ablauf von Delta: Vorgang anlegen, verarbeiten, exportieren.

Der Upload speichert nur; die Verarbeitung läuft als Hintergrundauftrag
(ADR 0003) und meldet ihren Fortschritt, den die Oberfläche per HTMX abfragt.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.delta import llm
from belegwerk.delta.klassifikation import Abweichung as Fachabweichung
from belegwerk.delta.klassifikation import Klasse, klassifizieren
from belegwerk.delta.modelle import (
    Abweichung,
    Dokument,
    Dokumentrolle,
    KorrekturLog,
    Position,
    Vorgang,
    VorgangStatus,
)
from belegwerk.delta.rechnung import Ergebnis, auswerten, satzvergleich
from belegwerk.delta.zuordnung import Paar, zuordnen
from belegwerk.dokumente.erkennung import KeinAdapter, verarbeiten
from belegwerk.dokumente.modell import Kalkulation
from belegwerk.dokumente.modell import Position as Fachposition
from belegwerk.kern import ablage, auftraege
from belegwerk.kern.dateipruefung import DateiAbgelehnt, pruefen as datei_pruefen
from belegwerk.kern.formate import jetzt
from belegwerk.kern.modelle import Mandant

_log = logging.getLogger(__name__)

AUFTRAGSART = "delta.vergleich"
ERLAUBTE_ARTEN = frozenset({"pdf", "text", "xml"})
SCHEMA = "belegwerk.delta/1"


# ---------------------------------------------------------------------------
# Anlegen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hochgeladen:
    dateiname: str
    inhalt: bytes


async def vorgang_anlegen(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    benutzer_id: uuid.UUID,
    eigen: Hochgeladen,
    pruefbericht: Hochgeladen,
) -> Vorgang:
    """Speichert beide Dokumente und stellt den Verarbeitungsauftrag ein."""
    for datei in (eigen, pruefbericht):
        datei_pruefen(datei.inhalt, ERLAUBTE_ARTEN)

    vorgang = Vorgang(
        mandant_id=mandant_id, benutzer_id=benutzer_id, status=VorgangStatus.ANGELEGT
    )
    sitzung.add(vorgang)
    await sitzung.flush()

    ablagen = {}
    for rolle, datei in ((Dokumentrolle.EIGEN, eigen), (Dokumentrolle.PRUEFBERICHT, pruefbericht)):
        eintrag = ablage.speichern(mandant_id, datei.inhalt)
        ablagen[rolle.value] = {
            "pfad": str(eintrag.pfad),
            "dateiname": datei.dateiname,
            "hash": eintrag.sha256,
        }

    auftrag = await auftraege.anlegen(
        sitzung,
        mandant_id,
        AUFTRAGSART,
        {"vorgang_id": str(vorgang.id), "dateien": ablagen},
    )
    vorgang.auftrag_id = auftrag.id
    vorgang.status = VorgangStatus.VERARBEITUNG
    await sitzung.flush()
    return vorgang


# ---------------------------------------------------------------------------
# Verarbeitung
# ---------------------------------------------------------------------------


def _positionsmodell(position: Position) -> Fachposition:
    """Aus der gespeicherten Zeile wieder das fachliche Modell — nach Korrekturen."""
    return Fachposition(
        laufnummer=position.laufnummer,
        art=position.art,
        bezeichnung=position.bezeichnung,
        betrag=position.betrag,
        teilenummer=position.teilenummer,
        arbeitswerte=position.arbeitswerte,
        stundensatz=position.stundensatz,
        lackstufe=position.lackstufe,
        einzelpreis=position.einzelpreis,
        aufschlag_prozent=position.aufschlag_prozent,
        rohzeile=position.rohzeile,
    )


def _kalkulation_aus_dokument(dokument: Dokument) -> Kalkulation:
    from belegwerk.dokumente.modell import Fahrzeug, Quelle, Summen, Verrechnungssaetze

    def dez(werte: dict[str, Any], name: str) -> Decimal | None:
        wert = werte.get(name)
        return Decimal(wert) if wert not in (None, "") else None

    saetze = dokument.saetze or {}
    summen = dokument.summen or {}
    fahrzeug = dokument.fahrzeug or {}
    return Kalkulation(
        quelle=Quelle.PRUEFBERICHT if dokument.rolle is Dokumentrolle.PRUEFBERICHT else Quelle.DAT,
        quellformat=dokument.quellformat,
        adapter=dokument.adapter,
        aktenzeichen=fahrzeug.get("aktenzeichen"),
        fahrzeug=Fahrzeug(
            hersteller=fahrzeug.get("hersteller"),
            modell=fahrzeug.get("modell"),
            vin=fahrzeug.get("vin"),
            kennzeichen=fahrzeug.get("kennzeichen"),
        ),
        saetze=Verrechnungssaetze(
            mechanik=dez(saetze, "mechanik"),
            karosserie=dez(saetze, "karosserie"),
            elektrik=dez(saetze, "elektrik"),
            lack_lohn=dez(saetze, "lack_lohn"),
            lack_material_prozent=dez(saetze, "lack_material_prozent"),
            upe_aufschlag_prozent=dez(saetze, "upe_aufschlag_prozent"),
            verbringung=dez(saetze, "verbringung"),
        ),
        positionen=[_positionsmodell(p) for p in dokument.positionen],
        summen=Summen(
            ersatzteile=dez(summen, "ersatzteile"),
            arbeit=dez(summen, "arbeit"),
            lack=dez(summen, "lack"),
            nebenkosten=dez(summen, "nebenkosten"),
            netto=dez(summen, "netto"),
            mehrwertsteuer=dez(summen, "mehrwertsteuer"),
            brutto=dez(summen, "brutto"),
        ),
        konfidenz=float(dokument.konfidenz),
    )


def _dokument_fuellen(
    dokument: Dokument, kalkulation: Kalkulation, mandant_id: uuid.UUID
) -> None:
    fahrzeug = kalkulation.fahrzeug
    dokument.quellformat = kalkulation.quellformat
    dokument.adapter = kalkulation.adapter
    dokument.konfidenz = kalkulation.konfidenz
    dokument.hinweise = list(kalkulation.hinweise)
    dokument.fahrzeug = {
        "aktenzeichen": kalkulation.aktenzeichen,
        "hersteller": fahrzeug.hersteller,
        "modell": fahrzeug.modell,
        "vin": fahrzeug.vin,
        "kennzeichen": fahrzeug.kennzeichen,
    }
    dokument.saetze = {
        name: (str(wert) if wert is not None else None)
        for name, wert in vars_of(kalkulation.saetze).items()
    }
    dokument.summen = {
        name: (str(wert) if wert is not None else None)
        for name, wert in vars_of(kalkulation.summen).items()
    }
    dokument.positionen = [
        Position(
            mandant_id=mandant_id,
            laufnummer=position.laufnummer,
            art=position.art,
            bezeichnung=position.bezeichnung[:400],
            teilenummer=position.teilenummer,
            arbeitswerte=position.arbeitswerte,
            stundensatz=position.stundensatz,
            lackstufe=position.lackstufe,
            einzelpreis=position.einzelpreis,
            aufschlag_prozent=position.aufschlag_prozent,
            betrag=position.betrag,
            rohzeile=position.rohzeile,
        )
        for position in kalkulation.positionen
    ]


def vars_of(objekt: Any) -> dict[str, Any]:
    """``vars()`` für ``slots``-Dataclasses."""
    return {name: getattr(objekt, name) for name in objekt.__slots__}


@auftraege.auftragsart(AUFTRAGSART)
async def vergleich_ausfuehren(kontext: auftraege.Auftragskontext) -> None:
    """Der Hintergrundauftrag: parsen, zuordnen, klassifizieren, rechnen."""
    vorgang_id = uuid.UUID(str(kontext.nutzlast["vorgang_id"]))
    try:
        await _vergleich_bauen(kontext, vorgang_id)
    except Exception as fehler:  # noqa: BLE001 — der Vorgang muss den Grund tragen
        await _als_fehlgeschlagen_vermerken(kontext.mandant_id, vorgang_id, fehler)
        raise


async def _als_fehlgeschlagen_vermerken(
    mandant_id: uuid.UUID, vorgang_id: uuid.UUID, fehler: Exception
) -> None:
    """Eigene Transaktion: die des Auftrags ist beim Fehler bereits verloren.

    Ohne diesen Schritt haenge der Vorgang fuer den Benutzer ewig auf
    „wird verarbeitet" — die schlechteste aller Rueckmeldungen.
    """
    from belegwerk.kern.mandantentrennung import mandanten_sitzung

    text = str(fehler) or type(fehler).__name__
    try:
        async with mandanten_sitzung(mandant_id) as sitzung:
            vorgang = (
                await sitzung.execute(select(Vorgang).where(Vorgang.id == vorgang_id))
            ).scalar_one_or_none()
            if vorgang is not None:
                vorgang.status = VorgangStatus.FEHLGESCHLAGEN
                vorgang.fehlertext = text[:2000]
    except Exception:  # noqa: BLE001
        _log.exception("Fehlerstatus konnte nicht gespeichert werden")


async def _vergleich_bauen(kontext: auftraege.Auftragskontext, vorgang_id: uuid.UUID) -> None:
    dateien: dict[str, dict[str, str]] = kontext.nutzlast["dateien"]
    sitzung = kontext.sitzung

    vorgang = (
        await sitzung.execute(select(Vorgang).where(Vorgang.id == vorgang_id))
    ).scalar_one()

    # Ein wiederholter Versuch darf keine zweite Garnitur Dokumente anlegen.
    for alt in list(vorgang.dokumente):
        await sitzung.delete(alt)
    await sitzung.flush()

    await kontext.melden(10, "Dokumente werden gelesen")
    for rolle in (Dokumentrolle.EIGEN, Dokumentrolle.PRUEFBERICHT):
        angaben = dateien[rolle.value]
        inhalt = ablage.lesen(kontext.mandant_id, angaben["pfad"])
        try:
            kalkulation = verarbeiten(inhalt)
        except (KeinAdapter, DateiAbgelehnt) as fehler:
            raise type(fehler)(f"{_rollenname(rolle)}: {fehler}") from fehler
        dokument = Dokument(
            mandant_id=kontext.mandant_id,
            vorgang_id=vorgang.id,
            rolle=rolle,
            dateiname=angaben["dateiname"][:300],
            dokument_hash=angaben["hash"],
            quellformat=kalkulation.quellformat,
            adapter=kalkulation.adapter,
            konfidenz=kalkulation.konfidenz,
            upload_pfad=angaben["pfad"],
        )
        _dokument_fuellen(dokument, kalkulation, kontext.mandant_id)
        sitzung.add(dokument)
        await kontext.melden(35 if rolle is Dokumentrolle.EIGEN else 55, "Dokument gelesen")
    await sitzung.flush()
    # Die Beziehung wurde beim Laden des Vorgangs gefuellt und kennt die eben
    # angelegten Dokumente noch nicht.
    await sitzung.refresh(vorgang, ["dokumente"])

    await kontext.melden(70, "Positionen werden zugeordnet")
    await neu_auswerten(sitzung, vorgang, kontext.mandant_id)
    await kontext.melden(100, "Vergleich fertig")


def _rollenname(rolle: Dokumentrolle) -> str:
    return "Ihre Kalkulation" if rolle is Dokumentrolle.EIGEN else "Der Prüfbericht"


async def neu_auswerten(
    sitzung: AsyncSession, vorgang: Vorgang, mandant_id: uuid.UUID
) -> Ergebnis:
    """Zuordnung, Klassifikation und Rechnung — auch nach einer Korrektur."""
    eigen_dokument = vorgang.dokument(Dokumentrolle.EIGEN)
    pruef_dokument = vorgang.dokument(Dokumentrolle.PRUEFBERICHT)
    assert eigen_dokument is not None and pruef_dokument is not None

    eigen = _kalkulation_aus_dokument(eigen_dokument)
    pruefbericht = _kalkulation_aus_dokument(pruef_dokument)

    mandant = (await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))).scalar_one()
    zuordner = llm.zuordner(mandant.llm_pfad_aktiv)

    paare = zuordnen(eigen.positionen, pruefbericht.positionen, zuordner)
    fachliche = [a for a in (klassifizieren(paar) for paar in paare) if a is not None]
    ergebnis = auswerten(eigen, pruefbericht, fachliche)

    for alt in list(vorgang.abweichungen):
        await sitzung.delete(alt)
    await sitzung.flush()

    nach_zeile = {
        (dokument.id, position.rohzeile, position.laufnummer, position.betrag): position.id
        for dokument in (eigen_dokument, pruef_dokument)
        for position in dokument.positionen
    }

    def kennung(dokument: Dokument, position: Fachposition | None) -> uuid.UUID | None:
        if position is None:
            return None
        return nach_zeile.get(
            (dokument.id, position.rohzeile, position.laufnummer, position.betrag)
        )

    for abweichung in fachliche:
        sitzung.add(
            Abweichung(
                mandant_id=mandant_id,
                vorgang_id=vorgang.id,
                position_a_id=kennung(eigen_dokument, abweichung.paar.a),
                position_b_id=kennung(pruef_dokument, abweichung.paar.b),
                klasse=abweichung.klasse,
                art=abweichung.art,
                laufnummer=abweichung.laufnummer,
                bezeichnung=abweichung.bezeichnung[:400],
                differenz_netto=abweichung.differenz_netto,
                wert_eigen=(abweichung.wert_eigen or "")[:120] or None,
                wert_pruefbericht=(abweichung.wert_pruefbericht or "")[:120] or None,
                beleg_eigen=abweichung.beleg_eigen,
                beleg_pruefbericht=abweichung.beleg_pruefbericht,
                match_stufe=abweichung.paar.stufe,
                match_konfidenz=Decimal(str(abweichung.paar.konfidenz)),
            )
        )

    vorgang.aktenzeichen = eigen.aktenzeichen or pruefbericht.aktenzeichen
    vorgang.kennzeichen = eigen.fahrzeug.kennzeichen or pruefbericht.fahrzeug.kennzeichen
    vorgang.ergebnis = _ergebnis_als_json(ergebnis, eigen, pruefbericht, paare)
    vorgang.status = (
        VorgangStatus.KORREKTUR_NOETIG
        if eigen.konfidenz < 0.85 or pruefbericht.konfidenz < 0.85
        else VorgangStatus.FERTIG
    )
    await sitzung.flush()
    return ergebnis


def _ergebnis_als_json(
    ergebnis: Ergebnis, eigen: Kalkulation, pruefbericht: Kalkulation, paare: list[Paar]
) -> dict[str, Any]:
    return {
        "eigen_netto": str(ergebnis.eigen_netto) if ergebnis.eigen_netto is not None else None,
        "pruefbericht_netto": (
            str(ergebnis.pruefbericht_netto) if ergebnis.pruefbericht_netto is not None else None
        ),
        "differenz_netto": str(ergebnis.differenz_netto),
        "differenz_brutto": str(ergebnis.differenz_brutto),
        "mehrwertsteuersatz": str(ergebnis.mehrwertsteuersatz),
        "kontrolle_geht_auf": ergebnis.kontrolle_geht_auf,
        "unerklaerter_rest": str(ergebnis.unerklaerter_rest),
        "hinweise": ergebnis.hinweise,
        "gruppen": [
            {
                "beschriftung": gruppe.beschriftung,
                "eigen": str(gruppe.eigen),
                "pruefbericht": str(gruppe.pruefbericht),
                "differenz": str(gruppe.differenz),
            }
            for gruppe in ergebnis.gruppen
        ],
        "saetze": [
            {"beschriftung": b, "eigen": e, "pruefbericht": p}
            for b, e, p in satzvergleich(eigen, pruefbericht)
        ],
        "zuordnung": {
            "gesamt": len(paare),
            "zugeordnet": sum(1 for p in paare if p.zugeordnet),
            "nur_eigen": sum(1 for p in paare if p.nur_in_a),
            "nur_pruefbericht": sum(1 for p in paare if p.nur_in_b),
            "je_stufe": {
                str(stufe): sum(1 for p in paare if p.stufe == stufe) for stufe in (1, 2, 3, 4, 5)
            },
        },
    }


# ---------------------------------------------------------------------------
# Korrekturansicht
# ---------------------------------------------------------------------------


async def position_korrigieren(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    benutzer_id: uuid.UUID,
    position_id: uuid.UUID,
    aenderungen: dict[str, str],
) -> Position:
    """Übernimmt Korrekturen und schreibt jede in den Korrekturlog."""
    from belegwerk.kern.formate import zahl_lesen

    position = (
        await sitzung.execute(select(Position).where(Position.id == position_id))
    ).scalar_one_or_none()
    if position is None:
        raise LookupError("Diese Position gehört nicht zu Ihren Vorgängen.")

    dezimalfelder = {"betrag", "arbeitswerte", "stundensatz", "einzelpreis", "aufschlag_prozent"}
    for feld, roh in aenderungen.items():
        if feld not in dezimalfelder | {"bezeichnung", "teilenummer", "lackstufe"}:
            continue
        alt = getattr(position, feld)
        if feld in dezimalfelder:
            neu: Any = zahl_lesen(roh)
            if feld == "betrag" and neu is None:
                continue
        elif feld == "lackstufe":
            neu = int(roh) if roh.strip().isdigit() else None
        else:
            neu = roh.strip() or None
        if str(alt) == str(neu):
            continue
        setattr(position, feld, neu)
        sitzung.add(
            KorrekturLog(
                mandant_id=mandant_id,
                dokument_id=position.dokument_id,
                position_id=position.id,
                feld=feld,
                wert_alt=None if alt is None else str(alt)[:400],
                wert_neu=None if neu is None else str(neu)[:400],
                benutzer_id=benutzer_id,
                zeit=jetzt(),
            )
        )
    await sitzung.flush()
    return position


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def als_json(vorgang: Vorgang) -> dict[str, Any]:
    """Stabiles Schema, damit ein Stellungnahme-Werkzeug dagegen programmieren kann."""
    eigen = vorgang.dokument(Dokumentrolle.EIGEN)
    fahrzeug = (eigen.fahrzeug if eigen else {}) or {}
    ergebnis = vorgang.ergebnis or {}
    return {
        "schema": SCHEMA,
        "vorgang_id": str(vorgang.id),
        "erstellt_am": vorgang.angelegt_am.isoformat() if vorgang.angelegt_am else None,
        "aktenzeichen": vorgang.aktenzeichen,
        "fahrzeug": {
            "hersteller": fahrzeug.get("hersteller"),
            "modell": fahrzeug.get("modell"),
            "vin": fahrzeug.get("vin"),
            "kennzeichen": fahrzeug.get("kennzeichen"),
        },
        "summen": {
            "eigen_netto": ergebnis.get("eigen_netto"),
            "pruefbericht_netto": ergebnis.get("pruefbericht_netto"),
            "differenz_netto": ergebnis.get("differenz_netto"),
            "differenz_brutto": ergebnis.get("differenz_brutto"),
        },
        "kontrollrechnung": {
            "geht_auf": ergebnis.get("kontrolle_geht_auf"),
            "unerklaerter_rest": ergebnis.get("unerklaerter_rest"),
        },
        "abweichungen": [
            {
                "klasse": abweichung.klasse.value,
                "bezeichnung": abweichung.bezeichnung,
                "laufnummer": abweichung.laufnummer,
                "art": abweichung.art.value,
                "wert_eigen": abweichung.wert_eigen,
                "wert_pruefbericht": abweichung.wert_pruefbericht,
                "differenz_netto": str(abweichung.differenz_netto),
                "beleg_eigen": abweichung.beleg_eigen,
                "beleg_pruefbericht": abweichung.beleg_pruefbericht,
                "match_stufe": abweichung.match_stufe,
                "match_konfidenz": str(abweichung.match_konfidenz),
            }
            for abweichung in sorted(
                vorgang.abweichungen, key=lambda a: (a.klasse.value, a.laufnummer)
            )
        ],
    }


def json_text(vorgang: Vorgang) -> str:
    return json.dumps(als_json(vorgang), ensure_ascii=False, indent=2)


def nach_klasse(vorgang: Vorgang) -> dict[Klasse, list[Abweichung]]:
    gruppen: dict[Klasse, list[Abweichung]] = {}
    for abweichung in sorted(vorgang.abweichungen, key=lambda a: a.laufnummer):
        gruppen.setdefault(abweichung.klasse, []).append(abweichung)
    return dict(sorted(gruppen.items(), key=lambda eintrag: eintrag[0].value))


__all__ = [
    "AUFTRAGSART",
    "Fachabweichung",
    "Hochgeladen",
    "als_json",
    "json_text",
    "nach_klasse",
    "neu_auswerten",
    "position_korrigieren",
    "vorgang_anlegen",
]
