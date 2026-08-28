"""Oberfläche von Atlas (Briefing Abschnitt 6)."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from belegwerk.atlas import dienst, geo, pool
from belegwerk.atlas.diagramm import verteilung_svg
from belegwerk.atlas.modelle import Betriebsart, Erhebung, Erhebungsart
from belegwerk.atlas.statistik import MINDESTANZAHL
from belegwerk.kern.abhaengigkeiten import BenutzerAbh, CsrfAbh, DatenbankAbh
from belegwerk.kern.abrechnung import alle_zugriffe, schreibzugriff_pruefen, zugriff_pruefen
from belegwerk.kern.dateipruefung import DateiAbgelehnt
from belegwerk.kern.formate import zahl_lesen
from belegwerk.kern.modelle import Mandant, Modul
from belegwerk.web import pdf
from belegwerk.web.kontext import antworten, antwort_mit_meldung

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/app/atlas", tags=["atlas"])


async def _module(sitzung: AsyncSession) -> set[str]:
    zugriffe = await alle_zugriffe(sitzung)
    return {modul.value for modul, zugriff in zugriffe.items() if zugriff.lesen}


def _datum(roh: str) -> date:
    for muster in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(roh.strip(), muster).date()
        except ValueError:
            continue
    raise dienst.ErhebungUnvollstaendig("Das Erhebungsdatum ist nicht lesbar (TT.MM.JJJJ).")


@router.get("")
async def erfassen_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, suche: str = ""
) -> Response:
    zugriff = await zugriff_pruefen(sitzung, Modul.ATLAS)
    betriebe = await dienst.betrieb_suchen(sitzung, suche) if suche.strip() else []
    beitraege = await pool.beitragszaehler(benutzer.mandant_id)
    return antworten(
        request,
        "atlas/erfassen.html",
        {
            "betriebe": betriebe,
            "suche": suche,
            "betriebsarten": list(Betriebsart),
            "erhebungsarten": list(Erhebungsart),
            "heute": date.today().isoformat(),
            "nur_lesbar": not zugriff.schreiben,
            "beitraege": beitraege,
            "pool_freigegeben": pool.POOL_FREIGEGEBEN,
        },
        benutzer=benutzer,
        modul="Atlas",
        module=await _module(sitzung),
    )


@router.post("")
async def erfassen(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    name: Annotated[str, Form()],
    plz: Annotated[str, Form()],
    erhebungsdatum: Annotated[str, Form()],
    erhebungsart: Annotated[str, Form()],
    betriebsart: Annotated[str, Form()] = Betriebsart.FREI.value,
    ort: Annotated[str, Form()] = "",
    strasse: Annotated[str, Form()] = "",
    marken: Annotated[str, Form()] = "",
    bemerkung: Annotated[str, Form()] = "",
    im_pool: Annotated[str, Form()] = "",
    betrieb_id: Annotated[str, Form()] = "",
    nachweis: Annotated[UploadFile | None, File()] = None,
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.ATLAS)
    formular = await request.form()

    def satz(feld: str) -> Decimal | None:
        wert = formular.get(feld)
        return zahl_lesen(str(wert)) if isinstance(wert, str) and wert.strip() else None

    try:
        erfassung = dienst.Erfassung(
            betrieb_id=uuid.UUID(betrieb_id) if betrieb_id.strip() else None,
            name=name,
            strasse=strasse,
            plz=plz,
            ort=ort,
            betriebsart=Betriebsart(betriebsart),
            marken=[m for m in marken.split(",")],
            erhebungsdatum=_datum(erhebungsdatum),
            erhebungsart=Erhebungsart(erhebungsart),
            saetze={
                "satz_mechanik": satz("satz_mechanik"),
                "satz_karosserie": satz("satz_karosserie"),
                "satz_elektrik": satz("satz_elektrik"),
                "satz_lack_lohn": satz("satz_lack_lohn"),
                "lack_material_prozent": satz("lack_material_prozent"),
                "lack_material_pauschale": satz("lack_material_pauschale"),
                "upe_aufschlag_prozent": satz("upe_aufschlag_prozent"),
                "verbringung_pauschale": satz("verbringung_pauschale"),
                "entsorgung": satz("entsorgung"),
            },
            bemerkung=bemerkung,
            im_pool=bool(im_pool) and pool.POOL_FREIGEGEBEN,
        )
        beleg: tuple[str, bytes] | None = None
        if nachweis is not None and nachweis.filename:
            beleg = (nachweis.filename, await nachweis.read())
        await dienst.erhebung_anlegen(
            sitzung, benutzer.mandant_id, benutzer.benutzer_id, erfassung, beleg
        )
    except (dienst.ErhebungUnvollstaendig, DateiAbgelehnt, ValueError) as fehler:
        return antwort_mit_meldung("/app/atlas", "fehler", str(fehler))
    return antwort_mit_meldung("/app/atlas/erhebungen", "erfolg", "Die Erhebung ist gespeichert.")


@router.get("/betriebe")
async def betriebe_suchen(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, suche: str = ""
) -> Response:
    """HTMX-Teilantwort: Betriebssuche mit Dublettenwarnung."""
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    treffer = await dienst.betrieb_suchen(sitzung, suche) if suche.strip() else []
    return antworten(
        request, "atlas/teile/betriebe.html", {"betriebe": treffer, "suche": suche}, benutzer=benutzer
    )


@router.get("/auswertung")
async def auswertung_ansicht(
    request: Request,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    plz: str = "",
    radius: int = 30,
    betriebsart: str = "",
    marke: str = "",
    belastbarkeit: str = "",
    hoechstalter: str = "",
) -> Response:
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    bericht = None
    fehler = None
    if plz.strip():
        try:
            bericht = await dienst.auswerten(
                sitzung,
                benutzer.mandant_id,
                dienst.Filter(
                    plz=plz.strip(),
                    radius_km=max(1, min(200, radius)),
                    betriebsart=Betriebsart(betriebsart) if betriebsart else None,
                    marke=marke.strip() or None,
                    mindestbelastbarkeit=belastbarkeit or None,
                    hoechstalter_monate=int(hoechstalter) if hoechstalter.isdigit() else None,
                ),
            )
        except (geo.PlzUnbekannt, ValueError) as ausnahme:
            fehler = str(ausnahme)

    return antworten(
        request,
        "atlas/auswertung.html",
        {
            "bericht": bericht,
            "fehler": fehler,
            "plz": plz,
            "radius": radius,
            "betriebsart": betriebsart,
            "marke": marke,
            "belastbarkeit": belastbarkeit,
            "hoechstalter": hoechstalter,
            "betriebsarten": list(Betriebsart),
            "mindestanzahl": MINDESTANZAHL,
            "diagramme": (
                {k.feld: verteilung_svg(k) for k in bericht.ergebnis.kennzahlen}
                if bericht
                else {}
            ),
        },
        benutzer=benutzer,
        modul="Atlas",
        module=await _module(sitzung),
    )


def _filter_aus_parametern(
    plz: str, radius: int, betriebsart: str, marke: str, belastbarkeit: str, hoechstalter: str
) -> dienst.Filter:
    return dienst.Filter(
        plz=plz.strip(),
        radius_km=max(1, min(200, radius)),
        betriebsart=Betriebsart(betriebsart) if betriebsart else None,
        marke=marke.strip() or None,
        mindestbelastbarkeit=belastbarkeit or None,
        hoechstalter_monate=int(hoechstalter) if hoechstalter.isdigit() else None,
    )


@router.get("/auswertung.pdf")
async def auswertung_pdf(
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    plz: str,
    radius: int = 30,
    betriebsart: str = "",
    marke: str = "",
    belastbarkeit: str = "",
    hoechstalter: str = "",
) -> Response:
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    try:
        bericht = await dienst.auswerten(
            sitzung,
            benutzer.mandant_id,
            _filter_aus_parametern(plz, radius, betriebsart, marke, belastbarkeit, hoechstalter),
        )
    except geo.PlzUnbekannt as fehler:
        return Response(str(fehler), status_code=400)

    mandant = (
        await sitzung.execute(select(Mandant).where(Mandant.id == benutzer.mandant_id))
    ).scalar_one()
    await dienst.auswertung_speichern(sitzung, benutzer.mandant_id, benutzer.benutzer_id, bericht)
    daten = await run_in_threadpool(
        pdf.aus_vorlage,
        "pdf/atlas_auswertung.html",
        {
            "bericht": bericht,
            "mandant": mandant,
            "logo": pdf.logo_datei_uri(mandant.logo_pfad),
            "diagramme": {k.feld: verteilung_svg(k) for k in bericht.ergebnis.kennzahlen},
            "mindestanzahl": MINDESTANZAHL,
        },
    )
    return Response(
        daten,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="stundensaetze-{plz}-{radius}km.pdf"'},
    )


@router.get("/auswertung.csv")
async def auswertung_csv(
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    plz: str,
    radius: int = 30,
    betriebsart: str = "",
    marke: str = "",
    belastbarkeit: str = "",
    hoechstalter: str = "",
) -> Response:
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    try:
        bericht = await dienst.auswerten(
            sitzung,
            benutzer.mandant_id,
            _filter_aus_parametern(plz, radius, betriebsart, marke, belastbarkeit, hoechstalter),
        )
    except geo.PlzUnbekannt as fehler:
        return Response(str(fehler), status_code=400)
    return Response(
        dienst.als_csv(bericht).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="betriebe-{plz}-{radius}km.csv"'},
    )


@router.get("/erhebungen")
async def eigene_erhebungen(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    erhebungen = list(
        (
            await sitzung.execute(select(Erhebung).order_by(Erhebung.erhebungsdatum.desc()).limit(300))
        )
        .scalars()
        .all()
    )
    return antworten(
        request,
        "atlas/erhebungen.html",
        {
            "erhebungen": erhebungen,
            "beitraege": await pool.beitragszaehler(benutzer.mandant_id),
            "pool_freigegeben": pool.POOL_FREIGEGEBEN,
            "alterung_monate": dienst.ALTERUNG_MONATE,
        },
        benutzer=benutzer,
        modul="Atlas",
        module=await _module(sitzung),
    )


@router.post("/erhebung/{erhebung_id}/pool")
async def pool_schalten(
    _csrf: CsrfAbh, benutzer: BenutzerAbh, sitzung: DatenbankAbh, erhebung_id: uuid.UUID
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.ATLAS)
    if not pool.POOL_FREIGEGEBEN:
        return antwort_mit_meldung(
            "/app/atlas/erhebungen",
            "hinweis",
            "Der Pool ist noch nicht freigegeben. Bis zur wettbewerbsrechtlichen "
            "Prüfung bleiben alle Erhebungen ausschließlich in Ihrem Büro.",
        )
    erhebung = (
        await sitzung.execute(select(Erhebung).where(Erhebung.id == erhebung_id))
    ).scalar_one_or_none()
    if erhebung is None:
        return antwort_mit_meldung("/app/atlas/erhebungen", "fehler", "Diese Erhebung gibt es nicht.")
    erhebung.im_pool = not erhebung.im_pool
    await sitzung.flush()
    text = "steht jetzt im Pool" if erhebung.im_pool else "ist aus dem Pool genommen"
    return antwort_mit_meldung("/app/atlas/erhebungen", "erfolg", f"Die Erhebung {text}.")


@router.get("/karte")
async def karte(request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, plz: str = "", radius: int = 30) -> Response:
    await zugriff_pruefen(sitzung, Modul.ATLAS)
    bericht = None
    fehler = None
    if plz.strip():
        try:
            bericht = await dienst.auswerten(
                sitzung, benutzer.mandant_id, dienst.Filter(plz=plz.strip(), radius_km=radius)
            )
        except geo.PlzUnbekannt as ausnahme:
            fehler = str(ausnahme)
    return antworten(
        request,
        "atlas/karte.html",
        {"bericht": bericht, "fehler": fehler, "plz": plz, "radius": radius},
        benutzer=benutzer,
        modul="Atlas",
        module=await _module(sitzung),
    )
