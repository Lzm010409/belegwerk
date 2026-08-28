"""Erststart: legt aus den Umgebungsvariablen den ersten Mandanten an.

Ohne diesen Schritt gäbe es nach dem ersten Deployment kein Konto, mit dem man
sich anmelden kann — und Registrierung ist nur per Einladung möglich. Läuft nur,
solange noch kein Benutzer existiert; danach passiert nichts mehr.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern import passwoerter
from belegwerk.kern.abrechnung import testphase_starten
from belegwerk.kern.modelle import Benutzer, Mandant, Rolle
from belegwerk.konfiguration import einstellungen

_log = logging.getLogger(__name__)


async def ersten_mandanten_anlegen() -> bool:
    konfiguration = einstellungen()
    if not (konfiguration.erster_admin_email and konfiguration.erster_admin_passwort):
        return False

    async with sitzungsfabrik()() as db:
        vorhandene = (await db.execute(select(func.count()).select_from(Benutzer))).scalar_one()
        if vorhandene:
            return False

        try:
            hash_wert = passwoerter.hashen(konfiguration.erster_admin_passwort)
        except passwoerter.PasswortZuSchwach as fehler:
            _log.error("ERSTER_ADMIN_PASSWORT abgelehnt", extra={"grund": str(fehler)})
            return False

        mandant = Mandant(name=konfiguration.erster_admin_buero)
        db.add(mandant)
        await db.flush()
        db.add(
            Benutzer(
                mandant_id=mandant.id,
                email=konfiguration.erster_admin_email.strip().lower(),
                name=konfiguration.erster_admin_name or "Inhaber",
                passwort_hash=hash_wert,
                rolle=Rolle.INHABER,
            )
        )
        await testphase_starten(db, mandant.id)
        await db.commit()
        _log.info("Erster Mandant angelegt", extra={"mandant_id": str(mandant.id)})
        return True
