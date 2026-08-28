"""Modul Atlas: Umkreis, Statistik, Nachweispflicht, Pool."""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from belegwerk.atlas import dienst, geo, pool
from belegwerk.atlas.diagramm import verteilung_svg
from belegwerk.atlas.modelle import Betrieb, Betriebsart, Erhebung, Erhebungsart
from belegwerk.atlas.statistik import MINDESTANZAHL, kennzahlen_bilden, perzentil
from belegwerk.kern.mandantentrennung import mandanten_sitzung
from belegwerk.kern.modelle import Mandant

pytestmark = pytest.mark.anyio

HEUTE = date(2026, 8, 28)


# --- Geo -------------------------------------------------------------------


def test_plz_tabelle_deckt_deutschland_ab() -> None:
    punkte = geo.mittelpunkte()
    assert len(punkte) > 7000
    for plz in ("26123", "10115", "80331", "20095", "01067"):
        assert geo.bekannt(plz), plz


@pytest.mark.parametrize(
    ("a", "b", "referenz_km"),
    [
        # Referenzentfernungen zwischen Stadtmittelpunkten (Luftlinie).
        ((53.1435, 8.2146), (53.0793, 8.8017), 40.0),   # Oldenburg – Bremen
        ((52.5200, 13.4050), (48.1372, 11.5755), 504.0),  # Berlin – München
        ((50.1109, 8.6821), (50.9375, 6.9603), 152.0),   # Frankfurt – Köln
        ((53.5511, 9.9937), (53.5511, 9.9937), 0.0),     # identischer Punkt
    ],
)
def test_haversine_bleibt_unter_zwei_kilometern_abweichung(
    a: tuple[float, float], b: tuple[float, float], referenz_km: float
) -> None:
    """Todo 3.1: bekannte Entfernungen unter 2 km Abweichung."""
    gemessen = geo.entfernung_km(a[0], a[1], b[0], b[1])
    assert abs(gemessen - referenz_km) < 2.0, f"{gemessen:.1f} statt {referenz_km}"


def test_umkreis_liefert_nur_postleitzahlen_im_radius() -> None:
    umkreis = geo.plz_im_umkreis("26123", 30)
    assert "26123" in umkreis
    assert umkreis["26123"] == 0.0
    for plz, strecke in umkreis.items():
        assert strecke <= 30.0
    assert "80331" not in umkreis  # München


def test_unbekannte_plz_nennt_den_naechsten_schritt() -> None:
    with pytest.raises(geo.PlzUnbekannt) as fehler:
        geo.punkt("00000")
    assert "benachbarte Postleitzahl" in str(fehler.value)


# --- Statistik -------------------------------------------------------------


def test_perzentile_werden_linear_interpoliert() -> None:
    werte = [Decimal(x) for x in ("100", "110", "120", "130", "140")]
    assert perzentil(werte, Decimal("0.5")) == Decimal("120.00")
    assert perzentil(werte, Decimal("0.25")) == Decimal("110.00")
    assert perzentil(werte, Decimal("0.75")) == Decimal("130.00")


def test_unter_fuenf_betrieben_kein_median() -> None:
    """Todo 3.3: ein Test mit vier Betrieben liefert keinen Median."""
    werte = [Decimal(x) for x in ("100", "110", "120", "130")]
    kennzahl = kennzahlen_bilden("satz_mechanik", "Mechanik", werte, 0)
    assert kennzahl.anzahl == 4
    assert kennzahl.median is None
    assert kennzahl.p25 is None and kennzahl.p75 is None
    assert not kennzahl.belastbar
    assert "mindestens 5" in (kennzahl.hinweis or "")


def test_ab_fuenf_betrieben_gibt_es_einen_median() -> None:
    werte = [Decimal(x) for x in ("100", "110", "120", "130", "140")]
    kennzahl = kennzahlen_bilden("satz_mechanik", "Mechanik", werte, 0)
    assert kennzahl.belastbar
    assert kennzahl.median == Decimal("120.00")
    assert kennzahl.hinweis is None


def test_kennzahlen_bleiben_decimal() -> None:
    kennzahl = kennzahlen_bilden(
        "satz_mechanik", "Mechanik", [Decimal(x) for x in ("100.5", "110", "120", "130", "141.25")], 0
    )
    for wert in (kennzahl.median, kennzahl.p25, kennzahl.p75, kennzahl.minimum, kennzahl.maximum):
        assert isinstance(wert, Decimal)


