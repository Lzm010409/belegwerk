"""Strukturiertes JSON-Logging.

Querschnitt 4.1: Niemals Dokumentinhalte, Namen, Kennzeichen oder VIN ins Log.
Erlaubt sind Vorgangs-ID, Mandanten-ID und Dokument-Hash. Der Filter unten ist
die technische Absicherung dieser Regel: Felder, deren Name auf personenbezogene
Inhalte hindeutet, werden nicht ausgegeben.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

VERBOTENE_FELDER = frozenset(
    {
        "name",
        "vorname",
        "nachname",
        "email",
        "e_mail",
        "anschrift",
        "strasse",
        "kennzeichen",
        "vin",
        "rohtext",
        "rohzeile",
        "inhalt",
        "dateiname",
        "passwort",
        "token",
        "geheimnis",
    }
)

_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatierer(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        eintrag: dict[str, Any] = {
            "zeit": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "stufe": record.levelname,
            "logger": record.name,
            "meldung": record.getMessage(),
        }
        for schluessel, wert in record.__dict__.items():
            if schluessel in _STANDARD or schluessel.startswith("_"):
                continue
            if schluessel.lower() in VERBOTENE_FELDER:
                eintrag[schluessel] = "<unterdrueckt>"
                continue
            try:
                json.dumps(wert)
            except (TypeError, ValueError):
                wert = repr(wert)
            eintrag[schluessel] = wert
        if record.exc_info:
            eintrag["ausnahme"] = self.formatException(record.exc_info)
        return json.dumps(eintrag, ensure_ascii=False)


def logging_einrichten(stufe: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatierer())
    wurzel = logging.getLogger()
    wurzel.handlers = [handler]
    wurzel.setLevel(stufe)
    for laut in ("uvicorn.access", "asyncio", "pdfminer", "fontTools", "weasyprint"):
        logging.getLogger(laut).setLevel(logging.WARNING)
