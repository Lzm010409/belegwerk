"""Kernmodelle: Mandant, Benutzer, Sitzung, Einladung, Abonnement, Auftrag."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belegwerk.basis import Basis, MandantMixin, ZeitstempelMixin, uuid_spalte


class Modul(str, enum.Enum):
    DELTA = "delta"
    ATLAS = "atlas"
    CHECK = "check"


class Rolle(str, enum.Enum):
    """Zwei Rollen reichen (Querschnitt 8.7)."""

    INHABER = "inhaber"
    MITARBEITER = "mitarbeiter"


class AbonnementStatus(str, enum.Enum):
    TESTPHASE = "testphase"
    AKTIV = "aktiv"
    GEKUENDIGT = "gekuendigt"
    ABGELAUFEN = "abgelaufen"


class AuftragStatus(str, enum.Enum):
    WARTET = "wartet"
    LAEUFT = "laeuft"
    FERTIG = "fertig"
    FEHLGESCHLAGEN = "fehlgeschlagen"


def _enum(typ: type[enum.Enum], name: str) -> Enum:
    return Enum(typ, name=name, values_callable=lambda e: [glied.value for glied in e])


class Mandant(Basis, ZeitstempelMixin):
    """Ein Sachverständigenbüro. Die Trennungseinheit der gesamten Plattform."""

    __tablename__ = "mandant"

    id: Mapped[uuid.UUID] = uuid_spalte()
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Briefkopf für die erzeugten Anlagen
    briefkopf_zeilen: Mapped[str | None] = mapped_column(Text)
    logo_pfad: Mapped[str | None] = mapped_column(String(500))
    aktenzeichen_muster: Mapped[str | None] = mapped_column(String(200))

    # Ein Büro, das keine Daten außer Haus geben will, muss das Produkt voll
    # nutzen können (Plattformdatei Abschnitt 8).
    llm_pfad_aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Kontolöschung mit Karenz (Querschnitt 7.3)
    loeschung_beantragt_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    benutzer: Mapped[list[Benutzer]] = relationship(back_populates="mandant", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Mandant {self.id}>"


class Benutzer(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "benutzer"
    __table_args__ = (UniqueConstraint("email", name="uq_benutzer_email"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    passwort_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rolle: Mapped[Rolle] = mapped_column(_enum(Rolle, "rolle"), nullable=False, default=Rolle.MITARBEITER)
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    letzte_anmeldung: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mandant: Mapped[Mandant] = relationship(back_populates="benutzer", lazy="joined")

    @property
    def ist_inhaber(self) -> bool:
        return self.rolle is Rolle.INHABER


class Sitzung(Basis, MandantMixin):
    """Serverseitige Sitzung. Das Cookie trägt nur einen Zufallswert."""

    __tablename__ = "sitzung"

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benutzer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    angelegt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    laeuft_ab: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    benutzer: Mapped[Benutzer] = relationship(lazy="joined")


class Einladung(Basis, MandantMixin, ZeitstempelMixin):
    """Registrierung ist nur per Einladungscode möglich (Delta-Todo 1.3)."""

    __tablename__ = "einladung"

    id: Mapped[uuid.UUID] = uuid_spalte()
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    rolle: Mapped[Rolle] = mapped_column(_enum(Rolle, "rolle"), nullable=False, default=Rolle.MITARBEITER)
    laeuft_ab: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eingeloest_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erstellt_von_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )


class PasswortMarke(Basis, MandantMixin):
    """Einmalmarke zum Zurücksetzen des Passworts."""

    __tablename__ = "passwort_marke"

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benutzer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marke_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    laeuft_ab: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eingeloest_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    angelegt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Abonnement(Basis, MandantMixin, ZeitstempelMixin):
    """Modulzugriff prüft gegen ein aktives Abonnement, nicht gegen ein Flag
    (Querschnitt 2.2)."""

    __tablename__ = "abonnement"
    __table_args__ = (UniqueConstraint("mandant_id", "modul", name="uq_abonnement_mandant_modul"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    modul: Mapped[Modul] = mapped_column(_enum(Modul, "modul"), nullable=False)
    status: Mapped[AbonnementStatus] = mapped_column(
        _enum(AbonnementStatus, "abonnement_status"), nullable=False
    )
    beginn: Mapped[date] = mapped_column(Date, nullable=False)
    ende: Mapped[date | None] = mapped_column(Date)
    preis_monat: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))


class Auftrag(Basis, MandantMixin):
    """Hintergrundauftrag (ADR 0003). Parsing läuft nicht im Request."""

    __tablename__ = "auftrag"
    __table_args__ = (Index("ix_auftrag_status_angelegt", "status", "angelegt_am"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    art: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[AuftragStatus] = mapped_column(
        _enum(AuftragStatus, "auftrag_status"), nullable=False, default=AuftragStatus.WARTET
    )
    nutzlast: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fortschritt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schritt: Mapped[str | None] = mapped_column(String(200))
    fehlertext: Mapped[str | None] = mapped_column(Text)
    versuche: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    angelegt_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gestartet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    beendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dauer_ms: Mapped[int | None] = mapped_column(Integer)


class Rueckmeldung(Basis, MandantMixin, ZeitstempelMixin):
    """Rückmeldeknopf aus der Oberfläche (Querschnitt 8.8)."""

    __tablename__ = "rueckmeldung"

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    seite: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    erledigt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Zugangsanfrage(Basis, ZeitstempelMixin):
    """Formular der Landingpages. Nicht mandantenbezogen — es gibt noch keinen."""

    __tablename__ = "zugangsanfrage"

    id: Mapped[uuid.UUID] = uuid_spalte()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    buero: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    plz: Mapped[str | None] = mapped_column(String(10))
    modul: Mapped[str | None] = mapped_column(String(20))
    bearbeitet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
