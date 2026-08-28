"""Aufbewahrung, Alterung, Kontolöschung (Querschnitt 5 und 7.3).

Diese Jobs arbeiten mandantenübergreifend und laufen deshalb unter der
Eigentümerrolle. Sie sind so geschrieben, dass ein zweiter Lauf am selben Tag
nichts kaputt macht.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern import ablage, mail
from belegwerk.kern.formate import jetzt
from belegwerk.kern.modelle import (
    Abonnement,
    AbonnementStatus,
    Benutzer,
    Mandant,
    Rolle,
)
from belegwerk.konfiguration import einstellungen

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class Wartungsbericht:
    uploads_geloescht: int = 0
    ergebnisse_geloescht: int = 0
    sitzungen_entfernt: int = 0
    erinnerungen_versendet: int = 0
    abos_abgelaufen: int = 0
    mandanten_geloescht: int = 0
    meldungen: list[str] = field(default_factory=list)


async def uploads_aufraeumen(bericht: Wartungsbericht) -> None:
    """Uploads nach 90 Tagen löschen, Ergebnisse nach 12 Monaten.

    Gelöscht wird die Datei; der Datenbankeintrag bleibt, damit ein Vorgang
    nachvollziehbar bleibt. Der Pfad zeigt danach ins Leere — die Oberfläche
    sagt dann, dass die Datei nach Ablauf der Frist entfernt wurde.
    """
    konfiguration = einstellungen()
    fristen = {
        "uploads": timedelta(days=konfiguration.aufbewahrung_uploads_tage),
        "ausgaben": timedelta(days=konfiguration.aufbewahrung_ergebnisse_tage),
    }
    nun = jetzt()
    for bereich, frist in fristen.items():
        wurzel = (
            konfiguration.upload_verzeichnis
            if bereich == "uploads"
            else konfiguration.ausgabe_verzeichnis
        )
        if not wurzel.exists():
            continue
        for datei in wurzel.rglob("*"):
            if not datei.is_file():
                continue
            alter = nun.timestamp() - datei.stat().st_mtime
            if alter > frist.total_seconds():
                datei.unlink(missing_ok=True)
                if bereich == "uploads":
                    bericht.uploads_geloescht += 1
                else:
                    bericht.ergebnisse_geloescht += 1


async def sitzungen_aufraeumen(bericht: Wartungsbericht) -> None:
    from belegwerk.kern.anmeldung import abgelaufene_sitzungen_entfernen

    bericht.sitzungen_entfernt = await abgelaufene_sitzungen_entfernen()


async def erhebungen_erinnern(bericht: Wartungsbericht, stichtag: date | None = None) -> None:
    """Erinnerung an Erhebungen über 24 Monate (Atlas-Todo 2.4).

    Eine Mail je Büro und Lauf, ohne Kundendaten im Text — nur eine Anzahl und
    ein Link (Querschnitt 3.3).
    """
    from belegwerk.atlas.modelle import Erhebung

    heute = stichtag or date.today()
    grenze = heute - timedelta(days=24 * 30)
    async with sitzungsfabrik()() as sitzung:
        zeilen = (
            await sitzung.execute(
                select(Erhebung.mandant_id, func.count())
                .where(Erhebung.erhebungsdatum <= grenze, Erhebung.erinnert_am.is_(None))
                .group_by(Erhebung.mandant_id)
            )
        ).all()
        for mandant_id, anzahl in zeilen:
            inhaber = (
                await sitzung.execute(
                    select(Benutzer).where(
                        Benutzer.mandant_id == mandant_id,
                        Benutzer.rolle == Rolle.INHABER,
                        Benutzer.aktiv.is_(True),
                    )
                )
            ).scalars().first()
            if inhaber is None:
                continue
            link = f"{einstellungen().app_basis_url}/app/atlas/erhebungen"
            mail.senden(mail.erhebung_veraltet(inhaber.email, int(anzahl), link))
            await sitzung.execute(
                update(Erhebung)
                .where(
                    Erhebung.mandant_id == mandant_id,
                    Erhebung.erhebungsdatum <= grenze,
                    Erhebung.erinnert_am.is_(None),
                )
                .values(erinnert_am=jetzt())
            )
            bericht.erinnerungen_versendet += 1
        await sitzung.commit()


async def abonnements_pruefen(bericht: Wartungsbericht, stichtag: date | None = None) -> None:
    """Abgelaufene Testphasen umschalten und rechtzeitig darauf hinweisen."""
    heute = stichtag or date.today()
    async with sitzungsfabrik()() as sitzung:
        abos = (
            (
                await sitzung.execute(
                    select(Abonnement).where(
                        Abonnement.ende.is_not(None),
                        Abonnement.status != AbonnementStatus.ABGELAUFEN,
                    )
                )
            )
            .scalars()
            .all()
        )
        for abo in abos:
            assert abo.ende is not None
            if abo.ende < heute:
                abo.status = AbonnementStatus.ABGELAUFEN
                bericht.abos_abgelaufen += 1
            elif (abo.ende - heute).days == 7:
                inhaber = (
                    await sitzung.execute(
                        select(Benutzer).where(
                            Benutzer.mandant_id == abo.mandant_id,
                            Benutzer.rolle == Rolle.INHABER,
                            Benutzer.aktiv.is_(True),
                        )
                    )
                ).scalars().first()
                if inhaber is not None:
                    link = f"{einstellungen().app_basis_url}/app/einstellungen"
                    mail.senden(mail.abo_laeuft_aus(inhaber.email, abo.modul.value, link))
        await sitzung.commit()


async def kontoloeschungen_vollziehen(bericht: Wartungsbericht) -> None:
    """Kontolöschung mit 14 Tagen Karenz, danach unwiderruflich (Querschnitt 7.3).

    Nach Ablauf existiert keine Zeile und keine Datei des Mandanten mehr. Das
    Löschen der Mandantenzeile räumt über die Fremdschlüssel alles Weitere ab.
    """
    karenz = timedelta(days=einstellungen().konto_karenz_tage)
    grenze = jetzt() - karenz
    async with sitzungsfabrik()() as sitzung:
        faellige = (
            (
                await sitzung.execute(
                    select(Mandant).where(
                        Mandant.loeschung_beantragt_am.is_not(None),
                        Mandant.loeschung_beantragt_am <= grenze,
                    )
                )
            )
            .scalars()
            .all()
        )
        for mandant in faellige:
            mandant_id = mandant.id
            ablage.mandant_vollstaendig_loeschen(mandant_id)
            await sitzung.execute(delete(Mandant).where(Mandant.id == mandant_id))
            bericht.mandanten_geloescht += 1
            _log.info("Mandant endgültig gelöscht", extra={"mandant_id": str(mandant_id)})
        await sitzung.commit()


async def loeschung_beantragen(mandant_id: uuid.UUID) -> None:
    async with sitzungsfabrik()() as sitzung:
        mandant = (
            await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))
        ).scalar_one()
        mandant.loeschung_beantragt_am = jetzt()
        await sitzung.commit()


async def loeschung_widerrufen(mandant_id: uuid.UUID) -> None:
    async with sitzungsfabrik()() as sitzung:
        mandant = (
            await sitzung.execute(select(Mandant).where(Mandant.id == mandant_id))
        ).scalar_one()
        mandant.loeschung_beantragt_am = None
        await sitzung.commit()


async def alles_ausfuehren(stichtag: date | None = None) -> Wartungsbericht:
    """Der tägliche Durchlauf."""
    bericht = Wartungsbericht()
    schritte: list[tuple[str, Coroutine[Any, Any, None]]] = [
        ("Aufbewahrung", uploads_aufraeumen(bericht)),
        ("Sitzungen", sitzungen_aufraeumen(bericht)),
        ("Erhebungsalterung", erhebungen_erinnern(bericht, stichtag)),
        ("Abonnements", abonnements_pruefen(bericht, stichtag)),
        ("Kontolöschungen", kontoloeschungen_vollziehen(bericht)),
    ]
    for name, schritt in schritte:
        try:
            await schritt
        except Exception as fehler:  # noqa: BLE001 — ein Schritt darf den Lauf nicht kippen
            _log.exception("Wartungsschritt fehlgeschlagen", extra={"schritt": name})
            bericht.meldungen.append(f"{name}: {type(fehler).__name__}")
    _log.info(
        "Wartung fertig",
        extra={
            "uploads_geloescht": bericht.uploads_geloescht,
            "ergebnisse_geloescht": bericht.ergebnisse_geloescht,
            "sitzungen_entfernt": bericht.sitzungen_entfernt,
            "erinnerungen": bericht.erinnerungen_versendet,
            "abos_abgelaufen": bericht.abos_abgelaufen,
            "mandanten_geloescht": bericht.mandanten_geloescht,
        },
    )
    return bericht


WARTUNGSABSTAND_SEKUNDEN = 24 * 60 * 60


async def wartungsschleife(stopp: object) -> None:
    """Täglicher Durchlauf als Hintergrundtask der Anwendung.

    Bewusst kein externer Cron: der Container ist die Einheit, die läuft, und
    ein Job, der nur bei laufender Anwendung Sinn ergibt, gehört auch dorthin.
    Bei mehreren Replicas müsste hier eine Sperre über die Datenbank stehen.
    """
    import asyncio

    assert isinstance(stopp, asyncio.Event)
    # Kurz warten, damit der Start nicht durch die Wartung verzögert wird.
    try:
        await asyncio.wait_for(stopp.wait(), timeout=60)
        return
    except TimeoutError:
        pass
    while not stopp.is_set():
        await alles_ausfuehren()
        try:
            await asyncio.wait_for(stopp.wait(), timeout=WARTUNGSABSTAND_SEKUNDEN)
        except TimeoutError:
            continue
