"""Benutzerverwaltung je Mandant — zwei Rollen (Querschnitt 8.7).

Inhaber und Mitarbeiter. Drei Rollen wären eine Erfindung ohne Anlass.

Die E-Mail-Eindeutigkeit gilt über alle Mandanten hinweg: eine Adresse gehört zu
genau einem Konto. Die Prüfung braucht deshalb den mandantenübergreifenden
Zugang und ist in der Ausnahmeliste vermerkt — sie gibt nur „belegt" oder „frei"
zurück, nie einen fremden Datensatz.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern.anmeldung import einladung_anlegen, email_normalisieren
from belegwerk.kern.modelle import Benutzer, Einladung, Rolle


class VerwaltungFehler(Exception):
    pass


async def email_frei(email: str) -> bool:
    async with sitzungsfabrik()() as sitzung:
        anzahl = (
            await sitzung.execute(
                select(func.count())
                .select_from(Benutzer)
                .where(Benutzer.email == email_normalisieren(email))
            )
        ).scalar_one()
        return int(anzahl) == 0


async def benutzer_des_mandanten(sitzung: AsyncSession) -> list[Benutzer]:
    return list(
        (await sitzung.execute(select(Benutzer).order_by(Benutzer.name))).scalars().all()
    )


async def offene_einladungen(sitzung: AsyncSession) -> list[Einladung]:
    return list(
        (
            await sitzung.execute(
                select(Einladung)
                .where(Einladung.eingeloest_am.is_(None))
                .order_by(Einladung.angelegt_am.desc())
            )
        )
        .scalars()
        .all()
    )


async def einladen(
    sitzung: AsyncSession,
    mandant_id: uuid.UUID,
    einladender: uuid.UUID,
    email: str,
    rolle: Rolle,
) -> str:
    adresse = email_normalisieren(email)
    if "@" not in adresse or "." not in adresse.split("@")[-1]:
        raise VerwaltungFehler("Das ist keine gültige E-Mail-Adresse.")
    if not await email_frei(adresse):
        raise VerwaltungFehler(
            "Zu dieser E-Mail-Adresse besteht bereits ein Konto. Die Person kann sich "
            "anmelden oder ihr Passwort zurücksetzen."
        )
    return await einladung_anlegen(sitzung, mandant_id, adresse, rolle, einladender)


async def rolle_aendern(
    sitzung: AsyncSession, benutzer_id: uuid.UUID, rolle: Rolle, eigene_id: uuid.UUID
) -> Benutzer:
    if benutzer_id == eigene_id and rolle is not Rolle.INHABER:
        raise VerwaltungFehler(
            "Sie können sich nicht selbst die Inhaberrolle entziehen. Bitten Sie einen "
            "anderen Inhaber darum."
        )
    benutzer = (
        await sitzung.execute(select(Benutzer).where(Benutzer.id == benutzer_id))
    ).scalar_one_or_none()
    if benutzer is None:
        raise VerwaltungFehler("Diese Person gehört nicht zu Ihrem Büro.")
    if benutzer.rolle is Rolle.INHABER and rolle is not Rolle.INHABER:
        verbleibend = (
            await sitzung.execute(
                select(func.count())
                .select_from(Benutzer)
                .where(Benutzer.rolle == Rolle.INHABER, Benutzer.aktiv.is_(True))
            )
        ).scalar_one()
        if int(verbleibend) <= 1:
            raise VerwaltungFehler("Das Büro braucht mindestens einen Inhaber.")
    benutzer.rolle = rolle
    await sitzung.flush()
    return benutzer


async def zugang_sperren(
    sitzung: AsyncSession, benutzer_id: uuid.UUID, eigene_id: uuid.UUID
) -> Benutzer:
    if benutzer_id == eigene_id:
        raise VerwaltungFehler("Sie können sich nicht selbst sperren.")
    benutzer = (
        await sitzung.execute(select(Benutzer).where(Benutzer.id == benutzer_id))
    ).scalar_one_or_none()
    if benutzer is None:
        raise VerwaltungFehler("Diese Person gehört nicht zu Ihrem Büro.")
    benutzer.aktiv = not benutzer.aktiv
    await sitzung.flush()
    if not benutzer.aktiv:
        from belegwerk.kern.anmeldung import alle_sitzungen_beenden

        await alle_sitzungen_beenden(benutzer.id)
    return benutzer
