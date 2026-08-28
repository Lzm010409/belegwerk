"""Der Pool — das einzige mandantenübergreifende Feature der Plattform.

Regeln aus dem Atlas-Briefing Abschnitt 5, hier eins zu eins abgebildet:

* Standard ist Alleinbesitz. Der Pool ist eine bewusste Einzelentscheidung je
  Erhebung (``im_pool``), voreingestellt auf aus.
* Wer Daten in den Pool gibt, sieht Pooldaten anderer. Wer nichts gibt, sieht
  nur eigene. Gegenseitigkeit ist die Mechanik, die die Sammlung überhaupt in
  Gang bringt.
* Im Pool sichtbar: Betrieb, Anschrift, Sätze, Erhebungsdatum, Nachweisart.
* **Nicht sichtbar: welches Büro erfasst hat, die Nachweisdokumente, der
  Fallbezug.** Nachweise bleiben immer beim Erfasser.

Technische Umsetzung der letzten Regel: dieses Modul gibt **niemals** ein
ORM-Objekt heraus, sondern ausschließlich ``PoolErhebung`` — ein Datensatz, der
kein Feld für die Mandantenkennung besitzt. Es gibt damit keinen Pfad, über den
sie hinausgelangen könnte, auch nicht durch ein späteres Versehen in einer
Vorlage.

Weil der Pool über Mandantengrenzen liest, arbeitet er unter der
Eigentümerrolle und steht deshalb auf der Ausnahmeliste in
``tests/test_architektur.py``.

**Vor dem Livegang:** Das Poolmodell ist wettbewerbsrechtlich zu prüfen
(Briefing Abschnitt 5, Querschnitt 6.7). Erhoben werden Preise Dritter
(Werkstätten), nicht die Honorare der teilnehmenden Sachverständigen — das ist
der entscheidende Unterschied zu einem Preisaustausch unter Wettbewerbern. Bis
zur anwaltlichen Freigabe bleibt ``POOL_FREIGEGEBEN`` auf ``False``; dann ist
Atlas ein reines Einzelplatz-Register, und das ist ohnehin verkaufbar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from belegwerk.atlas.modelle import Betrieb, Betriebsart, Erhebung, Erhebungsart
from belegwerk.datenbank import sitzungsfabrik

# Schalter für Querschnitt 6.7: bis zur anwaltlichen Prüfung ist der Pool aus.
POOL_FREIGEGEBEN = False


@dataclass(frozen=True, slots=True)
class PoolErhebung:
    """Ein Pooldatensatz. Ohne Feld für den Erfasser — mit Absicht."""

    betrieb_name: str
    strasse: str | None
    plz: str
    ort: str
    lat: float | None
    lon: float | None
    betriebsart: Betriebsart
    marken: tuple[str, ...]
    erhebungsdatum: date
    erhebungsart: Erhebungsart
    satz_mechanik: Decimal | None
    satz_karosserie: Decimal | None
    satz_elektrik: Decimal | None
    satz_lack_lohn: Decimal | None
    lack_material_prozent: Decimal | None
    upe_aufschlag_prozent: Decimal | None
    verbringung_pauschale: Decimal | None
    entsorgung: Decimal | None
    eigen: bool

    def wert(self, feld: str) -> Decimal | None:
        return getattr(self, feld, None)


def _als_pool(erhebung: Erhebung, betrieb: Betrieb, eigen: bool) -> PoolErhebung:
    return PoolErhebung(
        betrieb_name=betrieb.name,
        strasse=betrieb.strasse,
        plz=betrieb.plz,
        ort=betrieb.ort,
        lat=betrieb.lat,
        lon=betrieb.lon,
        betriebsart=betrieb.art,
        marken=tuple(betrieb.marken or ()),
        erhebungsdatum=erhebung.erhebungsdatum,
        erhebungsart=erhebung.art,
        satz_mechanik=erhebung.satz_mechanik,
        satz_karosserie=erhebung.satz_karosserie,
        satz_elektrik=erhebung.satz_elektrik,
        satz_lack_lohn=erhebung.satz_lack_lohn,
        lack_material_prozent=erhebung.lack_material_prozent,
        upe_aufschlag_prozent=erhebung.upe_aufschlag_prozent,
        verbringung_pauschale=erhebung.verbringung_pauschale,
        entsorgung=erhebung.entsorgung,
        eigen=eigen,
    )


async def beitragszaehler(mandant_id: uuid.UUID) -> int:
    """Wie viele eigene Erhebungen stehen im Pool? (Todo 5.4)"""
    async with sitzungsfabrik()() as sitzung:
        anzahl = (
            await sitzung.execute(
                select(func.count())
                .select_from(Erhebung)
                .where(Erhebung.mandant_id == mandant_id, Erhebung.im_pool.is_(True))
            )
        ).scalar_one()
        return int(anzahl)


async def ist_teilnehmer(mandant_id: uuid.UUID) -> bool:
    """Wer nichts gibt, sieht nur eigene Daten."""
    if not POOL_FREIGEGEBEN:
        return False
    return await beitragszaehler(mandant_id) > 0


async def pooldaten(mandant_id: uuid.UUID, plz_menge: set[str]) -> list[PoolErhebung]:
    """Erhebungen **anderer** Büros im Pool, anonymisiert.

    Gibt eine leere Liste zurück, solange der Pool nicht freigegeben ist oder
    das Büro selbst nichts beiträgt.
    """
    if not plz_menge or not await ist_teilnehmer(mandant_id):
        return []
    async with sitzungsfabrik()() as sitzung:
        zeilen = (
            await sitzung.execute(
                select(Erhebung, Betrieb)
                .join(Betrieb, Erhebung.betrieb_id == Betrieb.id)
                .where(
                    Erhebung.im_pool.is_(True),
                    Erhebung.mandant_id != mandant_id,
                    Betrieb.plz.in_(plz_menge),
                )
            )
        ).all()
        return [_als_pool(erhebung, betrieb, eigen=False) for erhebung, betrieb in zeilen]


async def kennzahlen_oeffentlich() -> dict[str, Any]:
    """Zahlen für die Landingpage — live aus der Datenbank, nicht geschönt.

    Aggregate über alle Mandanten, ohne jeden Bezug zu einzelnen Büros: nur
    Anzahlen und ein Datum. Genau diese Zahlen macht die Landingpage öffentlich,
    und sie werden automatisch besser, je besser das Produkt wird.
    """
    async with sitzungsfabrik()() as sitzung:
        betriebe = (await sitzung.execute(select(func.count()).select_from(Betrieb))).scalar_one()
        erhebungen = (
            await sitzung.execute(select(func.count()).select_from(Erhebung))
        ).scalar_one()
        belegt = (
            await sitzung.execute(
                select(func.count())
                .select_from(Erhebung)
                .where(Erhebung.art == Erhebungsart.PREISAUSHANG)
            )
        ).scalar_one()
        zuletzt = (await sitzung.execute(select(func.max(Erhebung.angelegt_am)))).scalar_one()
        punkte = (
            await sitzung.execute(
                select(Betrieb.lat, Betrieb.lon)
                .where(Betrieb.lat.is_not(None), Betrieb.lon.is_not(None))
                .limit(4000)
            )
        ).all()
    return {
        "betriebe": int(betriebe),
        "erhebungen": int(erhebungen),
        "mit_preisaushang": int(belegt),
        "zuletzt_ergaenzt": zuletzt,
        "punkte": [(round(lat, 3), round(lon, 3)) for lat, lon in punkte],
    }
