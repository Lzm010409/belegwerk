"""Sitzungs-Auth: Anmeldung, Abmeldung, Einladung, Passwortrücksetzung.

Serverseitige Sitzungen: das Cookie trägt nur einen Zufallswert, in der
Datenbank steht dessen SHA-256. Wer die Datenbank liest, kann damit keine
Sitzung übernehmen.

Dieses Modul arbeitet bewusst mit der mandantenumgehenden Sitzung: vor der
Anmeldung ist der Mandant noch nicht bekannt (siehe ADR 0005).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern import passwoerter
from belegwerk.kern.formate import jetzt
from belegwerk.kern.modelle import Benutzer, Einladung, Mandant, PasswortMarke, Rolle, Sitzung

_log = logging.getLogger(__name__)

COOKIE_NAME = "belegwerk_sitzung"
SITZUNGSDAUER = timedelta(days=14)
EINLADUNGSDAUER = timedelta(days=7)
MARKENDAUER = timedelta(hours=2)


class AnmeldungFehlgeschlagen(Exception):
    """Bewusst ohne Unterscheidung zwischen „Konto unbekannt" und „Passwort falsch"."""

    def __init__(self) -> None:
        super().__init__("E-Mail-Adresse oder Passwort stimmen nicht.")


class EinladungUngueltig(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AngemeldeterBenutzer:
    """Was jede Anfrage über den Aufrufer wissen muss — ohne ORM-Objekt."""

    benutzer_id: uuid.UUID
    mandant_id: uuid.UUID
    name: str
    email: str
    rolle: Rolle
    mandant_name: str
    sitzung_id: uuid.UUID

    @property
    def ist_inhaber(self) -> bool:
        return self.rolle is Rolle.INHABER


def marke_hashen(marke: str) -> str:
    return hashlib.sha256(marke.encode()).hexdigest()


def email_normalisieren(email: str) -> str:
    return email.strip().lower()


async def anmelden(email: str, passwort: str) -> tuple[str, AngemeldeterBenutzer]:
    """Prüft die Zugangsdaten und legt eine Sitzung an."""
    async with sitzungsfabrik()() as db:
        benutzer = (
            await db.execute(select(Benutzer).where(Benutzer.email == email_normalisieren(email)))
        ).scalar_one_or_none()

        if benutzer is None or not benutzer.aktiv:
            # Gleicher Zeitaufwand wie bei existierendem Konto: sonst verrät die
            # Antwortzeit, welche Adressen registriert sind.
            passwoerter.pruefen(passwort, _BLIND_HASH)
            raise AnmeldungFehlgeschlagen
        if not passwoerter.pruefen(passwort, benutzer.passwort_hash):
            raise AnmeldungFehlgeschlagen

        if passwoerter.muss_neu_gehasht_werden(benutzer.passwort_hash):
            benutzer.passwort_hash = passwoerter.hashen(passwort)

        marke = passwoerter.marke_erzeugen()
        nun = jetzt()
        sitzung = Sitzung(
            mandant_id=benutzer.mandant_id,
            benutzer_id=benutzer.id,
            token_hash=marke_hashen(marke),
            angelegt_am=nun,
            zuletzt_gesehen=nun,
            laeuft_ab=nun + SITZUNGSDAUER,
        )
        db.add(sitzung)
        benutzer.letzte_anmeldung = nun
        await db.flush()
        angemeldet = AngemeldeterBenutzer(
            benutzer_id=benutzer.id,
            mandant_id=benutzer.mandant_id,
            name=benutzer.name,
            email=benutzer.email,
            rolle=benutzer.rolle,
            mandant_name=benutzer.mandant.name,
            sitzung_id=sitzung.id,
        )
        await db.commit()
    _log.info("Anmeldung erfolgreich", extra={"mandant_id": str(angemeldet.mandant_id)})
    return marke, angemeldet


# Ein gültiger Argon2-Hash eines Zufallswerts, damit unbekannte Konten dieselbe
# Rechenzeit kosten wie bekannte.
_BLIND_HASH = passwoerter.hashen(passwoerter.marke_erzeugen())


async def sitzung_lesen(marke: str) -> AngemeldeterBenutzer | None:
    """Löst das Cookie auf. Gibt ``None`` bei abgelaufener oder unbekannter Sitzung."""
    if not marke:
        return None
    async with sitzungsfabrik()() as db:
        sitzung = (
            await db.execute(select(Sitzung).where(Sitzung.token_hash == marke_hashen(marke)))
        ).scalar_one_or_none()
        if sitzung is None:
            return None
        nun = jetzt()
        if sitzung.laeuft_ab <= nun:
            await db.delete(sitzung)
            await db.commit()
            return None
        benutzer = sitzung.benutzer
        if not benutzer.aktiv:
            return None
        if (nun - sitzung.zuletzt_gesehen) > timedelta(minutes=15):
            sitzung.zuletzt_gesehen = nun
            sitzung.laeuft_ab = nun + SITZUNGSDAUER
            await db.commit()
        return AngemeldeterBenutzer(
            benutzer_id=benutzer.id,
            mandant_id=benutzer.mandant_id,
            name=benutzer.name,
            email=benutzer.email,
            rolle=benutzer.rolle,
            mandant_name=benutzer.mandant.name,
            sitzung_id=sitzung.id,
        )


async def abmelden(marke: str) -> None:
    async with sitzungsfabrik()() as db:
        sitzung = (
            await db.execute(select(Sitzung).where(Sitzung.token_hash == marke_hashen(marke)))
        ).scalar_one_or_none()
        if sitzung is not None:
            await db.delete(sitzung)
            await db.commit()


async def alle_sitzungen_beenden(benutzer_id: uuid.UUID) -> None:
    """Nach Passwortwechsel: bestehende Sitzungen verlieren ihre Gültigkeit."""
    async with sitzungsfabrik()() as db:
        for sitzung in (
            (await db.execute(select(Sitzung).where(Sitzung.benutzer_id == benutzer_id)))
            .scalars()
            .all()
        ):
            await db.delete(sitzung)
        await db.commit()


async def abgelaufene_sitzungen_entfernen() -> int:
    async with sitzungsfabrik()() as db:
        alte = (
            (await db.execute(select(Sitzung).where(Sitzung.laeuft_ab <= jetzt()))).scalars().all()
        )
        for sitzung in alte:
            await db.delete(sitzung)
        await db.commit()
        return len(alte)


# --------------------------------------------------------------------------
# Einladungen — Registrierung ist ausschließlich über einen Code möglich.
# --------------------------------------------------------------------------


async def einladung_anlegen(
    db: AsyncSession, mandant_id: uuid.UUID, email: str, rolle: Rolle, erstellt_von: uuid.UUID | None
) -> str:
    code = passwoerter.marke_erzeugen()
    db.add(
        Einladung(
            mandant_id=mandant_id,
            code_hash=marke_hashen(code),
            email=email_normalisieren(email),
            rolle=rolle,
            laeuft_ab=jetzt() + EINLADUNGSDAUER,
            erstellt_von_id=erstellt_von,
        )
    )
    await db.flush()
    return code


async def einladung_pruefen(code: str) -> Einladung:
    async with sitzungsfabrik()() as db:
        einladung = (
            await db.execute(select(Einladung).where(Einladung.code_hash == marke_hashen(code)))
        ).scalar_one_or_none()
        if einladung is None:
            raise EinladungUngueltig("Dieser Einladungscode ist unbekannt.")
        if einladung.eingeloest_am is not None:
            raise EinladungUngueltig("Dieser Einladungscode wurde bereits eingelöst.")
        if einladung.laeuft_ab <= jetzt():
            raise EinladungUngueltig(
                "Dieser Einladungscode ist abgelaufen. Bitte im Büro eine neue Einladung anfordern."
            )
        db.expunge(einladung)
        return einladung


async def einladung_einloesen(code: str, name: str, passwort: str) -> AngemeldeterBenutzer:
    einladung = await einladung_pruefen(code)
    hash_wert = passwoerter.hashen(passwort)
    async with sitzungsfabrik()() as db:
        frisch = (
            await db.execute(select(Einladung).where(Einladung.id == einladung.id))
        ).scalar_one()
        if frisch.eingeloest_am is not None:
            raise EinladungUngueltig("Dieser Einladungscode wurde bereits eingelöst.")
        vorhanden = (
            await db.execute(select(Benutzer).where(Benutzer.email == frisch.email))
        ).scalar_one_or_none()
        if vorhanden is not None:
            raise EinladungUngueltig(
                "Für diese E-Mail-Adresse besteht bereits ein Konto. Bitte anmelden "
                "oder das Passwort zurücksetzen."
            )
        benutzer = Benutzer(
            mandant_id=frisch.mandant_id,
            email=frisch.email,
            name=name.strip(),
            passwort_hash=hash_wert,
            rolle=frisch.rolle,
        )
        db.add(benutzer)
        frisch.eingeloest_am = jetzt()
        await db.flush()
        mandant = (await db.execute(select(Mandant).where(Mandant.id == frisch.mandant_id))).scalar_one()
        angelegt = AngemeldeterBenutzer(
            benutzer_id=benutzer.id,
            mandant_id=benutzer.mandant_id,
            name=benutzer.name,
            email=benutzer.email,
            rolle=benutzer.rolle,
            mandant_name=mandant.name,
            sitzung_id=uuid.uuid4(),
        )
        await db.commit()
    return angelegt


# --------------------------------------------------------------------------
# Passwortrücksetzung
# --------------------------------------------------------------------------


async def marke_fuer_passwort(email: str) -> tuple[str, str] | None:
    """Legt eine Rücksetzmarke an. ``None``, wenn es das Konto nicht gibt.

    Der Aufrufer meldet dem Benutzer in beiden Fällen dasselbe — sonst wird das
    Formular zur Auskunft darüber, welche Adressen registriert sind.
    """
    async with sitzungsfabrik()() as db:
        benutzer = (
            await db.execute(select(Benutzer).where(Benutzer.email == email_normalisieren(email)))
        ).scalar_one_or_none()
        if benutzer is None or not benutzer.aktiv:
            return None
        marke = passwoerter.marke_erzeugen()
        db.add(
            PasswortMarke(
                mandant_id=benutzer.mandant_id,
                benutzer_id=benutzer.id,
                marke_hash=marke_hashen(marke),
                angelegt_am=jetzt(),
                laeuft_ab=jetzt() + MARKENDAUER,
            )
        )
        await db.commit()
        return marke, benutzer.email


async def passwort_neu_setzen(marke: str, passwort: str) -> bool:
    hash_wert = passwoerter.hashen(passwort)
    async with sitzungsfabrik()() as db:
        eintrag = (
            await db.execute(select(PasswortMarke).where(PasswortMarke.marke_hash == marke_hashen(marke)))
        ).scalar_one_or_none()
        if eintrag is None or eintrag.eingeloest_am is not None or eintrag.laeuft_ab <= jetzt():
            return False
        await db.execute(
            update(Benutzer).where(Benutzer.id == eintrag.benutzer_id).values(passwort_hash=hash_wert)
        )
        eintrag.eingeloest_am = jetzt()
        await db.commit()
        benutzer_id = eintrag.benutzer_id
    await alle_sitzungen_beenden(benutzer_id)
    return True
