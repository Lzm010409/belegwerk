"""Datenmodell für Check (Briefing Abschnitt 4)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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
from belegwerk.check.regelmaschine import Schwere


class PruefungStatus(str, enum.Enum):
    LAEUFT = "laeuft"
    FERTIG = "fertig"
    FEHLGESCHLAGEN = "fehlgeschlagen"


class Regelherkunft(str, enum.Enum):
    GLOBAL = "global"  # Regel aus dem Startkatalog; hier nur der Schalter
    EIGEN = "eigen"  # vom Büro selbst angelegt


def _enum(typ: type[enum.Enum], name: str) -> Enum:
    return Enum(typ, name=name, values_callable=lambda e: [glied.value for glied in e])


class Pruefung(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "check_pruefung"
    __table_args__ = (Index("ix_check_pruefung_aktenzeichen", "mandant_id", "aktenzeichen"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    aktenzeichen: Mapped[str | None] = mapped_column(String(120), index=True)
    dateiname: Mapped[str] = mapped_column(String(300), nullable=False)
    dokument_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    upload_pfad: Mapped[str | None] = mapped_column(String(500))
    seiten: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gutachtenart: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[PruefungStatus] = mapped_column(
        _enum(PruefungStatus, "check_pruefung_status"), nullable=False
    )
    fehlertext: Mapped[str | None] = mapped_column(Text)
    extraktion: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    konfidenz: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    geprueft_regeln: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nicht_entscheidbar: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    fehlende_pflichtfelder: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    befunde: Mapped[list[Befund]] = relationship(
        back_populates="pruefung", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def offene_befunde(self) -> list[Befund]:
        return [b for b in self.befunde if b.quittiert_am is None]


class Befund(Basis, MandantMixin):
    __tablename__ = "check_befund"

    id: Mapped[uuid.UUID] = uuid_spalte()
    pruefung_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("check_pruefung.id", ondelete="CASCADE"), nullable=False, index=True
    )
    regel_id: Mapped[str] = mapped_column(String(80), nullable=False)
    nummer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schwere: Mapped[Schwere] = mapped_column(_enum(Schwere, "check_schwere"), nullable=False)
    titel: Mapped[str] = mapped_column(String(300), nullable=False)
    meldung: Mapped[str] = mapped_column(Text, nullable=False)
    feldwerte: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    seite: Mapped[int | None] = mapped_column(Integer)
    ausschnitt: Mapped[str | None] = mapped_column(Text)

    # Quittierung ist Kernfunktion (Briefing 4): ein Werkzeug, das man nicht
    # überstimmen kann, wird nach der dritten falsch-positiven Meldung ignoriert.
    quittiert_von_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    quittiert_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quittierungsgrund: Mapped[str | None] = mapped_column(Text)

    pruefung: Mapped[Pruefung] = relationship(back_populates="befunde")


class CheckRegel(Basis, MandantMixin, ZeitstempelMixin):
    """Eigene Regeln und Schalter für die Regeln des Startkatalogs.

    Der Startkatalog liegt als YAML im Image und ist für alle Mandanten gleich.
    Diese Tabelle hält nur die Abweichungen davon: abgeschaltete globale Regeln
    (``herkunft = global``) und eigene Regeln (``herkunft = eigen``).
    """

    __tablename__ = "check_regel"
    __table_args__ = (UniqueConstraint("mandant_id", "kennung", name="uq_check_regel_kennung"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    kennung: Mapped[str] = mapped_column(String(80), nullable=False)
    herkunft: Mapped[Regelherkunft] = mapped_column(
        _enum(Regelherkunft, "check_regelherkunft"), nullable=False
    )
    aktiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    yaml_quelle: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CheckFeldmuster(Basis, MandantMixin, ZeitstempelMixin):
    """Mandanteneigene Labelmuster; sie gehen den globalen vor (Todo 1.4)."""

    __tablename__ = "check_feldmuster"
    __table_args__ = (
        UniqueConstraint("mandant_id", "feld", "muster", name="uq_check_feldmuster"),
    )

    id: Mapped[uuid.UUID] = uuid_spalte()
    feld: Mapped[str] = mapped_column(String(80), nullable=False)
    muster: Mapped[str] = mapped_column(String(300), nullable=False)
    prioritaet: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
