"""Oberfläche von Delta — vier Ansichten, mehr nicht (Briefing Abschnitt 4)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from belegwerk.delta import dienst
from belegwerk.delta.klassifikation import Klasse
from belegwerk.delta.modelle import Dokumentrolle, Position, Vorgang, VorgangStatus
from belegwerk.kern.abhaengigkeiten import BenutzerAbh, CsrfAbh, DatenbankAbh
from belegwerk.kern.abrechnung import alle_zugriffe, schreibzugriff_pruefen, zugriff_pruefen
from belegwerk.kern.auftraege import auftrag_lesen
from belegwerk.kern.dateipruefung import DateiAbgelehnt
from belegwerk.kern.modelle import Mandant, Modul
from belegwerk.kern.ratenbegrenzung import UPLOAD, ZuVieleVersuche, pruefen_und_zaehlen
from belegwerk.web import pdf
from belegwerk.web.kontext import antworten, antwort_mit_meldung

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/app/delta", tags=["delta"])


async def _module(sitzung: AsyncSession) -> set[str]:
    zugriffe = await alle_zugriffe(sitzung)
    return {modul.value for modul, zugriff in zugriffe.items() if zugriff.lesen}


@router.get("")
async def neuer_vergleich(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    zugriff = await zugriff_pruefen(sitzung, Modul.DELTA)
    letzte = (
        (await sitzung.execute(select(Vorgang).order_by(Vorgang.angelegt_am.desc()).limit(8)))
        .scalars()
        .all()
    )
    return antworten(
        request,
        "delta/neu.html",
        {"letzte": letzte, "nur_lesbar": not zugriff.schreiben},
        benutzer=benutzer,
        modul="Delta",
        module=await _module(sitzung),
    )


@router.post("")
async def vergleich_starten(
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    eigen: Annotated[UploadFile, File()],
    pruefbericht: Annotated[UploadFile, File()],
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.DELTA)
    try:
        pruefen_und_zaehlen("upload", str(benutzer.mandant_id), UPLOAD)
    except ZuVieleVersuche as fehler:
        return antwort_mit_meldung("/app/delta", "fehler", str(fehler))
    try:
        vorgang = await dienst.vorgang_anlegen(
            sitzung,
            benutzer.mandant_id,
            benutzer.benutzer_id,
            dienst.Hochgeladen(eigen.filename or "kalkulation", await eigen.read()),
            dienst.Hochgeladen(pruefbericht.filename or "pruefbericht", await pruefbericht.read()),
        )
    except DateiAbgelehnt as fehler:
        return antwort_mit_meldung("/app/delta", "fehler", str(fehler))
    return antwort_mit_meldung(
        f"/app/delta/vorgang/{vorgang.id}", "erfolg", "Die Dokumente werden verarbeitet."
    )


@router.get("/vorgang/{vorgang_id}")
async def vorgang_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, vorgang_id: uuid.UUID
) -> Response:
    await zugriff_pruefen(sitzung, Modul.DELTA)
    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is None:
        return antwort_mit_meldung("/app/delta", "fehler", "Diesen Vorgang gibt es nicht.")

    if vorgang.status in {VorgangStatus.ANGELEGT, VorgangStatus.VERARBEITUNG}:
        auftrag = await auftrag_lesen(sitzung, vorgang.auftrag_id) if vorgang.auftrag_id else None
        return antworten(
            request,
            "delta/verarbeitung.html",
            {"vorgang": vorgang, "auftrag": auftrag},
            benutzer=benutzer,
            modul="Delta",
            module=await _module(sitzung),
        )

    if vorgang.status is VorgangStatus.FEHLGESCHLAGEN:
        return antworten(
            request,
            "delta/fehlgeschlagen.html",
            {"vorgang": vorgang},
            benutzer=benutzer,
            modul="Delta",
            module=await _module(sitzung),
        )

    klasse_filter = request.query_params.get("klasse", "")
    gruppen = dienst.nach_klasse(vorgang)
    if klasse_filter:
        gruppen = {k: v for k, v in gruppen.items() if k.value == klasse_filter}
    return antworten(
        request,
        "delta/delta.html",
        {
            "vorgang": vorgang,
            "gruppen": gruppen,
            "alle_klassen": dienst.nach_klasse(vorgang),
            "ergebnis": vorgang.ergebnis or {},
            "klasse_filter": klasse_filter,
            "eigen": vorgang.dokument(Dokumentrolle.EIGEN),
            "pruefbericht": vorgang.dokument(Dokumentrolle.PRUEFBERICHT),
        },
        benutzer=benutzer,
        modul="Delta",
        module=await _module(sitzung),
    )


@router.get("/vorgang/{vorgang_id}/fortschritt")
async def fortschritt(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, vorgang_id: uuid.UUID
) -> Response:
    """HTMX-Polling während der Verarbeitung."""
    await zugriff_pruefen(sitzung, Modul.DELTA)
    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is None:
        return Response("", status_code=404)
    auftrag = await auftrag_lesen(sitzung, vorgang.auftrag_id) if vorgang.auftrag_id else None
    antwort = antworten(
        request,
        "delta/teile/fortschritt.html",
        {"vorgang": vorgang, "auftrag": auftrag},
        benutzer=benutzer,
    )
    if vorgang.status not in {VorgangStatus.ANGELEGT, VorgangStatus.VERARBEITUNG}:
        antwort.headers["HX-Redirect"] = f"/app/delta/vorgang/{vorgang.id}"
    return antwort


@router.get("/vorgang/{vorgang_id}/korrektur")
async def korrekturansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, vorgang_id: uuid.UUID
) -> Response:
    """Nur nötig bei niedriger Konfidenz — aber dann Kernfunktion."""
    await zugriff_pruefen(sitzung, Modul.DELTA)
    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is None:
        return antwort_mit_meldung("/app/delta", "fehler", "Diesen Vorgang gibt es nicht.")
    return antworten(
        request,
        "delta/korrektur.html",
        {
            "vorgang": vorgang,
            "eigen": vorgang.dokument(Dokumentrolle.EIGEN),
            "pruefbericht": vorgang.dokument(Dokumentrolle.PRUEFBERICHT),
        },
        benutzer=benutzer,
        modul="Delta",
        module=await _module(sitzung),
    )


@router.post("/position/{position_id}")
async def position_speichern(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    position_id: uuid.UUID,
    vorgang_id: Annotated[uuid.UUID, Form()],
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.DELTA)
    formular = await request.form()
    aenderungen = {
        name: str(wert)
        for name, wert in formular.items()
        if name in {"bezeichnung", "teilenummer", "arbeitswerte", "stundensatz", "lackstufe", "einzelpreis", "aufschlag_prozent", "betrag"}
    }
    try:
        await dienst.position_korrigieren(
            sitzung, benutzer.mandant_id, benutzer.benutzer_id, position_id, aenderungen
        )
    except LookupError as fehler:
        return antwort_mit_meldung(f"/app/delta/vorgang/{vorgang_id}/korrektur", "fehler", str(fehler))

    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is not None:
        await sitzung.refresh(vorgang)
        await dienst.neu_auswerten(sitzung, vorgang, benutzer.mandant_id)
    return antwort_mit_meldung(
        f"/app/delta/vorgang/{vorgang_id}/korrektur", "erfolg", "Die Korrektur ist übernommen."
    )


@router.get("/vorgang/{vorgang_id}/anlage.pdf")
async def anlage_pdf(
    benutzer: BenutzerAbh, sitzung: DatenbankAbh, vorgang_id: uuid.UUID
) -> Response:
    await zugriff_pruefen(sitzung, Modul.DELTA)
    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is None:
        return Response("Diesen Vorgang gibt es nicht.", status_code=404)
    mandant = (
        await sitzung.execute(select(Mandant).where(Mandant.id == benutzer.mandant_id))
    ).scalar_one()
    daten = await run_in_threadpool(
        pdf.aus_vorlage,
        "pdf/delta_anlage.html",
        {
            "vorgang": vorgang,
            "gruppen": dienst.nach_klasse(vorgang),
            "ergebnis": vorgang.ergebnis or {},
            "mandant": mandant,
            "logo": pdf.logo_datei_uri(mandant.logo_pfad),
            "eigen": vorgang.dokument(Dokumentrolle.EIGEN),
            "pruefbericht": vorgang.dokument(Dokumentrolle.PRUEFBERICHT),
        },
    )
    name = f"delta-{(vorgang.aktenzeichen or str(vorgang.id)[:8]).replace('/', '-')}.pdf"
    return Response(
        daten,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/vorgang/{vorgang_id}/export.json")
async def export_json(
    benutzer: BenutzerAbh, sitzung: DatenbankAbh, vorgang_id: uuid.UUID
) -> Response:
    await zugriff_pruefen(sitzung, Modul.DELTA)
    vorgang = await _vorgang(sitzung, vorgang_id)
    if vorgang is None:
        return Response('{"fehler": "unbekannter Vorgang"}', status_code=404, media_type="application/json")
    name = f"delta-{(vorgang.aktenzeichen or str(vorgang.id)[:8]).replace('/', '-')}.json"
    return Response(
        dienst.json_text(vorgang),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/archiv")
async def archiv(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, suche: str = ""
) -> Response:
    await zugriff_pruefen(sitzung, Modul.DELTA)
    anfrage = select(Vorgang).order_by(Vorgang.angelegt_am.desc()).limit(200)
    if suche.strip():
        muster = f"%{suche.strip()}%"
        anfrage = anfrage.where(
            or_(Vorgang.aktenzeichen.ilike(muster), Vorgang.kennzeichen.ilike(muster))
        )
    vorgaenge = list((await sitzung.execute(anfrage)).scalars().all())
    return antworten(
        request,
        "delta/archiv.html",
        {"vorgaenge": vorgaenge, "suche": suche, "klassen": list(Klasse)},
        benutzer=benutzer,
        modul="Delta",
        module=await _module(sitzung),
    )


async def _vorgang(sitzung: AsyncSession, vorgang_id: uuid.UUID) -> Vorgang | None:
    gefunden: Vorgang | None = (
        await sitzung.execute(select(Vorgang).where(Vorgang.id == vorgang_id))
    ).scalar_one_or_none()
    return gefunden
