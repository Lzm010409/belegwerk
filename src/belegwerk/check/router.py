"""Oberfläche von Check (Briefing Abschnitt 5)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

import yaml
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from belegwerk.check import dienst
from belegwerk.check.ausdruck import AusdruckFehler, felder_im_ausdruck
from belegwerk.check.extraktion import globaler_katalog
from belegwerk.check.modelle import CheckRegel, Pruefung, Regelherkunft
from belegwerk.check.regelmaschine import RegelFehler, Schwere, regel_aus_dict, startkatalog
from belegwerk.kern.abhaengigkeiten import BenutzerAbh, CsrfAbh, DatenbankAbh
from belegwerk.kern.abrechnung import schreibzugriff_pruefen, zugriff_pruefen
from belegwerk.kern.dateipruefung import DateiAbgelehnt
from belegwerk.kern.modelle import Mandant, Modul
from belegwerk.kern.ratenbegrenzung import UPLOAD, ZuVieleVersuche, pruefen_und_zaehlen
from belegwerk.web import pdf
from belegwerk.web.kontext import antworten, antwort_mit_meldung

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/app/check", tags=["check"])

MODULE = {"check"}


def _seite(request: Request, benutzer: object, vorlage: str, kontext: dict[str, object], **rest: object) -> Response:
    return antworten(
        request, vorlage, kontext, benutzer=benutzer, modul="Check", module=MODULE, **rest  # type: ignore[arg-type]
    )


async def _module(sitzung: DatenbankAbh) -> set[str]:
    from belegwerk.kern.abrechnung import alle_zugriffe

    zugriffe = await alle_zugriffe(sitzung)
    return {modul.value for modul, zugriff in zugriffe.items() if zugriff.lesen}


@router.get("")
async def pruefen_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    zugriff = await zugriff_pruefen(sitzung, Modul.CHECK)
    regeln, fehlerhafte = await dienst.eigene_regeln(sitzung)
    letzte = (
        (
            await sitzung.execute(
                select(Pruefung).order_by(Pruefung.angelegt_am.desc()).limit(8)
            )
        )
        .scalars()
        .all()
    )
    return antworten(
        request,
        "check/pruefen.html",
        {
            "anzahl_regeln": len(regeln),
            "fehlerhafte_regeln": fehlerhafte,
            "letzte": letzte,
            "nur_lesbar": not zugriff.schreiben,
        },
        benutzer=benutzer,
        modul="Check",
        module=await _module(sitzung),
    )


@router.post("")
async def pruefung_starten(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    datei: Annotated[UploadFile, File()],
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.CHECK)
    try:
        pruefen_und_zaehlen("upload", str(benutzer.mandant_id), UPLOAD)
    except ZuVieleVersuche as fehler:
        return antwort_mit_meldung("/app/check", "fehler", str(fehler))

    inhalt = await datei.read()
    mandant = (
        await sitzung.execute(select(Mandant).where(Mandant.id == benutzer.mandant_id))
    ).scalar_one()
    try:
        pruefung = await dienst.pruefung_anlegen(
            sitzung,
            benutzer.mandant_id,
            benutzer.benutzer_id,
            datei.filename or "gutachten.pdf",
            inhalt,
            mandant.aktenzeichen_muster,
        )
    except DateiAbgelehnt as fehler:
        return antwort_mit_meldung("/app/check", "fehler", str(fehler))
    return antwort_mit_meldung(
        f"/app/check/pruefung/{pruefung.id}", "erfolg", "Die Prüfung ist abgeschlossen."
    )


@router.get("/pruefung/{pruefung_id}")
async def protokoll(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, pruefung_id: uuid.UUID
) -> Response:
    await zugriff_pruefen(sitzung, Modul.CHECK)
    pruefung = await dienst.pruefung_lesen(sitzung, pruefung_id)
    if pruefung is None:
        return antwort_mit_meldung("/app/check", "fehler", "Diese Prüfung gibt es nicht.")

    vorherige = None
    unterschied = None
    if pruefung.aktenzeichen:
        alle = await dienst.historie(sitzung, pruefung.aktenzeichen)
        aeltere = [p for p in alle if p.angelegt_am < pruefung.angelegt_am]
        if aeltere:
            vorherige = aeltere[0]
            unterschied = dienst.vergleich(pruefung, vorherige)

    return antworten(
        request,
        "check/protokoll.html",
        {
            "pruefung": pruefung,
            "gruppen": _gruppieren(pruefung),
            "vorherige": vorherige,
            "unterschied": unterschied,
            "katalog": {d.feld: d.label for d in globaler_katalog()},
        },
        benutzer=benutzer,
        modul="Check",
        module=await _module(sitzung),
    )


def _gruppieren(pruefung: Pruefung) -> dict[Schwere, list[object]]:
    gruppen: dict[Schwere, list[object]] = {s: [] for s in Schwere}
    for befund in sorted(pruefung.befunde, key=lambda b: (b.schwere.rang, b.nummer)):
        gruppen[befund.schwere].append(befund)
    return gruppen


@router.post("/befund/{befund_id}/quittieren")
async def befund_quittieren(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    befund_id: uuid.UUID,
    grund: Annotated[str, Form()],
    pruefung_id: Annotated[uuid.UUID, Form()],
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.CHECK)
    try:
        await dienst.quittieren(sitzung, befund_id, benutzer.benutzer_id, grund)
    except (ValueError, LookupError) as fehler:
        return antwort_mit_meldung(f"/app/check/pruefung/{pruefung_id}", "fehler", str(fehler))
    return antwort_mit_meldung(
        f"/app/check/pruefung/{pruefung_id}", "erfolg", "Der Befund ist quittiert."
    )


@router.get("/pruefung/{pruefung_id}/protokoll.pdf")
async def protokoll_pdf(
    benutzer: BenutzerAbh, sitzung: DatenbankAbh, pruefung_id: uuid.UUID
) -> Response:
    await zugriff_pruefen(sitzung, Modul.CHECK)
    pruefung = await dienst.pruefung_lesen(sitzung, pruefung_id)
    if pruefung is None:
        return Response("Diese Prüfung gibt es nicht.", status_code=404)
    mandant = (
        await sitzung.execute(select(Mandant).where(Mandant.id == benutzer.mandant_id))
    ).scalar_one()
    daten = await run_in_threadpool(
        pdf.aus_vorlage,
        "pdf/check_protokoll.html",
        {
            "pruefung": pruefung,
            "gruppen": _gruppieren(pruefung),
            "mandant": mandant,
            "logo": pdf.logo_datei_uri(mandant.logo_pfad),
            "katalog": {d.feld: d.label for d in globaler_katalog()},
        },
    )
    name = f"pruefprotokoll-{(pruefung.aktenzeichen or str(pruefung.id)[:8]).replace('/', '-')}.pdf"
    return Response(
        daten,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- Regelverwaltung ------------------------------------------------------


@router.get("/regeln")
async def regeln_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    await zugriff_pruefen(sitzung, Modul.CHECK)
    eintraege = {
        e.kennung: e for e in (await sitzung.execute(select(CheckRegel))).scalars().all()
    }
    global_regeln = [
        {"regel": regel, "aktiv": eintraege.get(regel.id, None) is None or eintraege[regel.id].aktiv}
        for regel in startkatalog()
    ]
    eigene = [e for e in eintraege.values() if e.herkunft is Regelherkunft.EIGEN]
    return antworten(
        request,
        "check/regeln.html",
        {
            "global_regeln": global_regeln,
            "eigene": eigene,
            "felder": sorted(d.feld for d in globaler_katalog()),
        },
        benutzer=benutzer,
        modul="Check",
        module=await _module(sitzung),
    )


@router.post("/regeln/{kennung}/schalten")
async def regel_schalten(
    _csrf: CsrfAbh, benutzer: BenutzerAbh, sitzung: DatenbankAbh, kennung: str
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.CHECK)
    eintrag = (
        await sitzung.execute(select(CheckRegel).where(CheckRegel.kennung == kennung))
    ).scalar_one_or_none()
    if eintrag is None:
        sitzung.add(
            CheckRegel(
                mandant_id=benutzer.mandant_id,
                kennung=kennung,
                herkunft=Regelherkunft.GLOBAL,
                aktiv=False,
            )
        )
        zustand = "abgeschaltet"
    else:
        eintrag.aktiv = not eintrag.aktiv
        zustand = "eingeschaltet" if eintrag.aktiv else "abgeschaltet"
    await sitzung.flush()
    return antwort_mit_meldung("/app/check/regeln", "erfolg", f"Regel {kennung} {zustand}.")


@router.post("/regeln/eigene")
async def eigene_regel_anlegen(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    kennung: Annotated[str, Form()],
    titel: Annotated[str, Form()],
    schwere: Annotated[str, Form()],
    wenn: Annotated[str, Form()],
    meldung: Annotated[str, Form()],
) -> Response:
    await schreibzugriff_pruefen(sitzung, Modul.CHECK)
    daten: dict[str, object] = {
        "id": kennung.strip(),
        "nummer": 0,
        "schwere": schwere,
        "titel": titel.strip(),
        "wenn": wenn.strip(),
        "meldung": meldung.strip(),
        "felder": [],
    }
    try:
        # Beides innerhalb des try: schon das Ermitteln der Felder uebersetzt den
        # Ausdruck und weist damit alles zurueck, was kein Regelausdruck ist.
        daten["felder"] = sorted(felder_im_ausdruck(wenn))
        regel_aus_dict(daten, mandant_eigen=True)
    except (RegelFehler, AusdruckFehler) as fehler:
        return antwort_mit_meldung("/app/check/regeln", "fehler", str(fehler))
    if kennung.strip() in {r.id for r in startkatalog()}:
        return antwort_mit_meldung(
            "/app/check/regeln", "fehler", "Diese Kennung ist im Startkatalog belegt."
        )
    sitzung.add(
        CheckRegel(
            mandant_id=benutzer.mandant_id,
            kennung=kennung.strip(),
            herkunft=Regelherkunft.EIGEN,
            aktiv=True,
            yaml_quelle=yaml.safe_dump(daten, allow_unicode=True, sort_keys=False),
        )
    )
    await sitzung.flush()
    return antwort_mit_meldung("/app/check/regeln", "erfolg", "Die Regel ist angelegt.")


# --- Historie -------------------------------------------------------------


@router.get("/historie")
async def historie_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh, suche: str = ""
) -> Response:
    await zugriff_pruefen(sitzung, Modul.CHECK)
    anfrage = select(Pruefung).order_by(Pruefung.angelegt_am.desc()).limit(200)
    if suche.strip():
        anfrage = anfrage.where(Pruefung.aktenzeichen.ilike(f"%{suche.strip()}%"))
    pruefungen = list((await sitzung.execute(anfrage)).scalars().all())
    return antworten(
        request,
        "check/historie.html",
        {"pruefungen": pruefungen, "suche": suche},
        benutzer=benutzer,
        modul="Check",
        module=await _module(sitzung),
    )
