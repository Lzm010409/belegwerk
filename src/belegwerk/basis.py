"""Deklarative Basis und gemeinsame Bausteine aller Datenmodelle."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMENSKONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Basis(DeclarativeBase):
    """Gemeinsame Basis. Die Namenskonvention macht Migrationen wiederholbar."""

    metadata = MetaData(naming_convention=NAMENSKONVENTION)

    type_annotation_map = {
        uuid.UUID: PgUUID(as_uuid=True),
    }


def uuid_spalte() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ZeitstempelMixin:
    """``angelegt_am`` und ``geaendert_am`` fuer jede Tabelle."""

    angelegt_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    geaendert_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MandantMixin:
    """Kennzeichnet eine mandantenbezogene Tabelle.

    Jede Tabelle mit diesem Mixin bekommt ``mandant_id NOT NULL`` (Querschnitt
    1.1) und eine Row-Level-Security-Policy (Querschnitt 1.2). Der Test in
    ``tests/test_mandantentrennung.py`` findet diese Tabellen ueber
    Introspektion — nicht ueber eine Liste, die beim naechsten Modell vergessen
    wird.
    """

    @property
    def _mandant_marker(self) -> bool:
        return True

    mandant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mandant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def ist_mandantentabelle(modell: Any) -> bool:
    """Ob ein Modell mandantenbezogen ist — ueber die Vererbung, nicht ueber Namen."""
    return isinstance(modell, type) and issubclass(modell, MandantMixin)
