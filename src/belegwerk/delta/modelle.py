"""Datenmodell für Delta (Briefing Abschnitt 3)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belegwerk.basis import Basis, MandantMixin, ZeitstempelMixin, uuid_spalte
from belegwerk.delta.klassifikation import Klasse
from belegwerk.dokumente.modell import PositionsArt


class VorgangStatus(str, enum.Enum):
    ANGELEGT = "angelegt"
    VERARBEITUNG = "verarbeitung"
    KORREKTUR_NOETIG = "korrektur_noetig"
    FERTIG = "fertig"
    FEHLGESCHLAGEN = "fehlgeschlagen"


class Dokumentrolle(str, enum.Enum):
    EIGEN = "eigen"
    PRUEFBERICHT = "pruefbericht"


def _enum(typ: type[enum.Enum], name: str) -> Enum:
    return Enum(typ, name=name, values_callable=lambda e: [glied.value for glied in e])


class Vorgang(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "delta_vorgang"
    __table_args__ = (Index("ix_delta_vorgang_suche", "mandant_id", "aktenzeichen", "kennzeichen"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    aktenzeichen: Mapped[str | None] = mapped_column(String(120))
    kennzeichen: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[VorgangStatus] = mapped_column(
        _enum(VorgangStatus, "delta_vorgang_status"), nullable=False
    )
    fehlertext: Mapped[str | None] = mapped_column(Text)
    auftrag_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auftrag.id", ondelete="SET NULL"))

    # Ergebnis der Auswertung; die Einzelabweichungen stehen in ihrer Tabelle.
    ergebnis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    dokumente: Mapped[list[Dokument]] = relationship(
        back_populates="vorgang", cascade="all, delete-orphan", lazy="selectin"
    )
    abweichungen: Mapped[list[Abweichung]] = relationship(
        back_populates="vorgang", cascade="all, delete-orphan", lazy="selectin"
    )

    def dokument(self, rolle: Dokumentrolle) -> Dokument | None:
        for eintrag in self.dokumente:
            if eintrag.rolle is rolle:
                return eintrag
        return None

    @property
    def braucht_korrektur(self) -> bool:
        return any(d.konfidenz < 0.85 for d in self.dokumente)


class Dokument(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "delta_dokument"

    id: Mapped[uuid.UUID] = uuid_spalte()
    vorgang_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("delta_vorgang.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rolle: Mapped[Dokumentrolle] = mapped_column(
        _enum(Dokumentrolle, "delta_dokumentrolle"), nullable=False
    )
    dateiname: Mapped[str] = mapped_column(String(300), nullable=False)
    dokument_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quellformat: Mapped[str] = mapped_column(String(10), nullable=False)
    adapter: Mapped[str] = mapped_column(String(60), nullable=False)
    konfidenz: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    upload_pfad: Mapped[str | None] = mapped_column(String(500))
    rohtext_pfad: Mapped[str | None] = mapped_column(String(500))
    hinweise: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    fahrzeug: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    saetze: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    summen: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    vorgang: Mapped[Vorgang] = relationship(back_populates="dokumente")
    positionen: Mapped[list[Position]] = relationship(
        back_populates="dokument",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Position.laufnummer",
    )


class Position(Basis, MandantMixin):
    __tablename__ = "delta_position"

    id: Mapped[uuid.UUID] = uuid_spalte()
    dokument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("delta_dokument.id", ondelete="CASCADE"), nullable=False, index=True
    )
    laufnummer: Mapped[int] = mapped_column(Integer, nullable=False)
    art: Mapped[PositionsArt] = mapped_column(_enum(PositionsArt, "delta_positionsart"), nullable=False)
    bezeichnung: Mapped[str] = mapped_column(String(400), nullable=False)
    teilenummer: Mapped[str | None] = mapped_column(String(80))
    arbeitswerte: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    stundensatz: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    lackstufe: Mapped[int | None] = mapped_column(Integer)
    einzelpreis: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    aufschlag_prozent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    betrag: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    rohzeile: Mapped[str] = mapped_column(Text, nullable=False, default="")

    dokument: Mapped[Dokument] = relationship(back_populates="positionen")


class Abweichung(Basis, MandantMixin):
    __tablename__ = "delta_abweichung"

    id: Mapped[uuid.UUID] = uuid_spalte()
    vorgang_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("delta_vorgang.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_a_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delta_position.id", ondelete="SET NULL")
    )
    position_b_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delta_position.id", ondelete="SET NULL")
    )
    klasse: Mapped[Klasse] = mapped_column(_enum(Klasse, "delta_klasse"), nullable=False)
    art: Mapped[PositionsArt] = mapped_column(
        _enum(PositionsArt, "delta_positionsart"), nullable=False
    )
    laufnummer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bezeichnung: Mapped[str] = mapped_column(String(400), nullable=False)
    differenz_netto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    wert_eigen: Mapped[str | None] = mapped_column(String(120))
    wert_pruefbericht: Mapped[str | None] = mapped_column(String(120))
    beleg_eigen: Mapped[str | None] = mapped_column(Text)
    beleg_pruefbericht: Mapped[str | None] = mapped_column(Text)
    match_stufe: Mapped[int | None] = mapped_column(Integer)
    match_konfidenz: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    kommentar: Mapped[str | None] = mapped_column(Text)

    vorgang: Mapped[Vorgang] = relationship(back_populates="abweichungen")


class KorrekturLog(Basis, MandantMixin):
    """Jede Korrektur wird gespeichert (Plattformdatei 4.3).

    Sie dient später als Trainingsmaterial für Adapterverbesserungen — deshalb
    mit altem und neuem Wert, nicht nur mit dem Ergebnis.
    """

    __tablename__ = "delta_korrektur_log"

    id: Mapped[uuid.UUID] = uuid_spalte()
    dokument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("delta_dokument.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("delta_position.id", ondelete="SET NULL")
    )
    feld: Mapped[str] = mapped_column(String(80), nullable=False)
    wert_alt: Mapped[str | None] = mapped_column(String(400))
    wert_neu: Mapped[str | None] = mapped_column(String(400))
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    zeit: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
