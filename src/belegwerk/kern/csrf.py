"""CSRF-Schutz (Querschnitt 8.5).

Doppeltes Absenden: ein zufälliger Wert steht im ``__Host``-Cookie und im
Formularfeld. Ein fremdes Formular kennt den Cookiewert nicht.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response

COOKIE_NAME = "belegwerk_csrf"
FELD_NAME = "csrf_token"
SICHERE_METHODEN = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfFehler(Exception):
    pass


def token_erzeugen() -> str:
    return secrets.token_urlsafe(32)


def token_setzen(antwort: Response, token: str, sicher: bool) -> None:
    antwort.set_cookie(
        COOKIE_NAME,
        token,
        httponly=False,  # das Formular muss den Wert lesen können
        secure=sicher,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 12,
    )


def token_aus_request(request: Request) -> str:
    vorhanden = request.cookies.get(COOKIE_NAME)
    return vorhanden or token_erzeugen()


async def pruefen(request: Request) -> None:
    if request.method in SICHERE_METHODEN:
        return
    aus_cookie = request.cookies.get(COOKIE_NAME)
    formular = await request.form()
    aus_formular = formular.get(FELD_NAME) or request.headers.get("X-CSRF-Token")
    if not aus_cookie or not isinstance(aus_formular, str) or not hmac.compare_digest(aus_cookie, aus_formular):
        raise CsrfFehler(
            "Das Formular ist abgelaufen oder stammt nicht von dieser Seite. "
            "Bitte die Seite neu laden und erneut absenden."
        )
