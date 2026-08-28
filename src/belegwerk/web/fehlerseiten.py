"""Fehlerseiten 404 und 500 im Gestaltungsrahmen (Querschnitt 8.1).

Jede Seite nennt einen Weg nach vorn, nicht nur den Fehler.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from belegwerk.web.vorlagen import seite

_log = logging.getLogger(__name__)

TEXTE: dict[int, tuple[str, str]] = {
    400: ("Anfrage nicht verwertbar", "Die Anfrage war unvollständig oder fehlerhaft aufgebaut. Bitte das Formular erneut ausfüllen."),
    401: ("Anmeldung nötig", "Diese Seite setzt eine Anmeldung voraus. Bitte melden Sie sich an."),
    403: ("Kein Zugriff", "Ihr Konto hat auf diese Seite keinen Zugriff. Fehlt ein Modul, schaltet der Inhaber Ihres Büros es in den Einstellungen frei."),
    404: ("Seite nicht gefunden", "Unter dieser Adresse liegt nichts. Möglich ist ein veralteter Link oder ein Tippfehler."),
    405: ("Methode nicht erlaubt", "Diese Adresse nimmt Anfragen dieser Art nicht entgegen."),
    413: ("Datei zu groß", "Die Datei überschreitet die zulässige Größe. Bitte ein kleineres Dokument hochladen."),
    422: ("Eingaben unvollständig", "Mindestens ein Feld fehlt oder hat ein unerwartetes Format. Die Meldungen stehen am jeweiligen Feld."),
    429: ("Zu viele Versuche", "Zum Schutz vor automatisierten Zugriffen ist diese Adresse kurzzeitig gesperrt. Bitte in einigen Minuten erneut versuchen."),
    500: ("Verarbeitung fehlgeschlagen", "Ein interner Fehler ist aufgetreten und wurde protokolliert. Die zuletzt gespeicherten Daten sind unberührt."),
}


def _wege(request: Request) -> list[tuple[str, str]]:
    angemeldet = bool(getattr(request.state, "benutzer", None))
    if angemeldet:
        return [("/app", "Zur Übersicht"), ("/app/rueckmeldung", "Problem melden")]
    return [("/", "Zur Startseite"), ("/anmelden", "Anmelden")]


def _ist_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get(
        "accept", ""
    )


async def http_fehler(request: Request, ausnahme: Exception) -> Response:
    assert isinstance(ausnahme, StarletteHTTPException)
    code = ausnahme.status_code
    ueberschrift, erlaeuterung = TEXTE.get(code, ("Fehler", "Die Anfrage konnte nicht bearbeitet werden."))
    if isinstance(ausnahme.detail, str) and ausnahme.detail and code != 404:
        erlaeuterung = ausnahme.detail
    if _ist_json(request):
        return JSONResponse({"fehler": ueberschrift, "erlaeuterung": erlaeuterung}, status_code=code)
    return seite(
        request,
        "fehler.html",
        {"code": code, "ueberschrift": ueberschrift, "erlaeuterung": erlaeuterung, "wege": _wege(request)},
        status_code=code,
    )


async def validierungsfehler(request: Request, ausnahme: Exception) -> Response:
    assert isinstance(ausnahme, RequestValidationError)
    if _ist_json(request):
        return JSONResponse(
            {"fehler": "Eingaben unvollständig", "felder": ausnahme.errors()}, status_code=422
        )
    felder = ", ".join(
        str(teil) for fehler in ausnahme.errors() for teil in fehler["loc"][1:]
    ) or "unbekannt"
    return seite(
        request,
        "fehler.html",
        {
            "code": 422,
            "ueberschrift": TEXTE[422][0],
            "erlaeuterung": f"Diese Felder fehlen oder haben ein unerwartetes Format: {felder}.",
            "wege": _wege(request),
        },
        status_code=422,
    )


async def serverfehler(request: Request, ausnahme: Exception) -> Response:
    _log.exception("unbehandelter Fehler", extra={"pfad": request.url.path})
    ueberschrift, erlaeuterung = TEXTE[500]
    if _ist_json(request):
        return JSONResponse({"fehler": ueberschrift, "erlaeuterung": erlaeuterung}, status_code=500)
    return seite(
        request,
        "fehler.html",
        {"code": 500, "ueberschrift": ueberschrift, "erlaeuterung": erlaeuterung, "wege": _wege(request)},
        status_code=500,
    )


async def anmeldung_noetig(request: Request, ausnahme: Exception) -> Response:
    """Umleitung statt Fehlerseite — der Benutzer soll sich anmelden können."""
    from belegwerk.kern.abhaengigkeiten import AnmeldungNoetig

    assert isinstance(ausnahme, AnmeldungNoetig)
    if _ist_json(request):
        return JSONResponse(
            {"fehler": TEXTE[401][0], "erlaeuterung": TEXTE[401][1]}, status_code=401
        )
    return RedirectResponse(f"/anmelden?weiter={ausnahme.ziel}", status_code=303)


def fehlerseiten_registrieren(app: FastAPI) -> None:
    from belegwerk.kern.abhaengigkeiten import AnmeldungNoetig

    handler: dict[Any, Any] = {
        AnmeldungNoetig: anmeldung_noetig,
        StarletteHTTPException: http_fehler,
        RequestValidationError: validierungsfehler,
        Exception: serverfehler,
    }
    for typ, funktion in handler.items():
        app.add_exception_handler(typ, funktion)
