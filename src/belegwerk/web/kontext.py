"""Gemeinsamer Vorlagenkontext: Benutzer, Navigation, CSRF, Meldungen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from belegwerk.kern import csrf
from belegwerk.kern.anmeldung import AngemeldeterBenutzer
from belegwerk.konfiguration import einstellungen
from belegwerk.web.vorlagen import seite

MELDUNG_COOKIE = "belegwerk_meldung"


@dataclass(frozen=True, slots=True)
class Navigationseintrag:
    pfad: str
    beschriftung: str
    aktiv: bool


NAVIGATION = [
    ("/app", "Übersicht"),
    ("/app/delta", "Delta"),
    ("/app/atlas", "Atlas"),
    ("/app/check", "Check"),
]


def navigation_bauen(request: Request, module: set[str] | None = None) -> list[Navigationseintrag]:
    """Zeigt nur die Module, die das Büro gebucht hat (Plattformdatei 3)."""
    pfad = request.url.path
    eintraege: list[Navigationseintrag] = []
    for ziel, beschriftung in NAVIGATION:
        schluessel = ziel.rsplit("/", 1)[-1]
        if module is not None and schluessel in {"delta", "atlas", "check"} and schluessel not in module:
            continue
        eintraege.append(
            Navigationseintrag(ziel, beschriftung, aktiv=pfad == ziel or pfad.startswith(ziel + "/"))
        )
    return eintraege


def meldungen_lesen(request: Request) -> list[tuple[str, str]]:
    roh = request.cookies.get(MELDUNG_COOKIE)
    if not roh:
        return []
    art, _, text = roh.partition("|")
    if art not in {"erfolg", "fehler", "hinweis"} or not text:
        return []
    # Cookie-Werte muessen latin-1-faehig sein; deutsche Anfuehrungszeichen sind
    # es nicht. Deshalb prozentkodiert ablegen und hier zurueckwandeln.
    return [(art, unquote(text))]


def antwort_mit_meldung(ziel: str, art: str, text: str, status_code: int = 303) -> RedirectResponse:
    antwort = RedirectResponse(ziel, status_code=status_code)
    antwort.set_cookie(
        MELDUNG_COOKIE,
        f"{art}|{quote(text)}",
        max_age=30,
        path="/",
        httponly=True,
        samesite="lax",
        secure=einstellungen().ist_produktion,
    )
    return antwort


def antworten(
    request: Request,
    vorlage: str,
    kontext: dict[str, Any] | None = None,
    *,
    benutzer: AngemeldeterBenutzer | None = None,
    modul: str | None = None,
    module: set[str] | None = None,
    status_code: int = 200,
) -> Response:
    """Rendert eine Seite mit dem gemeinsamen Grundkontext."""
    token = csrf.token_aus_request(request)
    daten: dict[str, Any] = {
        "benutzer": benutzer,
        "modul": modul,
        "navigation": navigation_bauen(request, module) if benutzer else [],
        "csrf_token": token,
        "meldungen": meldungen_lesen(request),
    }
    daten.update(kontext or {})
    antwort = seite(request, vorlage, daten, status_code=status_code)
    csrf.token_setzen(antwort, token, sicher=einstellungen().ist_produktion)
    antwort.delete_cookie(MELDUNG_COOKIE, path="/")
    return antwort
