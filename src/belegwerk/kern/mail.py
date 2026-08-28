"""E-Mail-Versand (Querschnitt 3).

Grundregel 3.3: keine Kundendaten im Mailtext. „Ihre Prüfung ist fertig" mit
Link, nicht das Ergebnis selbst. Die Vorlagen in diesem Modul halten sich
daran; neue Mails gehören hierher und nirgendwo sonst.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from belegwerk.konfiguration import einstellungen

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Nachricht:
    empfaenger: str
    betreff: str
    text: str


def senden(nachricht: Nachricht) -> bool:
    """Verschickt die Nachricht. Ohne SMTP-Konfiguration nur protokolliert.

    Gibt zurück, ob tatsächlich versendet wurde — der Aufrufer entscheidet, ob
    er das dem Benutzer sagt.
    """
    konfiguration = einstellungen()
    if not konfiguration.smtp_host:
        _log.info(
            "Mail nicht versendet (kein SMTP konfiguriert)",
            extra={"betreff": nachricht.betreff},
        )
        return False

    mail = EmailMessage()
    mail["From"] = konfiguration.smtp_absender
    mail["To"] = nachricht.empfaenger
    mail["Subject"] = nachricht.betreff
    mail.set_content(nachricht.text)

    try:
        with smtplib.SMTP(konfiguration.smtp_host, konfiguration.smtp_port, timeout=15) as server:
            server.starttls()
            if konfiguration.smtp_benutzer and konfiguration.smtp_passwort:
                server.login(konfiguration.smtp_benutzer, konfiguration.smtp_passwort)
            server.send_message(mail)
    except Exception as fehler:  # noqa: BLE001 — Versand darf keinen Vorgang abbrechen
        _log.error(
            "Mailversand fehlgeschlagen",
            extra={"betreff": nachricht.betreff, "fehlerart": type(fehler).__name__},
        )
        return False
    _log.info("Mail versendet", extra={"betreff": nachricht.betreff})
    return True


def einladung(empfaenger: str, buero: str, link: str) -> Nachricht:
    return Nachricht(
        empfaenger=empfaenger,
        betreff="Ihr Zugang zu Belegwerk",
        text=(
            f"Guten Tag,\n\n"
            f"für das Büro {buero} wurde ein Zugang zu Belegwerk eingerichtet.\n"
            f"Über den folgenden Link legen Sie Ihr Passwort fest:\n\n{link}\n\n"
            "Der Link gilt sieben Tage.\n\n"
            "Belegwerk"
        ),
    )


def passwort_zuruecksetzen(empfaenger: str, link: str) -> Nachricht:
    return Nachricht(
        empfaenger=empfaenger,
        betreff="Passwort zurücksetzen",
        text=(
            "Guten Tag,\n\n"
            "für Ihr Belegwerk-Konto wurde eine Passwortrücksetzung angefordert.\n"
            f"Über den folgenden Link vergeben Sie ein neues Passwort:\n\n{link}\n\n"
            "Der Link gilt zwei Stunden. Haben Sie die Rücksetzung nicht angefordert, "
            "können Sie diese Nachricht ignorieren.\n\n"
            "Belegwerk"
        ),
    )


def verarbeitung_fehlgeschlagen(empfaenger: str, link: str) -> Nachricht:
    return Nachricht(
        empfaenger=empfaenger,
        betreff="Verarbeitung fehlgeschlagen",
        text=(
            "Guten Tag,\n\n"
            "ein Vorgang in Belegwerk konnte nicht verarbeitet werden.\n"
            f"Die Einzelheiten stehen im Vorgang selbst:\n\n{link}\n\n"
            "Belegwerk"
        ),
    )


def erhebung_veraltet(empfaenger: str, anzahl: int, link: str) -> Nachricht:
    return Nachricht(
        empfaenger=empfaenger,
        betreff="Erhebungen zur Nachprüfung",
        text=(
            "Guten Tag,\n\n"
            f"{anzahl} Ihrer Erhebungen im Stundensatz-Register sind älter als "
            "24 Monate und zählen deshalb nicht mehr in den Median.\n"
            f"Übersicht:\n\n{link}\n\n"
            "Belegwerk"
        ),
    )


def abo_laeuft_aus(empfaenger: str, modul: str, link: str) -> Nachricht:
    return Nachricht(
        empfaenger=empfaenger,
        betreff=f"Testphase {modul} läuft aus",
        text=(
            "Guten Tag,\n\n"
            f"die Testphase für das Modul {modul} endet in Kürze. Danach bleiben Ihre "
            "Daten lesbar; neue Vorgänge lassen sich nicht mehr anlegen.\n"
            f"Verwaltung:\n\n{link}\n\n"
            "Belegwerk"
        ),
    )
