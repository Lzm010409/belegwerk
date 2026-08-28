"""Datenmodell für Atlas (Briefing Abschnitt 3)."""

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
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belegwerk.basis import Basis, MandantMixin, ZeitstempelMixin, uuid_spalte


class Betriebsart(str, enum.Enum):
    MARKENGEBUNDEN = "markengebunden"
    MARKENGEBUNDEN_MEHRMARKEN = "markengebunden_mehrmarken"
    FREI = "frei"

    @property
    def beschriftung(self) -> str:
        return {
            "markengebunden": "markengebunden",
            "markengebunden_mehrmarken": "markengebunden, mehrere Marken",
            "frei": "freie Werkstatt",
        }[self.value]


class Erhebungsart(str, enum.Enum):
    """Jede Art trägt ihre Belastbarkeit (Briefing Abschnitt 2)."""

    PREISAUSHANG = "preisaushang"
    RECHNUNG = "rechnung"
    SCHRIFTLICH = "schriftlich"
    TELEFONISCH = "telefonisch"
    FREMDKALKULATION = "fremdkalkulation"

    @property
    def beschriftung(self) -> str:
        return {
            "preisaushang": "Preisaushang fotografiert",
            "rechnung": "Werkstattrechnung aus eigenem Fall",
            "schriftlich": "schriftliche Auskunft des Betriebs",
            "telefonisch": "telefonische Auskunft",
            "fremdkalkulation": "Angabe aus fremder Kalkulation",
        }[self.value]

    @property
    def belastbarkeit(self) -> str:
        return {
            "preisaushang": "hoch",
            "rechnung": "hoch",
            "schriftlich": "hoch",
            "telefonisch": "mittel",
            "fremdkalkulation": "niedrig",
        }[self.value]

    @property
    def rang(self) -> int:
        return {"hoch": 0, "mittel": 1, "niedrig": 2}[self.belastbarkeit]

    @property
    def nachweis_pflicht(self) -> bool:
        """Bei diesen Arten ist ein Dokument die Grundlage der Aussage."""
        return self in {Erhebungsart.PREISAUSHANG, Erhebungsart.RECHNUNG, Erhebungsart.SCHRIFTLICH}


def _enum(typ: type[enum.Enum], name: str) -> Enum:
    return Enum(typ, name=name, values_callable=lambda e: [glied.value for glied in e])


class Betrieb(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "atlas_betrieb"
    __table_args__ = (Index("ix_atlas_betrieb_plz", "mandant_id", "plz"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strasse: Mapped[str | None] = mapped_column(String(200))
    plz: Mapped[str] = mapped_column(String(5), nullable=False)
    ort: Mapped[str] = mapped_column(String(120), nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    art: Mapped[Betriebsart] = mapped_column(_enum(Betriebsart, "atlas_betriebsart"), nullable=False)
    marken: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    geprueft_am: Mapped[date | None] = mapped_column(Date)

    erhebungen: Mapped[list[Erhebung]] = relationship(
        back_populates="betrieb", cascade="all, delete-orphan", lazy="selectin"
    )


class Erhebung(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "atlas_erhebung"
    __table_args__ = (Index("ix_atlas_erhebung_datum", "mandant_id", "erhebungsdatum"),)

    id: Mapped[uuid.UUID] = uuid_spalte()
    betrieb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atlas_betrieb.id", ondelete="CASCADE"), nullable=False, index=True
    )
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    erhebungsdatum: Mapped[date] = mapped_column(Date, nullable=False)
    art: Mapped[Erhebungsart] = mapped_column(_enum(Erhebungsart, "atlas_erhebungsart"), nullable=False)

    satz_mechanik: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    satz_karosserie: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    satz_elektrik: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    satz_lack_lohn: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    lack_material_prozent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    lack_material_pauschale: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    upe_aufschlag_prozent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    verbringung_pauschale: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    entsorgung: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))

    bemerkung: Mapped[str | None] = mapped_column(Text)

    # Voreinstellung aus. Der Pool ist eine bewusste Einzelentscheidung
    # je Erhebung (Briefing Abschnitt 5).
    im_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    erinnert_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    betrieb: Mapped[Betrieb] = relationship(back_populates="erhebungen", lazy="joined")
    nachweise: Mapped[list[Nachweis]] = relationship(
        back_populates="erhebung", cascade="all, delete-orphan", lazy="selectin"
    )

    def alter_monate(self, stichtag: date | None = None) -> int:
        heute = stichtag or date.today()
        return (heute.year - self.erhebungsdatum.year) * 12 + (heute.month - self.erhebungsdatum.month)

    def veraltet(self, stichtag: date | None = None) -> bool:
        """Über 24 Monate: sichtbar, aber nicht im Median (Briefing Abschnitt 2)."""
        return self.alter_monate(stichtag) > 24


class Nachweis(Basis, MandantMixin):
    """Nachweise bleiben immer beim Erfasser — auch im Pool (Briefing 5)."""

    __tablename__ = "atlas_nachweis"

    id: Mapped[uuid.UUID] = uuid_spalte()
    erhebung_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atlas_erhebung.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dateiname: Mapped[str] = mapped_column(String(300), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pfad: Mapped[str] = mapped_column(String(500), nullable=False)
    bytes_gross: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hochgeladen_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exif_entfernt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    erhebung: Mapped[Erhebung] = relationship(back_populates="nachweise")


class Auswertung(Basis, MandantMixin, ZeitstempelMixin):
    __tablename__ = "atlas_auswertung"

    id: Mapped[uuid.UUID] = uuid_spalte()
    benutzer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("benutzer.id", ondelete="SET NULL")
    )
    plz_zentrum: Mapped[str] = mapped_column(String(5), nullable=False)
    radius_km: Mapped[int] = mapped_column(Integer, nullable=False)
    filter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ergebnis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pdf_pfad: Mapped[str | None] = mapped_column(String(500))
