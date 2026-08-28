"""Datenhoheit des Kunden (Querschnitt 7).

Ein Werkzeug, das die eigene Arbeit aufnimmt, muss sie auch wieder herausgeben.
Das ist zugleich das Verkaufsargument gegenüber den geschlossenen Systemen der
Branche.

Der Export enthält alles, was zu einem Mandanten gehört: die Datenbankinhalte
als JSON und sämtliche Dateien — Uploads wie erzeugte Anlagen. Er dient sowohl
der Selbstauskunft nach Art. 15 DSGVO als auch dem vollständigen Datenexport bei
Kündigung.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk import __version__
from belegwerk.basis import Basis
from belegwerk.kern import ablage
from belegwerk.kern.formate import jetzt
from belegwerk.kern.mandantentrennung import mandantentabellen

LIESMICH = """Belegwerk — Datenexport

Dieses Archiv enthält alle Daten Ihres Büros zum Zeitpunkt der Erstellung.

  daten/<tabelle>.json   Der Inhalt je Tabelle, Feldnamen wie in der Anwendung.
                         Geldbeträge stehen als Zeichenkette, damit beim Lesen
                         keine Rundung entsteht.
  dateien/uploads/       Die von Ihnen hochgeladenen Dokumente, unverändert.
  dateien/ausgaben/      Die von der Anwendung erzeugten PDF-Anlagen.
  export.json            Zeitpunkt, Version und Umfang dieses Exports.

Der Export ist vollständig: er ist die Grundlage sowohl für eine Auskunft nach
Artikel 15 DSGVO als auch für einen Anbieterwechsel.
"""


def _wert(wert: Any) -> Any:
    if isinstance(wert, Decimal):
        return str(wert)
    if isinstance(wert, (datetime, date)):
        return wert.isoformat()
    if isinstance(wert, uuid.UUID):
        return str(wert)
    if isinstance(wert, (list, tuple)):
        return [_wert(eintrag) for eintrag in wert]
    if isinstance(wert, dict):
        return {schluessel: _wert(inhalt) for schluessel, inhalt in wert.items()}
    if hasattr(wert, "value"):  # Enum
        return wert.value
    return wert


async def _tabelle_lesen(sitzung: AsyncSession, tabelle: Table) -> list[dict[str, Any]]:
    zeilen = (await sitzung.execute(select(tabelle))).mappings().all()
    return [{name: _wert(inhalt) for name, inhalt in zeile.items()} for zeile in zeilen]


async def archiv_bauen(sitzung: AsyncSession, mandant_id: uuid.UUID) -> bytes:
    """Baut das ZIP. Die Sitzung ist mandantengebunden — RLS filtert mit."""
    puffer = io.BytesIO()
    umfang: dict[str, int] = {}

    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as archiv:
        archiv.writestr("LIESMICH.txt", LIESMICH)

        tabellen = [Basis.metadata.tables["mandant"], *mandantentabellen()]
        for tabelle in tabellen:
            zeilen = await _tabelle_lesen(sitzung, tabelle)
            umfang[tabelle.name] = len(zeilen)
            archiv.writestr(
                f"daten/{tabelle.name}.json",
                json.dumps(zeilen, ensure_ascii=False, indent=2, sort_keys=True),
            )

        dateien = 0
        for bereich in ("uploads", "ausgaben"):
            verzeichnis = ablage.mandantenverzeichnis(mandant_id, bereich)
            for datei in sorted(verzeichnis.rglob("*")):
                if datei.is_file():
                    archiv.write(datei, f"dateien/{bereich}/{datei.name}")
                    dateien += 1

        archiv.writestr(
            "export.json",
            json.dumps(
                {
                    "erstellt_am": jetzt().isoformat(),
                    "version": __version__,
                    "mandant_id": str(mandant_id),
                    "tabellen": umfang,
                    "dateien": dateien,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return puffer.getvalue()
