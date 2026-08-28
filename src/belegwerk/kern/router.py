"""Anmeldung, Einladung, Passwortrücksetzung und die Übersichtsseite."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from belegwerk.kern import mail, passwoerter, ratenbegrenzung
from belegwerk.kern.abhaengigkeiten import (
    BenutzerAbh,
    CsrfAbh,
    DatenbankAbh,
    OptionalerBenutzerAbh,
)
from belegwerk.kern.abrechnung import LISTENPREIS, MODULBESCHREIBUNG, MODULNAMEN, alle_zugriffe
from belegwerk.kern.anmeldung import (
    COOKIE_NAME,
    SITZUNGSDAUER,
    AnmeldungFehlgeschlagen,
    EinladungUngueltig,
    abmelden,
    anmelden,
    einladung_einloesen,
    einladung_pruefen,
    marke_fuer_passwort,
    passwort_neu_setzen,
)
from belegwerk.konfiguration import einstellungen
from belegwerk.web.kontext import antworten, antwort_mit_meldung

_log = logging.getLogger(__name__)
router = APIRouter()

SICHERE_WEITERLEITUNG_PRAEFIX = "/app"


def _weiter_saeubern(weiter: str | None) -> str:
    """Nur eigene Pfade — sonst wird das Anmeldeformular zur Weiterleitung."""
    if weiter and weiter.startswith(SICHERE_WEITERLEITUNG_PRAEFIX) and "//" not in weiter:
        return weiter
    return "/app"


def _sitzungscookie_setzen(antwort: Response, marke: str) -> None:
    antwort.set_cookie(
        COOKIE_NAME,
        marke,
        httponly=True,
        secure=einstellungen().ist_produktion,
        samesite="lax",
        path="/",
        max_age=int(SITZUNGSDAUER.total_seconds()),
    )


@router.get("/anmelden")
async def anmeldeformular(
    request: Request, benutzer: OptionalerBenutzerAbh, weiter: str | None = None
) -> Response:
    if benutzer is not None:
        return RedirectResponse(_weiter_saeubern(weiter), status_code=303)
    return antworten(request, "kern/anmelden.html", {"weiter": weiter or ""})


@router.post("/anmelden")
async def anmeldung_absenden(
    request: Request,
    _csrf: CsrfAbh,
    email: Annotated[str, Form()],
    passwort: Annotated[str, Form()],
    weiter: Annotated[str, Form()] = "",
) -> Response:
    kennung = request.client.host if request.client else "unbekannt"
    try:
        ratenbegrenzung.pruefen_und_zaehlen("anmeldung", kennung, ratenbegrenzung.ANMELDUNG)
        marke, benutzer = await anmelden(email, passwort)
    except ratenbegrenzung.ZuVieleVersuche as fehler:
        return antworten(
            request,
            "kern/anmelden.html",
            {"fehler": str(fehler), "email": email, "weiter": weiter},
            status_code=429,
        )
    except AnmeldungFehlgeschlagen as fehler:
        _log.info("Anmeldung fehlgeschlagen")
        return antworten(
            request,
            "kern/anmelden.html",
            {"fehler": str(fehler), "email": email, "weiter": weiter},
            status_code=401,
        )
    ratenbegrenzung.zuruecksetzen("anmeldung", kennung)
    antwort = RedirectResponse(_weiter_saeubern(weiter), status_code=303)
    _sitzungscookie_setzen(antwort, marke)
    return antwort


@router.post("/abmelden")
async def abmeldung(request: Request, _csrf: CsrfAbh) -> Response:
    await abmelden(request.cookies.get(COOKIE_NAME, ""))
    antwort = antwort_mit_meldung("/anmelden", "erfolg", "Sie sind abgemeldet.")
    antwort.delete_cookie(COOKIE_NAME, path="/")
    return antwort


# --------------------------------------------------------------------------
# Einladung
# --------------------------------------------------------------------------


@router.get("/einladung/{code}")
async def einladungsformular(request: Request, code: str) -> Response:
    try:
        einladung = await einladung_pruefen(code)
    except EinladungUngueltig as fehler:
        return antworten(
            request, "kern/einladung.html", {"fehler": str(fehler), "code": code}, status_code=410
        )
    return antworten(
        request,
        "kern/einladung.html",
        {"code": code, "email": einladung.email, "mindestlaenge": passwoerter.MINDESTLAENGE},
    )


@router.post("/einladung/{code}")
async def einladung_absenden(
    request: Request,
    _csrf: CsrfAbh,
    code: str,
    name: Annotated[str, Form()],
    passwort: Annotated[str, Form()],
    passwort_wiederholung: Annotated[str, Form()],
) -> Response:
    fehler: str | None = None
    if passwort != passwort_wiederholung:
        fehler = "Die beiden Passwörter stimmen nicht überein."
    else:
        try:
            passwoerter.staerke_pruefen(passwort)
            await einladung_einloesen(code, name, passwort)
        except (passwoerter.PasswortZuSchwach, EinladungUngueltig) as ausnahme:
            fehler = str(ausnahme)
    if fehler:
        return antworten(
            request,
            "kern/einladung.html",
            {"fehler": fehler, "code": code, "name": name, "mindestlaenge": passwoerter.MINDESTLAENGE},
            status_code=400,
        )
    return antwort_mit_meldung(
        "/anmelden", "erfolg", "Ihr Konto ist angelegt. Bitte melden Sie sich an."
    )


# --------------------------------------------------------------------------
# Passwortrücksetzung
# --------------------------------------------------------------------------


@router.get("/passwort-vergessen")
async def passwort_vergessen_formular(request: Request) -> Response:
    return antworten(request, "kern/passwort_vergessen.html", {})


@router.post("/passwort-vergessen")
async def passwort_vergessen_absenden(
    request: Request, _csrf: CsrfAbh, email: Annotated[str, Form()]
) -> Response:
    kennung = request.client.host if request.client else "unbekannt"
    try:
        ratenbegrenzung.pruefen_und_zaehlen(
            "passwort", kennung, ratenbegrenzung.PASSWORT_ZURUECK
        )
    except ratenbegrenzung.ZuVieleVersuche as fehler:
        return antworten(
            request, "kern/passwort_vergessen.html", {"fehler": str(fehler)}, status_code=429
        )
    ergebnis = await marke_fuer_passwort(email)
    if ergebnis is not None:
        marke, adresse = ergebnis
        link = f"{einstellungen().app_basis_url}/passwort-neu/{marke}"
        mail.senden(mail.passwort_zuruecksetzen(adresse, link))
    # Dieselbe Antwort in beiden Fällen: sonst verrät das Formular, welche
    # Adressen registriert sind.
    return antworten(request, "kern/passwort_vergessen.html", {"versendet": True})


@router.get("/passwort-neu/{marke}")
async def passwort_neu_formular(request: Request, marke: str) -> Response:
    return antworten(
        request,
        "kern/passwort_neu.html",
        {"marke": marke, "mindestlaenge": passwoerter.MINDESTLAENGE},
    )


@router.post("/passwort-neu/{marke}")
async def passwort_neu_absenden(
    request: Request,
    _csrf: CsrfAbh,
    marke: str,
    passwort: Annotated[str, Form()],
    passwort_wiederholung: Annotated[str, Form()],
) -> Response:
    fehler: str | None = None
    if passwort != passwort_wiederholung:
        fehler = "Die beiden Passwörter stimmen nicht überein."
    else:
        try:
            passwoerter.staerke_pruefen(passwort)
        except passwoerter.PasswortZuSchwach as ausnahme:
            fehler = str(ausnahme)
        else:
            if not await passwort_neu_setzen(marke, passwort):
                fehler = (
                    "Dieser Link ist abgelaufen oder wurde bereits benutzt. "
                    "Bitte fordern Sie eine neue Rücksetzung an."
                )
    if fehler:
        return antworten(
            request,
            "kern/passwort_neu.html",
            {"fehler": fehler, "marke": marke, "mindestlaenge": passwoerter.MINDESTLAENGE},
            status_code=400,
        )
    return antwort_mit_meldung(
        "/anmelden", "erfolg", "Das Passwort ist gesetzt. Bitte melden Sie sich an."
    )


# --------------------------------------------------------------------------
# Übersicht
# --------------------------------------------------------------------------


@router.get("/app")
async def uebersicht(request: Request, benutzer: BenutzerAbh, sitzung: DatenbankAbh) -> Response:
    zugriffe = await alle_zugriffe(sitzung)
    module = {modul.value for modul, zugriff in zugriffe.items() if zugriff.lesen}
    return antworten(
        request,
        "kern/uebersicht.html",
        {
            "zugriffe": list(zugriffe.values()),
            "namen": MODULNAMEN,
            "beschreibung": MODULBESCHREIBUNG,
            "preise": LISTENPREIS,
        },
        benutzer=benutzer,
        module=module,
    )