def test_diagramm_ist_gueltiges_svg_ohne_javascript() -> None:
    kennzahl = kennzahlen_bilden(
        "satz_mechanik", "Mechanik", [Decimal(x) for x in ("100", "110", "120", "130", "140")], 0
    )
    svg = verteilung_svg(kennzahl)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "script" not in svg.lower()
    assert "Median" in svg


def test_diagramm_ohne_werte_sagt_das() -> None:
    kennzahl = kennzahlen_bilden("satz_mechanik", "Mechanik", [], 0)
    assert "Keine Werte" in verteilung_svg(kennzahl)


# --- EXIF ------------------------------------------------------------------


def _jpeg_mit_gps() -> bytes:
    from PIL import Image

    bild = Image.new("RGB", (24, 24), (200, 30, 40))
    puffer = io.BytesIO()
    exif = bild.getexif()
    exif[0x8825] = {1: "N", 2: (53.0, 8.0, 0.0)}  # GPSInfo
    exif[0x010F] = "Testkamera"
    bild.save(puffer, format="JPEG", exif=exif)
    return puffer.getvalue()


def test_exif_wird_aus_bildern_entfernt() -> None:
    """Todo 1.4: hochgeladene Fotos enthalten keine GPS-Daten mehr."""
    from PIL import Image

    original = _jpeg_mit_gps()
    assert Image.open(io.BytesIO(original)).getexif()

    bereinigt, entfernt = dienst.exif_entfernen(original)
    assert entfernt is True
    assert not dict(Image.open(io.BytesIO(bereinigt)).getexif())


def test_pdf_bleibt_unveraendert() -> None:
    inhalt = b"%PDF-1.7\ntrailer\n%%EOF"
    bereinigt, entfernt = dienst.exif_entfernen(inhalt)
    assert bereinigt == inhalt
    assert entfernt is False


# --- Erfassung -------------------------------------------------------------


_BENUTZER: dict[uuid.UUID, uuid.UUID] = {}


async def _mandant(sitzung: AsyncSession, name: str) -> uuid.UUID:
    """Mandant samt Inhaber — die Erhebung verweist auf einen echten Benutzer."""
    from belegwerk.kern.modelle import Benutzer, Rolle

    mandant = Mandant(name=name)
    sitzung.add(mandant)
    await sitzung.flush()
    benutzer = Benutzer(
        mandant_id=mandant.id,
        email=f"{uuid.uuid4().hex[:10]}@example.de",
        name=f"{name} Inhaber",
        passwort_hash="x" * 40,
        rolle=Rolle.INHABER,
    )
    sitzung.add(benutzer)
    await sitzung.commit()
    _BENUTZER[mandant.id] = benutzer.id
    return mandant.id


def _benutzer(mandant_id: uuid.UUID) -> uuid.UUID:
    return _BENUTZER[mandant_id]


def _erfassung(**rest: Any) -> dienst.Erfassung:
    grund: dict[str, Any] = {
        "betrieb_id": None,
        "name": "Autohaus Nordwest",
        "strasse": "Industriestraße 4",
        "plz": "26123",
        "ort": "Oldenburg",
        "betriebsart": Betriebsart.MARKENGEBUNDEN,
        "marken": ["VW"],
        "erhebungsdatum": date(2026, 6, 1),
        "erhebungsart": Erhebungsart.TELEFONISCH,
        "saetze": {"satz_mechanik": Decimal("142.00"), "satz_karosserie": Decimal("156.00")},
        "bemerkung": "Auskunft Herr Meyer, 01.06.2026, 10:15 Uhr",
        "im_pool": False,
    }
    grund.update(rest)
    return dienst.Erfassung(**grund)


async def test_erhebung_ohne_nachweis_bei_belastbarer_art_wird_abgelehnt(
    sitzung: AsyncSession,
) -> None:
    """Ein Wert ohne Nachweis wird nicht gespeichert (Briefing Abschnitt 2)."""
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(dienst.ErhebungUnvollstaendig) as fehler:
            await dienst.erhebung_anlegen(
                db,
                mandant_id,
                _benutzer(mandant_id),
                _erfassung(erhebungsart=Erhebungsart.PREISAUSHANG),
                None,
            )
    assert "Beleg" in str(fehler.value)


