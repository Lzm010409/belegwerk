"""Einstellungen, Benutzerverwaltung, Datenhoheit und Rückmeldung."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from belegwerk.kern import ablage, benutzerverwaltung, datenexport, mail, wartung
from belegwerk.kern.abhaengigkeiten import (
    BenutzerAbh,
    CsrfAbh,
    DatenbankAbh,
    InhaberAbh,
)
from belegwerk.kern.abrechnung import LISTENPREIS, MODULBESCHREIBUNG, MODULNAMEN, alle_zugriffe
from belegwerk.kern.dateipruefung import DateiAbgelehnt, pruefen as datei_pruefen
from belegwerk.kern.formate import datum_zeit, jetzt
from belegwerk.kern.modelle import Mandant, Rolle, Rueckmeldung
from belegwerk.konfiguration import einstellungen
from belegwerk.web.kontext import antworten, antwort_mit_meldung

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/app", tags=["kern"])


async def _module(sitzung: AsyncSession) -> set[str]:
    zugriffe = await alle_zugriffe(sitzung)
    return {modul.value for modul, zugriff in zugriffe.items() if zugriff.lesen}


async def _mandant(sitzung: AsyncSession, mandant_id: uuid.UUID) -> Mandant:
    return (await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))).scalar_one()


@router.get("/einstellungen")
async def einstellungen_ansicht(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    mandant = await _mandant(sitzung, benutzer.mandant_id)
    zugriffe = await alle_zugriffe(sitzung)
    return antworten(
        request,
        "kern/einstellungen.html",
        {
            "mandant": mandant,
            "zugriffe": list(zugriffe.values()),
            "namen": MODULNAMEN,
            "beschreibung": MODULBESCHREIBUNG,
            "preise": LISTENPREIS,
            "benutzer_liste": await benutzerverwaltung.benutzer_des_mandanten(sitzung),
            "einladungen": await benutzerverwaltung.offene_einladungen(sitzung),
            "llm_moeglich": bool(einstellungen().mistral_api_schluessel),
            "karenz_tage": einstellungen().konto_karenz_tage,
            "aufbewahrung_uploads": einstellungen().aufbewahrung_uploads_tage,
            "aufbewahrung_ergebnisse": einstellungen().aufbewahrung_ergebnisse_tage,
        },
        benutzer=benutzer,
        module=await _module(sitzung),
    )


@router.post("/einstellungen/buero")
async def buero_speichern(
    _csrf: CsrfAbh,
    inhaber: InhaberAbh,
    sitzung: DatenbankAbh,
    name: Annotated[str, Form()],
    briefkopf_zeilen: Annotated[str, Form()] = "",
    aktenzeichen_muster: Annotated[str, Form()] = "",
    llm_pfad_aktiv: Annotated[str, Form()] = "",
) -> Response:
    mandant = await _mandant(sitzung, inhaber.mandant_id)
    if not name.strip():
        return antwort_mit_meldung("/app/einstellungen", "fehler", "Der Büroname darf nicht leer sein.")
    if aktenzeichen_muster.strip():
        import re

        try:
            re.compile(aktenzeichen_muster.strip())
        except re.error as fehler:
            return antwort_mit_meldung(
                "/app/einstellungen",
                "fehler",
                f"Das Aktenzeichenmuster ist kein gültiger Ausdruck: {fehler}",
            )
    mandant.name = name.strip()[:200]
    mandant.briefkopf_zeilen = briefkopf_zeilen.strip() or None
    mandant.aktenzeichen_muster = aktenzeichen_muster.strip() or None
    mandant.llm_pfad_aktiv = bool(llm_pfad_aktiv) and bool(einstellungen().mistral_api_schluessel)
    await sitzung.flush()
    return antwort_mit_meldung("/app/einstellungen", "erfolg", "Die Einstellungen sind gespeichert.")


@router.post("/einstellungen/logo")
async def logo_hochladen(
    _csrf: CsrfAbh,
    inhaber: InhaberAbh,
    sitzung: DatenbankAbh,
    logo: Annotated[UploadFile, File()],
) -> Response:
    inhalt = await logo.read()
    try:
        datei_pruefen(inhalt, frozenset({"bild"}), max_bytes=2 * 1024 * 1024)
    except DateiAbgelehnt as fehler:
        return antwort_mit_meldung("/app/einstellungen", "fehler", str(fehler))
    mandant = await _mandant(sitzung, inhaber.mandant_id)
    if mandant.logo_pfad:
        ablage.loeschen(inhaber.mandant_id, mandant.logo_pfad, bereich="ausgaben")
    eintrag = ablage.speichern(inhaber.mandant_id, inhalt, bereich="ausgaben")
    mandant.logo_pfad = str(eintrag.pfad)
    await sitzung.flush()
    return antwort_mit_meldung("/app/einstellungen", "erfolg", "Das Logo ist hinterlegt.")


# --- Benutzerverwaltung ---------------------------------------------------


@router.post("/einstellungen/einladen")
async def einladen(
    _csrf: CsrfAbh,
    inhaber: InhaberAbh,
    sitzung: DatenbankAbh,
    email: Annotated[str, Form()],
    rolle: Annotated[str, Form()] = Rolle.MITARBEITER.value,
) -> Response:
    try:
        code = await benutzerverwaltung.einladen(
            sitzung, inhaber.mandant_id, inhaber.benutzer_id, email, Rolle(rolle)
        )
    except (benutzerverwaltung.VerwaltungFehler, ValueError) as fehler:
        return antwort_mit_meldung("/app/einstellungen", "fehler", str(fehler))

    mandant = await _mandant(sitzung, inhaber.mandant_id)
    link = f"{einstellungen().app_basis_url}/einladung/{code}"
    versendet = mail.senden(mail.einladung(email.strip(), mandant.name, link))
    text = (
        "Die Einladung ist versendet."
        if versendet
        else f"Kein Mailversand konfiguriert. Bitte diesen Link weitergeben: {link}"
    )
    return antwort_mit_meldung("/app/einstellungen", "erfolg" if versendet else "hinweis", text)


@router.post("/einstellungen/benutzer/{benutzer_id}/rolle")
async def rolle_setzen(
    _csrf: CsrfAbh,
    inhaber: InhaberAbh,
    sitzung: DatenbankAbh,
    benutzer_id: uuid.UUID,
    rolle: Annotated[str, Form()],
) -> Response:
    try:
        await benutzerverwaltung.rolle_aendern(
            sitzung, benutzer_id, Rolle(rolle), inhaber.benutzer_id
        )
    except (benutzerverwaltung.VerwaltungFehler, ValueError) as fehler:
        return antwort_mit_meldung("/app/einstellungen", "fehler", str(fehler))
    return antwort_mit_meldung("/app/einstellungen", "erfolg", "Die Rolle ist geändert.")


@router.post("/einstellungen/benutzer/{benutzer_id}/sperren")
async def zugang_schalten(
    _csrf: CsrfAbh, inhaber: InhaberAbh, sitzung: DatenbankAbh, benutzer_id: uuid.UUID
) -> Response:
    try:
        benutzer = await benutzerverwaltung.zugang_sperren(
            sitzung, benutzer_id, inhaber.benutzer_id
        )
    except benutzerverwaltung.VerwaltungFehler as fehler:
        return antwort_mit_meldung("/app/einstellungen", "fehler", str(fehler))
    zustand = "wieder freigeschaltet" if benutzer.aktiv else "gesperrt"
    return antwort_mit_meldung("/app/einstellungen", "erfolg", f"Der Zugang ist {zustand}.")


# --- Datenhoheit ----------------------------------------------------------


@router.get("/einstellungen/datenexport.zip")
async def datenexport_herunterladen(benutzer: BenutzerAbh, sitzung: DatenbankAbh) -> Response:
    daten = await datenexport.archiv_bauen(sitzung, benutzer.mandant_id)
    name = f"belegwerk-export-{jetzt().date().isoformat()}.zip"
    _log.info("Datenexport erstellt", extra={"mandant_id": str(benutzer.mandant_id)})
    return Response(
        daten,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/einstellungen/konto-loeschen")
async def konto_loeschen(
    _csrf: CsrfAbh,
    inhaber: InhaberAbh,
    sitzung: DatenbankAbh,
    bestaetigung: Annotated[str, Form()] = "",
) -> Response:
    mandant = await _mandant(sitzung, inhaber.mandant_id)
    if bestaetigung.strip().upper() != "LOESCHEN":
        return antwort_mit_meldung(
            "/app/einstellungen",
            "fehler",
            "Zum Bestätigen bitte das Wort LOESCHEN eintragen.",
        )
    await wartung.loeschung_beantragen(inhaber.mandant_id)
    karenz = einstellungen().konto_karenz_tage
    return antwort_mit_meldung(
        "/app/einstellungen",
        "hinweis",
        f"Die Löschung ist beantragt. In {karenz} Tagen werden alle Daten von "
        f"{mandant.name} unwiderruflich entfernt. Bis dahin können Sie das hier widerrufen.",
    )


@router.post("/einstellungen/loeschung-widerrufen")
async def loeschung_widerrufen(_csrf: CsrfAbh, inhaber: InhaberAbh) -> Response:
    await wartung.loeschung_widerrufen(inhaber.mandant_id)
    return antwort_mit_meldung("/app/einstellungen", "erfolg", "Die Löschung ist widerrufen.")


# --- Rückmeldung ----------------------------------------------------------


@router.get("/rueckmeldung")
async def rueckmeldung_formular(
    request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh
) -> Response:
    return antworten(
        request,
        "kern/rueckmeldung.html",
        {"von": request.headers.get("referer", "")},
        benutzer=benutzer,
        module=await _module(sitzung),
    )


@router.post("/rueckmeldung")
async def rueckmeldung_senden(
    _csrf: CsrfAbh,
    benutzer: BenutzerAbh,
    sitzung: DatenbankAbh,
    text: Annotated[str, Form()],
    seite: Annotated[str, Form()] = "",
) -> Response:
    if not text.strip():
        return antwort_mit_meldung("/app/rueckmeldung", "fehler", "Die Rückmeldung ist leer.")
    sitzung.add(
        Rueckmeldung(
            mandant_id=benutzer.mandant_id,
            benutzer_id=benutzer.benutzer_id,
            seite=seite[:300] or None,
            text=text.strip(),
        )
    )
    await sitzung.flush()
    betreiber = einstellungen().betreiber_email
    if betreiber:
        mail.senden(
            mail.Nachricht(
                empfaenger=betreiber,
                betreff="Rückmeldung aus Belegwerk",
                text=(
                    f"Eingegangen am {datum_zeit(jetzt())}\n"
                    f"Seite: {seite or 'unbekannt'}\n\n{text.strip()}\n"
                ),
            )
        )
    return antwort_mit_meldung(
        "/app", "erfolg", "Danke — die Rückmeldung ist angekommen."
    )


# --- Betreiber-Auswertung -------------------------------------------------


@router.get("/betreiber")
async def betreiberauswertung(
    request: Request, inhaber: InhaberAbh, sitzung: DatenbankAbh
) -> Response:
    """Welche Regeln werden am häufigsten quittiert? (Check-Todo 4.2)

    Sichtbar für den Inhaber des eigenen Büros — die Zahlen beziehen sich
    ausschließlich auf die eigenen Prüfungen.
    """
    from sqlalchemy import func

    from belegwerk.check.modelle import Befund

    zeilen = (
        await sitzung.execute(
            select(
                Befund.regel_id,
                Befund.titel,
                func.count().label("gesamt"),
                func.count(Befund.quittiert_am).label("quittiert"),
            )
            .group_by(Befund.regel_id, Befund.titel)
            .order_by(func.count(Befund.quittiert_am).desc())
        )
    ).all()
    return antworten(
        request,
        "kern/betreiber.html",
        {
            "zeilen": [
                {
                    "regel_id": regel_id,
                    "titel": titel,
                    "gesamt": int(gesamt),
                    "quittiert": int(quittiert),
                    "quote": round(int(quittiert) / int(gesamt) * 100) if gesamt else 0,
                }
                for regel_id, titel, gesamt, quittiert in zeilen
            ]
        },
        benutzer=inhaber,
        module=await _module(sitzung),
    )


@router.get("/datei/{kennung}")
async def datei_ausliefern(
    benutzer: BenutzerAbh, kennung: str, bereich: str = "uploads"
) -> Response:
    """Dateien nur über diesen Endpoint, nie als statischer Pfad (Querschnitt 1.4)."""
    if bereich not in {"uploads", "ausgaben"}:
        return Response("Unbekannter Bereich.", status_code=400)
    try:
        pfad = ablage.mandantenverzeichnis(benutzer.mandant_id, bereich) / kennung
        inhalt = await run_in_threadpool(ablage.lesen, benutzer.mandant_id, pfad, bereich)
    except (ablage.AblageFehler, FileNotFoundError):
        return Response(
            "Diese Datei gehört nicht zu Ihrem Büro oder wurde nach Ablauf der "
            "Aufbewahrungsfrist entfernt.",
            status_code=404,
        )
    from belegwerk.kern.dateipruefung import art_bestimmen

    befund = art_bestimmen(inhalt)
    typen = {"pdf": "application/pdf", "bild": f"image/{befund.unterart or 'jpeg'}"}
    return Response(inhalt, media_type=typen.get(befund.art, "application/octet-stream"))
