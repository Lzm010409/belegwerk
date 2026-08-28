"""Sicherheits-Header inklusive Content-Security-Policy (Querschnitt 8.5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Alle Skripte, Stile, Schriften und Bilder liegen im eigenen Image. Deshalb
# reicht 'self'; 'unsafe-inline' ist nur fuer Stil-Attribute noetig, die HTMX
# und die serverseitig erzeugten SVG-Diagramme setzen.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)

KOPFZEILEN = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(self), camera=(self), microphone=(), payment=()",
}


class SicherheitsKopfzeilen(BaseHTTPMiddleware):
    """Setzt die Sicherheits-Kopfzeilen auf jede Antwort."""

    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        antwort = await call_next(request)
        for name, wert in KOPFZEILEN.items():
            antwort.headers.setdefault(name, wert)
        if self.hsts:
            antwort.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return antwort