async def test_telefonische_auskunft_geht_ohne_dokument(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        erhebung = await dienst.erhebung_anlegen(db, mandant_id, _benutzer(mandant_id), _erfassung(), None)
        assert erhebung.art.belastbarkeit == "mittel"
        assert erhebung.im_pool is False


async def test_erhebung_ohne_jeden_satz_wird_abgelehnt(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(dienst.ErhebungUnvollstaendig, match="keinen Inhalt"):
            await dienst.erhebung_anlegen(
                db, mandant_id, _benutzer(mandant_id), _erfassung(saetze={"satz_mechanik": None}), None
            )


async def test_erhebungsdatum_in_der_zukunft_wird_abgelehnt(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        with pytest.raises(dienst.ErhebungUnvollstaendig, match="Zukunft"):
            await dienst.erhebung_anlegen(
                db,
                mandant_id,
                _benutzer(mandant_id),
                _erfassung(erhebungsdatum=date.today() + timedelta(days=1)),
                None,
            )


async def test_betrieb_bekommt_die_koordinate_seiner_plz(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        erhebung = await dienst.erhebung_anlegen(db, mandant_id, _benutzer(mandant_id), _erfassung(), None)
        betrieb = (
            await db.execute(select(Betrieb).where(Betrieb.id == erhebung.betrieb_id))
        ).scalar_one()
        assert betrieb.lat is not None and betrieb.lon is not None


async def test_dublettenwarnung_bei_aehnlichem_namen(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(mandant_id) as db:
        await dienst.erhebung_anlegen(db, mandant_id, _benutzer(mandant_id), _erfassung(), None)
        treffer = await dienst.duplikate(db, "Autohaus Nordwest GmbH", "26123")
        assert treffer
        assert not await dienst.duplikate(db, "Karosseriebau Süd", "26123")


# --- Auswertung ------------------------------------------------------------


async def _bestand(sitzung: AsyncSession, mandant_id: uuid.UUID, anzahl: int, **rest: Any) -> None:
    async with mandanten_sitzung(mandant_id) as db:
        for nummer in range(anzahl):
            await dienst.erhebung_anlegen(
                db,
                mandant_id,
                _benutzer(mandant_id),
                _erfassung(
                    name=f"Betrieb {nummer}",
                    saetze={
                        "satz_mechanik": Decimal(110 + nummer * 5),
                        "satz_karosserie": Decimal(120 + nummer * 5),
                    },
                    **rest,
                ),
                None,
            )


async def test_auswertung_unter_fuenf_betrieben_ohne_median(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, mandant_id, 4)
    async with mandanten_sitzung(mandant_id) as db:
        bericht = await dienst.auswerten(db, mandant_id, dienst.Filter("26123", 30), HEUTE)
    kennzahl = bericht.ergebnis.nach_feld("satz_mechanik")
    assert kennzahl is not None
    assert kennzahl.anzahl == 4
    assert kennzahl.median is None


async def test_auswertung_ab_fuenf_betrieben_mit_median(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, mandant_id, 6)
    async with mandanten_sitzung(mandant_id) as db:
        bericht = await dienst.auswerten(db, mandant_id, dienst.Filter("26123", 30), HEUTE)
    kennzahl = bericht.ergebnis.nach_feld("satz_mechanik")
    assert kennzahl is not None and kennzahl.belastbar
    assert kennzahl.median == Decimal("122.50")
    assert bericht.ergebnis.anzahl_betriebe == 6


async def test_veraltete_erhebungen_zaehlen_nicht_in_den_median(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, mandant_id, 5)
    await _bestand(sitzung, mandant_id, 3, erhebungsdatum=date(2023, 1, 10))
    async with mandanten_sitzung(mandant_id) as db:
        bericht = await dienst.auswerten(db, mandant_id, dienst.Filter("26123", 30), HEUTE)
    kennzahl = bericht.ergebnis.nach_feld("satz_mechanik")
    assert kennzahl is not None
    assert kennzahl.anzahl == 5
    assert kennzahl.anzahl_veraltet == 3
    assert bericht.ergebnis.anzahl_veraltet == 3
    assert any("älter als 24 Monate" in h for h in bericht.ergebnis.hinweise)


async def test_filter_auf_belastbarkeit(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, mandant_id, 5)  # telefonisch = mittel
    async with mandanten_sitzung(mandant_id) as db:
        streng = await dienst.auswerten(
            db, mandant_id, dienst.Filter("26123", 30, mindestbelastbarkeit="hoch"), HEUTE
        )
    assert streng.ergebnis.anzahl_erhebungen == 0


async def test_csv_export_enthaelt_nachweisart(sitzung: AsyncSession) -> None:
    mandant_id = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, mandant_id, 5)
    async with mandanten_sitzung(mandant_id) as db:
        bericht = await dienst.auswerten(db, mandant_id, dienst.Filter("26123", 30), HEUTE)
    inhalt = dienst.als_csv(bericht)
    assert "Nachweisart" in inhalt and "Belastbarkeit" in inhalt
    assert "telefonische Auskunft" in inhalt
    assert inhalt.count("\r\n") >= 6


# --- Pool ------------------------------------------------------------------


async def test_ohne_pool_sieht_niemand_fremde_erhebungen(sitzung: AsyncSession) -> None:
    nord = await _mandant(sitzung, "Büro Nord")
    sued = await _mandant(sitzung, "Büro Süd")
    await _bestand(sitzung, nord, 5)

    async with mandanten_sitzung(sued) as db:
        bericht = await dienst.auswerten(db, sued, dienst.Filter("26123", 30), HEUTE)
    assert bericht.ergebnis.anzahl_erhebungen == 0
    assert bericht.zeilen == []


async def test_abgeschalteter_pool_liefert_nichts(
    sitzung: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Betreiber kann den Pool abschalten; dann ist Atlas Einzelplatz."""
    monkeypatch.setattr(pool, "pool_freigegeben", lambda: False)
    nord = await _mandant(sitzung, "Büro Nord")
    async with mandanten_sitzung(nord) as db:
        await dienst.erhebung_anlegen(db, nord, _benutzer(nord), _erfassung(im_pool=True), None)
    assert await pool.ist_teilnehmer(nord) is False
    assert await pool.pooldaten(nord, {"26123"}) == []


async def test_pool_ist_voreingestellt_freigegeben() -> None:
    """Das SVS-Register ist das einzige geteilte Feature der Plattform."""
    assert pool.pool_freigegeben() is True


async def test_pooldatensatz_kennt_die_mandanten_id_nicht(
    sitzung: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Todo 5.3: kein API-Pfad liefert die Erfasser-Mandanten-ID an einen anderen."""
    monkeypatch.setattr(pool, "pool_freigegeben", lambda: True)
    nord = await _mandant(sitzung, "Büro Nord")
    sued = await _mandant(sitzung, "Büro Süd")

    async with mandanten_sitzung(nord) as db:
        erhebung = await dienst.erhebung_anlegen(
            db, nord, _benutzer(nord), _erfassung(im_pool=True), None
        )
        assert erhebung.im_pool is True
    async with mandanten_sitzung(sued) as db:
        await dienst.erhebung_anlegen(db, sued, _benutzer(sued), _erfassung(im_pool=True), None)

    daten = await pool.pooldaten(sued, {"26123"})
    assert daten, "Poolteilnehmer sieht Pooldaten anderer"
    for eintrag in daten:
        felder = set(type(eintrag).__slots__)
        assert "mandant_id" not in felder
        assert not any("mandant" in feld for feld in felder)
        assert eintrag.eigen is False


async def test_wer_nichts_gibt_sieht_nur_eigene_daten(
    sitzung: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool, "pool_freigegeben", lambda: True)
    nord = await _mandant(sitzung, "Büro Nord")
    sued = await _mandant(sitzung, "Büro Süd")
    async with mandanten_sitzung(nord) as db:
        await dienst.erhebung_anlegen(db, nord, _benutzer(nord), _erfassung(im_pool=True), None)

    assert await pool.ist_teilnehmer(sued) is False
    assert await pool.pooldaten(sued, {"26123"}) == []

    async with mandanten_sitzung(sued) as db:
        await dienst.erhebung_anlegen(db, sued, _benutzer(sued), _erfassung(im_pool=True), None)
    assert await pool.ist_teilnehmer(sued) is True
    assert len(await pool.pooldaten(sued, {"26123"})) == 1


async def test_nachweise_bleiben_immer_beim_erfasser(
    sitzung: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool, "pool_freigegeben", lambda: True)
    nord = await _mandant(sitzung, "Büro Nord")
    sued = await _mandant(sitzung, "Büro Süd")
    async with mandanten_sitzung(nord) as db:
        await dienst.erhebung_anlegen(
            db,
            nord,
            _benutzer(nord),
            _erfassung(erhebungsart=Erhebungsart.PREISAUSHANG, im_pool=True),
            ("aushang.jpg", _jpeg_mit_gps()),
        )
    async with mandanten_sitzung(sued) as db:
        await dienst.erhebung_anlegen(db, sued, _benutzer(sued), _erfassung(im_pool=True), None)

    daten = await pool.pooldaten(sued, {"26123"})
    assert daten
    for eintrag in daten:
        assert not hasattr(eintrag, "nachweise")
        assert "nachweis" not in " ".join(type(eintrag).__slots__)

    # Und über die Mandantensitzung ist der fremde Nachweis ohnehin unsichtbar.
    from belegwerk.atlas.modelle import Nachweis

    async with mandanten_sitzung(sued) as db:
        assert (await db.execute(select(Nachweis))).scalars().all() == []


async def test_beitragszaehler_zaehlt_nur_eigene(sitzung: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "pool_freigegeben", lambda: True)
    nord = await _mandant(sitzung, "Büro Nord")
    sued = await _mandant(sitzung, "Büro Süd")
    async with mandanten_sitzung(nord) as db:
        await dienst.erhebung_anlegen(db, nord, _benutzer(nord), _erfassung(im_pool=True), None)
        await dienst.erhebung_anlegen(db, nord, _benutzer(nord), _erfassung(name="Zweiter", im_pool=True), None)
    assert await pool.beitragszaehler(nord) == 2
    assert await pool.beitragszaehler(sued) == 0


async def test_oeffentliche_kennzahlen_kommen_aus_der_datenbank(sitzung: AsyncSession) -> None:
    """Landingpage-Zahlen sind live, nicht aus einer Textdatei."""
    nord = await _mandant(sitzung, "Büro Nord")
    await _bestand(sitzung, nord, 3)
    kennzahlen = await pool.kennzahlen_oeffentlich()
    assert kennzahlen["betriebe"] == 3
    assert kennzahlen["erhebungen"] == 3
    assert kennzahlen["mit_preisaushang"] == 0
    assert len(kennzahlen["punkte"]) == 3


# --- Oberflaeche -----------------------------------------------------------

PASSWORT = "Kotfluegel-vorn-links-2026"


def _anmelden(klient: Any, email: str = "nord@example.de") -> None:
    klient.get("/anmelden")
    klient.post(
        "/anmelden",
        data={
            "email": email,
            "passwort": PASSWORT,
            "csrf_token": klient.cookies.get("belegwerk_csrf"),
            "weiter": "",
        },
        follow_redirects=False,
    )


@pytest.fixture()
def angemeldet_atlas(klient: Any, migrierte_datenbank: str) -> Any:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    _anmelden(klient)
    return klient


def _erfassen(klient: Any, **rest: Any) -> Any:
    daten: dict[str, Any] = {
        "csrf_token": klient.cookies.get("belegwerk_csrf"),
        "name": "Autohaus Nordwest",
        "plz": "26123",
        "ort": "Oldenburg",
        "strasse": "Industriestraße 4",
        "betriebsart": "markengebunden",
        "marken": "VW",
        "erhebungsdatum": "2026-06-01",
        "erhebungsart": "telefonisch",
        "satz_mechanik": "142,00",
        "satz_karosserie": "156,00",
        "bemerkung": "Herr Meyer, 01.06.2026, 10:15 Uhr",
    }
    daten.update(rest)
    return klient.post("/app/atlas", data=daten, follow_redirects=True)


def test_erfassungsformular_nennt_die_belastbarkeit(angemeldet_atlas: Any) -> None:
    antwort = angemeldet_atlas.get("/app/atlas")
    assert antwort.status_code == 200
    assert "Belastbarkeit hoch" in antwort.text
    assert "Standortdaten werden beim Hochladen aus dem Bild entfernt" in antwort.text
    assert "In den Pool geben" in antwort.text


def test_erfassung_und_liste(angemeldet_atlas: Any) -> None:
    antwort = _erfassen(angemeldet_atlas)
    assert "Erhebung ist gespeichert" in antwort.text
    assert "Autohaus Nordwest" in antwort.text
    assert "telefonische Auskunft" in antwort.text


def test_preisaushang_ohne_beleg_wird_abgelehnt(angemeldet_atlas: Any) -> None:
    antwort = _erfassen(angemeldet_atlas, erhebungsart="preisaushang")
    assert "Beleg" in antwort.text
    assert "Erhebung ist gespeichert" not in antwort.text


def test_auswertung_mit_zu_wenigen_betrieben(angemeldet_atlas: Any) -> None:
    for nummer in range(3):
        _erfassen(angemeldet_atlas, name=f"Betrieb {nummer}", satz_mechanik=f"{110 + nummer},00")
    antwort = angemeldet_atlas.get("/app/atlas/auswertung?plz=26123&radius=30")
    assert antwort.status_code == 200
    assert "Datenbasis" in antwort.text or "mindestens 5" in antwort.text
    assert "Median</span>" not in antwort.text


def test_auswertung_mit_median_und_diagramm(angemeldet_atlas: Any) -> None:
    for nummer in range(6):
        _erfassen(angemeldet_atlas, name=f"Betrieb {nummer}", satz_mechanik=f"{110 + nummer * 5},00")
    antwort = angemeldet_atlas.get("/app/atlas/auswertung?plz=26123&radius=30")
    assert "Median" in antwort.text
    assert "<svg" in antwort.text
    assert "Auswertung als PDF-Anlage" in antwort.text


def test_pdf_auswertung_enthaelt_methodik(angemeldet_atlas: Any) -> None:
    for nummer in range(6):
        _erfassen(angemeldet_atlas, name=f"Betrieb {nummer}", satz_mechanik=f"{110 + nummer * 5},00")
    antwort = angemeldet_atlas.get("/app/atlas/auswertung.pdf?plz=26123&radius=30")
    assert antwort.status_code == 200
    assert antwort.content.startswith(b"%PDF-")
    assert len(antwort.content) > 4000


def test_csv_export(angemeldet_atlas: Any) -> None:
    _erfassen(angemeldet_atlas)
    antwort = angemeldet_atlas.get("/app/atlas/auswertung.csv?plz=26123&radius=30")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("text/csv")
    assert "Autohaus Nordwest" in antwort.content.decode("utf-8-sig")


def test_unbekannte_plz_meldet_klartext(angemeldet_atlas: Any) -> None:
    antwort = angemeldet_atlas.get("/app/atlas/auswertung?plz=00000&radius=30")
    assert "benachbarte Postleitzahl" in antwort.text


def test_poolschalter_steht_in_der_erhebungsliste(angemeldet_atlas: Any) -> None:
    """Teilnahme bleibt eine Einzelentscheidung je Erhebung."""
    formular = angemeldet_atlas.get("/app/atlas")
    assert "In den Pool geben" in formular.text
    assert "Voreinstellung aus" in formular.text

    _erfassen(angemeldet_atlas)
    liste = angemeldet_atlas.get("/app/atlas/erhebungen")
    assert "in den Pool geben" in liste.text


def test_erhebungen_bleiben_beim_eigenen_buero(klient: Any, migrierte_datenbank: str) -> None:
    from tests.conftest import buero_anlegen

    buero_anlegen(migrierte_datenbank, "Büro Nord", "nord@example.de", PASSWORT)
    buero_anlegen(migrierte_datenbank, "Büro Süd", "sued@example.de", PASSWORT)
    _anmelden(klient)
    _erfassen(klient, name="Nur fuer Nord")
    assert "Nur fuer Nord" in klient.get("/app/atlas/erhebungen").text

    klient.cookies.clear()
    _anmelden(klient, "sued@example.de")
    sued = klient.get("/app/atlas/erhebungen")
    assert "Nur fuer Nord" not in sued.text
    assert "Noch keine Erhebung" in sued.text
    auswertung = klient.get("/app/atlas/auswertung?plz=26123&radius=30")
    assert "Nur fuer Nord" not in auswertung.text
