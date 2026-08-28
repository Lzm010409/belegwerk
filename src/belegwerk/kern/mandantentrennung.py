"""Mandantentrennung — in der Datenbank erzwungen, nicht nur in der Anwendung.

Querschnitt 1: Der gefährlichste denkbare Fehler dieser Plattform ist ein
Sachverständiger, der das Gutachten eines Kollegen sieht. Die Trennung darf
deshalb nicht davon abhängen, dass jede Abfrage brav ihr ``WHERE mandant_id = ?``
mitbringt.

Aufbau
------
1. Jede mandantenbezogene Tabelle erbt von ``MandantMixin`` und hat damit
   ``mandant_id NOT NULL``.
2. Auf jeder dieser Tabellen liegt eine Row-Level-Security-Policy, die
   ``current_setting('app.mandant_id')`` auswertet. Ist die Variable nicht
   gesetzt, liefert die Abfrage null Zeilen — kein Ergebnis ist besser als ein
   fremdes.
3. Die Anwendung arbeitet in Anfragen unter der Rolle ``belegwerk_app``. Diese
   Rolle ist bewusst **kein** Superuser: PostgreSQL umgeht Row Level Security
   für Superuser vollständig, und der von Coolify angelegte Datenbankbenutzer
   ist einer. ``SET LOCAL ROLE`` wechselt deshalb für die Dauer der Transaktion
   auf die eingeschränkte Rolle.
4. Nur Anmeldung und Wartungsjobs laufen unter der Eigentümerrolle
   (``rohe_sitzung``), weil sie mandantenübergreifend arbeiten müssen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.basis import Basis, MandantMixin
from belegwerk.datenbank import sitzungsfabrik

APP_ROLLE = "belegwerk_app"
SITZUNGSVARIABLE = "app.mandant_id"


def mandantentabellen() -> list[Table]:
    """Alle mandantenbezogenen Tabellen, über Introspektion des Modellregisters.

    Bewusst nicht über eine gepflegte Liste: die wird beim nächsten Modell
    vergessen (Querschnitt 1.3).
    """
    tabellen: list[Table] = []
    for mapper in Basis.registry.mappers:
        tabelle = mapper.local_table
        if issubclass(mapper.class_, MandantMixin) and isinstance(tabelle, Table):
            tabellen.append(tabelle)
    return sorted(tabellen, key=lambda t: t.name)


def _policy_name(tabelle: str) -> str:
    return f"{tabelle}_mandant"


def rls_aktivieren_sql(tabellennamen: Iterable[str]) -> list[str]:
    """SQL, das RLS für die genannten Tabellen einschaltet.

    ``NULLIF(...,'')`` verhindert, dass eine leere Sitzungsvariable beim Cast
    auf ``uuid`` einen Fehler wirft; sie wird zu ``NULL`` und die Bedingung
    damit unerfüllbar.
    """
    anweisungen: list[str] = []
    for tabelle in tabellennamen:
        anweisungen += [
            f"ALTER TABLE {tabelle} ENABLE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS {_policy_name(tabelle)} ON {tabelle}",
            (
                f"CREATE POLICY {_policy_name(tabelle)} ON {tabelle} "
                f"USING (mandant_id = NULLIF(current_setting('{SITZUNGSVARIABLE}', true), '')::uuid) "
                f"WITH CHECK (mandant_id = NULLIF(current_setting('{SITZUNGSVARIABLE}', true), '')::uuid)"
            ),
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabelle} TO {APP_ROLLE}",
        ]
    return anweisungen


def app_rolle_anlegen_sql() -> list[str]:
    return [
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLLE}') THEN
            CREATE ROLE {APP_ROLLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
          END IF;
        END
        $$
        """,
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLLE}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLLE}",
    ]


def mandant_tabelle_absichern_sql() -> list[str]:
    """Die Tabelle ``mandant`` selbst: sichtbar ist nur der eigene Datensatz."""
    return [
        "ALTER TABLE mandant ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS mandant_selbst ON mandant",
        (
            "CREATE POLICY mandant_selbst ON mandant "
            f"USING (id = NULLIF(current_setting('{SITZUNGSVARIABLE}', true), '')::uuid) "
            f"WITH CHECK (id = NULLIF(current_setting('{SITZUNGSVARIABLE}', true), '')::uuid)"
        ),
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON mandant TO {APP_ROLLE}",
    ]


async def kontext_setzen(sitzung: AsyncSession, mandant_id: uuid.UUID) -> None:
    """Setzt Rolle und Mandantenvariable für die laufende Transaktion."""
    await sitzung.execute(text(f"SET LOCAL ROLE {APP_ROLLE}"))
    await sitzung.execute(
        text(f"SELECT set_config('{SITZUNGSVARIABLE}', :wert, true)"),
        {"wert": str(mandant_id)},
    )


@asynccontextmanager
async def mandanten_sitzung(mandant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Datenbanksitzung, die ausschließlich Daten dieses Mandanten sieht."""
    async with sitzungsfabrik()() as sitzung:
        await kontext_setzen(sitzung, mandant_id)
        try:
            yield sitzung
            await sitzung.commit()
        except Exception:
            await sitzung.rollback()
            raise
