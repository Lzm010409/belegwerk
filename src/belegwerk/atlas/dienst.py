"""Fachlicher Ablauf von Atlas: Erfassen, Auswerten, Ausgeben."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.atlas import geo
from belegwerk.atlas.modelle import (
    Auswertung,
    Betrieb,
    Betriebsart,
    Erhebung,
    Erhebungsart,
    Nachweis,
)
from belegwerk.atlas.pool import PoolErhebung, ist_teilnehmer, pooldaten
from belegwerk.atlas.statistik import (
    SATZARTEN,
    Auswertungsergebnis,
    Kennzahlen,
    kennzahlen_bilden,
)
from belegwerk.kern import ablage
from belegwerk.kern.dateipruefung import DateiAbgelehnt, pruefen as datei_pruefen
from belegwerk.kern.formate import jetzt

_log = logging.getLogger(__name__)

ALTERUNG_MONATE = 24
NACHWEIS_ARTEN = frozenset({"bild", "pdf"})


class ErhebungUnvollstaendig(Exception):
    """Ein Wert ohne Nachweisart wird nicht gespeichert (Briefing Abschnitt 2)."""


# ---------------------------------------------------------------------------
# Erfassen
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Erfassung:
    betrieb_id: uuid.UUID | None
    name: str
    strasse: str | None
    plz: str
    ort: str
    betriebsart: Betriebsart
    marken: list[str]
    erhebungsdatum: date
    erhebungsart: Erhebungsart
    saetze: dict[str, Decimal | None]
    bemerkung: str | None
    im_pool: bool


def _pruefen(erfassung: Erfassung) -> None:
    if not erfassung.name.strip():
        raise ErhebungUnvollstaendig("Ohne Betriebsnamen lässt sich die Erhebung nicht zuordnen.")
    if not erfassung.plz.strip().isdigit() or len(erfassung.plz.strip()) != 5:
        raise ErhebungUnvollstaendig("Die Postleitzahl muss fünfstellig sein.")
    if erfassung.erhebungsdatum > date.today():
        raise ErhebungUnvollstaendig("Das Erhebungsdatum liegt in der Zukunft.")
    if not any(wert is not None for wert in erfassung.saetze.values()):
        raise ErhebungUnvollstaendig(
            "Mindestens ein Satz muss eingetragen sein — sonst hat die Erhebung keinen Inhalt."
        )


async def duplikate(sitzung: AsyncSession, name: str, plz: str) -> list[Betrieb]:
    """Dublettenwarnung bei ähnlichem Namen und gleicher PLZ (Todo 2.2)."""
    from rapidfuzz import fuzz

    kandidaten = (
        (await sitzung.execute(select(Betrieb).where(Betrieb.plz == plz.strip()))).scalars().all()
    )
    gesucht = name.strip().lower()
    return [b for b in kandidaten if fuzz.token_sort_ratio(b.name.lower(), gesucht) >= 82]


async def erhebung_anlegen(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    benutzer_id: uuid.UUID,
    erfassung: Erfassung,
    nachweis: tuple[str, bytes] | None,
) -> Erhebung:
    """Legt Betrieb (falls nötig), Erhebung und Nachweis an.

    Der Nachweis ist bei den belastbaren Erhebungsarten Pflicht: genau daran
    scheitert die Verwertbarkeit vor Gericht.
    """
    _pruefen(erfassung)
    if erfassung.erhebungsart.nachweis_pflicht and nachweis is None:
        raise ErhebungUnvollstaendig(
            f"Für die Nachweisart „{erfassung.erhebungsart.beschriftung}" + "“ gehört das "
            "Dokument dazu — ohne Beleg ist die Erhebung als Anlage nicht verwertbar."
        )

    if erfassung.betrieb_id is not None:
        betrieb = (
            await sitzung.execute(select(Betrieb).where(Betrieb.id == erfassung.betrieb_id))
        ).scalar_one_or_none()
        if betrieb is None:
            raise ErhebungUnvollstaendig("Der gewählte Betrieb gehört nicht zu Ihrem Bestand.")
    else:
        punkt = geo.mittelpunkte().get(erfassung.plz.strip())
        betrieb = Betrieb(
            mandant_id=mandant_id,
            name=erfassung.name.strip(),
            strasse=(erfassung.strasse or "").strip() or None,
            plz=erfassung.plz.strip(),
            ort=erfassung.ort.strip() or (punkt.ort if punkt else ""),
            lat=punkt.lat if punkt else None,
            lon=punkt.lon if punkt else None,
            art=erfassung.betriebsart,
            marken=[m.strip() for m in erfassung.marken if m.strip()],
        )
        sitzung.add(betrieb)
        await sitzung.flush()

    erhebung = Erhebung(
        mandant_id=mandant_id,
        betrieb_id=betrieb.id,
        benutzer_id=benutzer_id,
        erhebungsdatum=erfassung.erhebungsdatum,
        art=erfassung.erhebungsart,
        bemerkung=(erfassung.bemerkung or "").strip() or None,
        im_pool=erfassung.im_pool,
        **{name: wert for name, wert in erfassung.saetze.items()},
    )
    sitzung.add(erhebung)
    await sitzung.flush()

    if nachweis is not None:
        dateiname, inhalt = nachweis
        await nachweis_anlegen(sitzung, mandant_id, erhebung, dateiname, inhalt)
    return erhebung


async def nachweis_anlegen(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    erhebung: Erhebung,
    dateiname: str,
    inhalt: bytes,
) -> Nachweis:
    """Speichert den Nachweis; Bilder werden vorher von Metadaten befreit."""
    datei_pruefen(inhalt, NACHWEIS_ARTEN)
    bereinigt, entfernt = exif_entfernen(inhalt)
    eintrag = ablage.speichern(mandant_id, bereinigt)
    nachweis = Nachweis(
        mandant_id=mandant_id,
        erhebung_id=erhebung.id,
        dateiname=dateiname[:300],
        hash=eintrag.sha256,
        pfad=str(eintrag.pfad),
        bytes_gross=eintrag.groesse,
        hochgeladen_am=jetzt(),
        exif_entfernt=entfernt,
    )
    sitzung.add(nachweis)
    await sitzung.flush()
    return nachweis


def exif_entfernen(inhalt: bytes) -> tuple[bytes, bool]:
    """Entfernt EXIF aus Bildern (Todo 1.4).

    Ein Foto vom Preisaushang trägt den Standort des Sachverständigen im
    Moment der Aufnahme. Das gehört nicht in eine Gutachtenanlage.
    """
    from belegwerk.kern.dateipruefung import art_bestimmen

    befund = art_bestimmen(inhalt)
    if befund.art != "bild":
        return inhalt, False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(inhalt)) as bild:
            ohne_daten = Image.new(bild.mode, bild.size)
            ohne_daten.putdata(list(bild.getdata()))
            puffer = io.BytesIO()
            ohne_daten.save(puffer, format=bild.format)
            return puffer.getvalue(), True
    except Exception as fehler:  # noqa: BLE001
        _log.warning("EXIF-Bereinigung fehlgeschlagen", extra={"fehlerart": type(fehler).__name__})
        raise DateiAbgelehnt(
            "Das Bild ließ sich nicht verarbeiten. Bitte als JPEG oder PNG erneut hochladen."
        ) from fehler


# ---------------------------------------------------------------------------
# Auswerten
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Filter:
    plz: str
    radius_km: int = 30
    betriebsart: Betriebsart | None = None
    marke: str | None = None
    mindestbelastbarkeit: str | None = None  # 'hoch' | 'mittel' | 'niedrig'
    hoechstalter_monate: int | None = None

    def als_dict(self) -> dict[str, Any]:
        return {
            "plz": self.plz,
            "radius_km": self.radius_km,
            "betriebsart": self.betriebsart.value if self.betriebsart else None,
            "marke": self.marke,
            "mindestbelastbarkeit": self.mindestbelastbarkeit,
            "hoechstalter_monate": self.hoechstalter_monate,
        }


@dataclass(slots=True)
class Betriebszeile:
    name: str
    strasse: str | None
    plz: str
    ort: str
    entfernung_km: float
    betriebsart: Betriebsart
    erhebungsdatum: date
    erhebungsart: Erhebungsart
    veraltet: bool
    eigen: bool
    saetze: dict[str, Decimal | None]


@dataclass(slots=True)
class Auswertungsbericht:
    filter: Filter
    zentrum: geo.Punkt
    ergebnis: Auswertungsergebnis
    zeilen: list[Betriebszeile]
    poolteilnahme: bool


_RANG = {"hoch": 0, "mittel": 1, "niedrig": 2}


def _passt(
    art: Erhebungsart, betriebsart: Betriebsart, marken: tuple[str, ...], filter_: Filter
) -> bool:
    if filter_.betriebsart is not None and betriebsart is not filter_.betriebsart:
        return False
    if filter_.marke and filter_.marke.lower() not in {m.lower() for m in marken}:
        return False
    if filter_.mindestbelastbarkeit:
        if _RANG[art.belastbarkeit] > _RANG[filter_.mindestbelastbarkeit]:
            return False
    return True


async def auswerten(
    sitzung: AsyncSession, mandant_id: uuid.UUID, filter_: Filter, stichtag: date | None = None
) -> Auswertungsbericht:
    """Umkreissuche, Statistik und Betriebsliste."""
    heute = stichtag or date.today()
    zentrum = geo.punkt(filter_.plz)
    umkreis = geo.plz_im_umkreis(filter_.plz, filter_.radius_km)

    eigene = (
        (
            await sitzung.execute(
                select(Erhebung, Betrieb)
                .join(Betrieb, Erhebung.betrieb_id == Betrieb.id)
                .where(Betrieb.plz.in_(set(umkreis)))
            )
        )
        .all()
    )

    zeilen: list[Betriebszeile] = []
    for erhebung, betrieb in eigene:
        if not _passt(erhebung.art, betrieb.art, tuple(betrieb.marken or ()), filter_):
            continue
        alter = (heute.year - erhebung.erhebungsdatum.year) * 12 + (
            heute.month - erhebung.erhebungsdatum.month
        )
        if filter_.hoechstalter_monate is not None and alter > filter_.hoechstalter_monate:
            continue
        zeilen.append(
            Betriebszeile(
                name=betrieb.name,
                strasse=betrieb.strasse,
                plz=betrieb.plz,
                ort=betrieb.ort,
                entfernung_km=umkreis.get(betrieb.plz, 0.0),
                betriebsart=betrieb.art,
                erhebungsdatum=erhebung.erhebungsdatum,
                erhebungsart=erhebung.art,
                veraltet=alter > ALTERUNG_MONATE,
                eigen=True,
                saetze={
                    feld: getattr(erhebung, feld) for feld, _ in SATZARTEN
                },
            )
        )

    poolteilnahme = await ist_teilnehmer(mandant_id)
    for eintrag in await pooldaten(mandant_id, set(umkreis)):
        if not _passt(eintrag.erhebungsart, eintrag.betriebsart, eintrag.marken, filter_):
            continue
        alter = (heute.year - eintrag.erhebungsdatum.year) * 12 + (
            heute.month - eintrag.erhebungsdatum.month
        )
        if filter_.hoechstalter_monate is not None and alter > filter_.hoechstalter_monate:
            continue
        zeilen.append(_pool_zu_zeile(eintrag, umkreis, alter))

    zeilen.sort(key=lambda z: (z.entfernung_km, z.name))
    return Auswertungsbericht(
        filter=filter_,
        zentrum=zentrum,
        ergebnis=_statistik(zeilen, heute, zentrum),
        zeilen=zeilen,
        poolteilnahme=poolteilnahme,
    )


def _pool_zu_zeile(
    eintrag: PoolErhebung, umkreis: dict[str, float], alter: int
) -> Betriebszeile:
    return Betriebszeile(
        name=eintrag.betrieb_name,
        strasse=eintrag.strasse,
        plz=eintrag.plz,
        ort=eintrag.ort,
        entfernung_km=umkreis.get(eintrag.plz, 0.0),
        betriebsart=eintrag.betriebsart,
        erhebungsdatum=eintrag.erhebungsdatum,
        erhebungsart=eintrag.erhebungsart,
        veraltet=alter > ALTERUNG_MONATE,
        eigen=False,
        saetze={feld: eintrag.wert(feld) for feld, _ in SATZARTEN},
    )


def _statistik(
    zeilen: list[Betriebszeile], heute: date, zentrum: geo.Punkt
) -> Auswertungsergebnis:
    kennzahlen: list[Kennzahlen] = []
    for feld, beschriftung in SATZARTEN:
        aktuelle = [
            wert
            for zeile in zeilen
            if not zeile.veraltet and (wert := zeile.saetze.get(feld)) is not None
        ]
        veraltete = sum(
            1 for zeile in zeilen if zeile.veraltet and zeile.saetze.get(feld) is not None
        )
        kennzahlen.append(kennzahlen_bilden(feld, beschriftung, aktuelle, veraltete))

    hinweise: list[str] = []
    if not zentrum.ist_genau:
        hinweise.append(
            f"Der Mittelpunkt der Postleitzahl {zentrum.plz} ist nur auf Leitregionsebene "
            "bekannt. Die Entfernungsangaben sind entsprechend grob."
        )
    veraltet_gesamt = sum(1 for zeile in zeilen if zeile.veraltet)
    if veraltet_gesamt:
        hinweise.append(
            f"{veraltet_gesamt} Erhebungen sind älter als {ALTERUNG_MONATE} Monate. Sie sind "
            "in der Liste ausgewiesen, zählen aber nicht in Median und Perzentile."
        )

    return Auswertungsergebnis(
        kennzahlen=kennzahlen,
        anzahl_betriebe=len({(z.name, z.plz) for z in zeilen}),
        anzahl_erhebungen=len(zeilen),
        anzahl_veraltet=veraltet_gesamt,
        stichtag=heute,
        hinweise=hinweise,
    )


async def auswertung_speichern(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    benutzer_id: uuid.UUID,
    bericht: Auswertungsbericht,
) -> Auswertung:
    eintrag = Auswertung(
        mandant_id=mandant_id,
        benutzer_id=benutzer_id,
        plz_zentrum=bericht.filter.plz,
        radius_km=bericht.filter.radius_km,
        filter=bericht.filter.als_dict(),
        ergebnis={
            "anzahl_betriebe": bericht.ergebnis.anzahl_betriebe,
            "anzahl_erhebungen": bericht.ergebnis.anzahl_erhebungen,
            "kennzahlen": [
                {
                    "feld": k.feld,
                    "anzahl": k.anzahl,
                    "median": str(k.median) if k.median is not None else None,
                    "p25": str(k.p25) if k.p25 is not None else None,
                    "p75": str(k.p75) if k.p75 is not None else None,
                    "minimum": str(k.minimum) if k.minimum is not None else None,
                    "maximum": str(k.maximum) if k.maximum is not None else None,
                }
                for k in bericht.ergebnis.kennzahlen
            ],
        },
    )
    sitzung.add(eintrag)
    await sitzung.flush()
    return eintrag


def als_csv(bericht: Auswertungsbericht) -> str:
    """CSV-Export der Betriebsliste (Todo 4.2)."""
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";")
    schreiber.writerow(
        ["Betrieb", "Strasse", "PLZ", "Ort", "Entfernung km", "Betriebsart", "Erhebungsdatum",
         "Nachweisart", "Belastbarkeit", "veraltet"]
        + [beschriftung for _, beschriftung in SATZARTEN]
    )
    for zeile in bericht.zeilen:
        schreiber.writerow(
            [
                zeile.name,
                zeile.strasse or "",
                zeile.plz,
                zeile.ort,
                f"{zeile.entfernung_km:.1f}".replace(".", ","),
                zeile.betriebsart.beschriftung,
                zeile.erhebungsdatum.strftime("%d.%m.%Y"),
                zeile.erhebungsart.beschriftung,
                zeile.erhebungsart.belastbarkeit,
                "ja" if zeile.veraltet else "nein",
            ]
            + [
                ("" if zeile.saetze.get(feld) is None else str(zeile.saetze[feld]).replace(".", ","))
                for feld, _ in SATZARTEN
            ]
        )
    return puffer.getvalue()


# ---------------------------------------------------------------------------
# Alterung
# ---------------------------------------------------------------------------


async def veraltete_erhebungen(sitzung: AsyncSession, stichtag: date | None = None) -> list[Erhebung]:
    grenze = (stichtag or date.today()) - timedelta(days=ALTERUNG_MONATE * 30)
    return list(
        (
            await sitzung.execute(
                select(Erhebung)
                .where(Erhebung.erhebungsdatum <= grenze)
                .order_by(Erhebung.erhebungsdatum)
            )
        )
        .scalars()
        .all()
    )


async def betrieb_suchen(sitzung: AsyncSession, suche: str) -> list[Betrieb]:
    muster = f"%{suche.strip()}%"
    return list(
        (
            await sitzung.execute(
                select(Betrieb)
                .where(or_(Betrieb.name.ilike(muster), Betrieb.plz.ilike(muster), Betrieb.ort.ilike(muster)))
                .order_by(Betrieb.name)
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
