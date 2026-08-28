"""Jinja-Umgebung mit den deutschen Formatfiltern."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from belegwerk.kern import formate

VORLAGEN_VERZEICHNIS = Path(__file__).parent / "templates"
STATIK_VERZEICHNIS = Path(__file__).parent / "static"

vorlagen = Jinja2Templates(directory=str(VORLAGEN_VERZEICHNIS))
vorlagen.env.filters["geld"] = formate.geld
vorlagen.env.filters["zahl"] = formate.zahl
vorlagen.env.filters["prozent"] = formate.prozent
vorlagen.env.filters["datum"] = formate.datum
vorlagen.env.filters["datum_zeit"] = formate.datum_zeit
vorlagen.env.globals["marke"] = "Belegwerk"


def seite(
    request: Request,
    name: str,
    kontext: dict[str, Any] | None = None,
    status_code: int = 200,
) -> Response:
    """Rendert eine Seite und reicht immer den Request mit."""
    daten: dict[str, Any] = {"request": request}
    daten.update(kontext or {})
    antwort: Response = vorlagen.TemplateResponse(request, name, daten, status_code=status_code)
    return antwort


def bruchteil_klasse(anteil: float) -> Markup:
    """Hilfsfunktion fuer Balken in Vorlagen."""
    return Markup(f"width:{max(0.0, min(1.0, anteil)) * 100:.1f}%")


vorlagen.env.globals["bruchteil_klasse"] = bruchteil_klasse
