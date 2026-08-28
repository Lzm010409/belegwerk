"""Zentrale Konfiguration. Alle Werte kommen aus Umgebungsvariablen."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Einstellungen(BaseSettings):
    """Laufzeitkonfiguration der Anwendung.

    Secrets kommen ausschliesslich aus der Umgebung (Coolify), niemals aus einer
    im Image mitgelieferten Datei.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    datenbank_url: str = Field(
        default="postgresql+asyncpg://belegwerk:belegwerk@localhost:5432/belegwerk",
        validation_alias="DATABASE_URL",
    )
    sitzung_geheimnis: str = Field(
        default_factory=lambda: secrets.token_urlsafe(48),
        validation_alias="SITZUNG_GEHEIMNIS",
    )
    app_basis_url: str = Field(default="http://localhost:8000", validation_alias="APP_BASIS_URL")
    umgebung: str = Field(default="entwicklung", validation_alias="UMGEBUNG")

    daten_verzeichnis: Path = Field(default=Path("/data"), validation_alias="DATEN_VERZEICHNIS")

    erster_admin_email: str | None = Field(default=None, validation_alias="ERSTER_ADMIN_EMAIL")
    erster_admin_name: str | None = Field(default=None, validation_alias="ERSTER_ADMIN_NAME")
    erster_admin_passwort: str | None = Field(default=None, validation_alias="ERSTER_ADMIN_PASSWORT")
    erster_admin_buero: str = Field(
        default="Belegwerk Betrieb", validation_alias="ERSTER_ADMIN_BUERO"
    )

    # Aufbewahrung (Plattformdatei Abschnitt 5)
    aufbewahrung_uploads_tage: int = Field(default=90, validation_alias="AUFBEWAHRUNG_UPLOADS_TAGE")
    aufbewahrung_ergebnisse_tage: int = Field(
        default=365, validation_alias="AUFBEWAHRUNG_ERGEBNISSE_TAGE"
    )
    testphase_tage: int = Field(default=30, validation_alias="TESTPHASE_TAGE")
    konto_karenz_tage: int = Field(default=14, validation_alias="KONTO_KARENZ_TAGE")

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES")
    max_seiten: int = Field(default=200, validation_alias="MAX_SEITEN")

    # SMTP; ohne Konfiguration werden Mails nur protokolliert.
    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="SMTP_PORT")
    smtp_benutzer: str | None = Field(default=None, validation_alias="SMTP_BENUTZER")
    smtp_passwort: str | None = Field(default=None, validation_alias="SMTP_PASSWORT")
    smtp_absender: str = Field(default="noreply@belegwerk.de", validation_alias="SMTP_ABSENDER")
    betreiber_email: str | None = Field(default=None, validation_alias="BETREIBER_EMAIL")

    # LLM-Pfad; ohne Schluessel bleibt er global aus.
    mistral_api_schluessel: str | None = Field(
        default=None, validation_alias="MISTRAL_API_SCHLUESSEL"
    )
    mistral_basis_url: str = Field(
        default="https://api.mistral.ai/v1", validation_alias="MISTRAL_BASIS_URL"
    )
    mistral_modell: str = Field(default="mistral-small-latest", validation_alias="MISTRAL_MODELL")

    # Offene Dropzone der Check-Landingpage
    oeffentliche_pruefung_aktiv: bool = Field(
        default=True, validation_alias="OEFFENTLICHE_PRUEFUNG_AKTIV"
    )

    @field_validator("datenbank_url")
    @classmethod
    def _asyncpg_treiber(cls, wert: str) -> str:
        """Coolify liefert `postgres://` bzw. `postgresql://` — auf asyncpg heben."""
        if wert.startswith("postgres://"):
            wert = "postgresql://" + wert[len("postgres://") :]
        if wert.startswith("postgresql://"):
            wert = "postgresql+asyncpg://" + wert[len("postgresql://") :]
        return wert

    @property
    def datenbank_url_sync(self) -> str:
        """Synchrone Variante fuer Alembic."""
        return self.datenbank_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )

    @property
    def upload_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "uploads"

    @property
    def ausgabe_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "ausgaben"

    @property
    def ist_produktion(self) -> bool:
        return self.umgebung.lower() in {"produktion", "production", "prod"}


@lru_cache(maxsize=1)
def einstellungen() -> Einstellungen:
    return Einstellungen()
