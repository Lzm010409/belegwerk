"""Passwörter: Argon2id (Delta-Todo 1.3)."""

from __future__ import annotations

import secrets
import unicodedata

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Parameter nach der Empfehlung des BSI/OWASP für interaktive Anmeldungen.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16, type=Type.ID)

MINDESTLAENGE = 12


class PasswortZuSchwach(Exception):
    """Enthält im Klartext, was fehlt."""


def normalisieren(passwort: str) -> str:
    """Unicode-Normalform, damit dasselbe Passwort von zwei Tastaturen passt."""
    return unicodedata.normalize("NFKC", passwort)


def staerke_pruefen(passwort: str) -> None:
    passwort = normalisieren(passwort)
    if len(passwort) < MINDESTLAENGE:
        raise PasswortZuSchwach(
            f"Das Passwort ist {len(passwort)} Zeichen lang. Nötig sind mindestens "
            f"{MINDESTLAENGE}. Eine Wortfolge aus vier Wörtern erfüllt das mühelos."
        )
    if passwort.strip() != passwort:
        raise PasswortZuSchwach("Das Passwort darf nicht mit einem Leerzeichen beginnen oder enden.")
    if len(set(passwort)) < 5:
        raise PasswortZuSchwach("Das Passwort besteht aus zu wenigen verschiedenen Zeichen.")


def hashen(passwort: str) -> str:
    staerke_pruefen(passwort)
    return _hasher.hash(normalisieren(passwort))


def pruefen(passwort: str, gespeicherter_hash: str) -> bool:
    try:
        return _hasher.verify(gespeicherter_hash, normalisieren(passwort))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def muss_neu_gehasht_werden(gespeicherter_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(gespeicherter_hash)
    except InvalidHashError:
        return True


def marke_erzeugen() -> str:
    """Zufallsmarke für Sitzungscookie, Einladung und Passwortrücksetzung."""
    return secrets.token_urlsafe(32)
