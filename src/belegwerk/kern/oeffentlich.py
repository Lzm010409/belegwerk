"""Öffentliche Seiten: Landingpages, Rechtstexte, Zugangsanfragen.

Die Seiten stehen ohne Anmeldung offen und arbeiten deshalb ohne
Mandantenkontext. Die einzigen Schreibvorgänge sind Zugangsanfragen; sie sind
mit Honeypot und Rate-Limit versehen (Querschnitt 8.3), aber ohne Captcha —
die Zielgruppe ist klein und ein Captcha kostet mehr Anmeldungen, als es Bots
abhält.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from belegwerk.datenbank import sitzungsfabrik
from belegwerk.kern import mail, ratenbegrenzung
from belegwerk.kern.abhaengigkeiten import CsrfAbh, OptionalerBenutzerAbh
from belegwerk.kern.abrechnung import LISTENPREIS
from belegwerk.kern.modelle import Zugangsanfrage
from belegwerk.konfiguration import einstellungen
from belegwerk.web.kontext import antworten

_log = logging.getLogger(__name__)
router = APIRouter(tags=["oeffentlich"])

ZWISCHENSPEICHER = "public, max-age=600"
STAND = "28.08.2026"


def _oeffentlich(
    request: Request, vorlage: str, kontext: dict[str, Any], benutzer: Any = None
) -> Response:
    antwort = antworten(request, vorlage, kontext, benutzer=benutzer)
    antwort.headers.setdefault("Cache-Control", ZWISCHENSPEICHER)
    return antwort


# ---------------------------------------------------------------------------
# Startseite und Produktseiten
# ---------------------------------------------------------------------------


@router.get("/", include_in_schema=False)
async def start(request: Request, benutzer: OptionalerBenutzerAbh) -> Response:
    from belegwerk.kern.modelle import Modul

    module = [
        (
            "/delta",
            "Delta",
            LISTENPREIS[Modul.DELTA],
            "Legt Ihre Kalkulation neben den Prüfbericht des Versicherers und zeigt "
            "Position für Position, was gestrichen wurde und was es kostet.",
            "Statt 20 bis 45 Minuten: unter einer Minute.",
        ),
        (
            "/atlas",
            "Atlas",
            LISTENPREIS[Modul.ATLAS],
            "Regionale Stundenverrechnungssätze, UPE-Aufschläge und Verbringungskosten "
            "mit Erhebungsnachweis — als belegbare Anlage.",
            "Erfassung am Werkstatttresen in unter 60 Sekunden.",
        ),
        (
            "/check",
            "Check",
            LISTENPREIS[Modul.CHECK],
            "Prüft das fertige Gutachten-PDF gegen 20 Regeln und meldet Widersprüche, "
            "bevor es beim Versicherer liegt.",
            "Fünfzehn Sekunden je Gutachten.",
        ),
    ]
    return _oeffentlich(request, "landing/start.html", {"module": module}, benutzer)


@router.get("/delta", include_in_schema=False)
async def delta_seite(request: Request, benutzer: OptionalerBenutzerAbh) -> Response:
    from belegwerk.delta.klassifikation import Klasse
    from belegwerk.kern.modelle import Modul

    return _oeffentlich(
        request,
        "landing/delta.html",
        {
            "klassen": list(Klasse),
            "preis": LISTENPREIS[Modul.DELTA],
            "beispiel": _beispiel_delta(),
        },
        benutzer,
    )


def _beispiel_delta() -> dict[str, Any]:
    """Ein anonymisierter Fall für den Hero — echte Struktur, erfundene Namen."""
    from belegwerk.delta.klassifikation import Klasse

    zeilen = [
        (1, "Motorhaube", Klasse.UPE_GEKUERZT, "18,0 %", "0,0 %", Decimal("160.56")),
        (2, "Kotflügel vorn links", Klasse.UPE_GEKUERZT, "18,0 %", "0,0 %", Decimal("57.33")),
        (3, "Scheinwerfer links", Klasse.POS_ENTFALLEN, "612,80", "0,00", Decimal("612.80")),
        (4, "Stoßfänger vorn", Klasse.TEIL_ERSETZT, "5H0807221", "IDENT-4471", Decimal("214.90")),
        (11, "Motorhaube ersetzen", Klasse.AW_REDUZIERT, "8,5", "5,1", Decimal("53.04")),
        (12, "Kotflügel ersetzen", Klasse.SATZ_GESENKT, "156,00", "132,60", Decimal("42.12")),
        (21, "Motorhaube lackieren", Klasse.LACKSTUFE_GESENKT, "3", "2", Decimal("118.42")),
        (22, "Beilackierung Seitenwand", Klasse.LACKMATERIAL_GEKUERZT, "38,0 %", "30,0 %", Decimal("47.65")),
        (31, "Verbringungskosten", Klasse.VERBRINGUNG_ENTFALLEN, "120,00", "0,00", Decimal("120.00")),
    ]
    return {
        "zeilen": [
            {
                "nr": nr,
                "bezeichnung": bezeichnung,
                "klasse": klasse,
                "eigen": eigen,
                "pruefbericht": pruef,
                "differenz": differenz,
            }
            for nr, bezeichnung, klasse, eigen, pruef, differenz in zeilen
        ],
        "summe": sum((z[5] for z in zeilen), Decimal("0.00")),
    }


@router.get("/atlas", include_in_schema=False)
async def atlas_seite(request: Request, benutzer: OptionalerBenutzerAbh) -> Response:
    from belegwerk.atlas.pool import kennzahlen_oeffentlich
    from belegwerk.kern.modelle import Modul

    kennzahlen = await kennzahlen_oeffentlich()
    antwort = antworten(
        request,
        "landing/atlas.html",
        {"kennzahlen": kennzahlen, "preis": LISTENPREIS[Modul.ATLAS]},
        benutzer=benutzer,
    )
    # Diese Zahlen sind der Kern der Seite und dürfen nicht altern.
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


@router.get("/check", include_in_schema=False)
async def check_seite(request: Request, benutzer: OptionalerBenutzerAbh) -> Response:
    from belegwerk.check.regelmaschine import startkatalog
    from belegwerk.kern.modelle import Modul

    return _oeffentlich(
        request,
        "landing/check.html",
        {
            "regeln": startkatalog(),
            "preis": LISTENPREIS[Modul.CHECK],
            "offen": einstellungen().oeffentliche_pruefung_aktiv,
        },
        benutzer,
    )


@router.post("/check/probe", include_in_schema=False)
async def offene_pruefung(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: OptionalerBenutzerAbh,
    datei: Annotated[UploadFile, File()],
) -> Response:
    """Die funktionierende Dropzone im Hero (Check-Briefing Abschnitt 7).

    Die Datei wird **nicht gespeichert**. Sie liegt für die Dauer der Anfrage im
    Arbeitsspeicher, das Protokoll entsteht daraus, und danach ist sie weg. Das
    ist strenger als die im Briefing genannte Löschung nach einer Stunde und
    deshalb auch leichter zu behaupten: es gibt nichts zu löschen.
    """
    from belegwerk.check import dienst
    from belegwerk.check.regelmaschine import startkatalog
    from belegwerk.kern.dateipruefung import DateiAbgelehnt
    from belegwerk.kern.modelle import Modul

    if not einstellungen().oeffentliche_pruefung_aktiv:
        return _oeffentlich(
            request,
            "landing/check.html",
            {
                "regeln": startkatalog(),
                "preis": LISTENPREIS[Modul.CHECK],
                "offen": False,
                "fehler": "Die offene Prüfung ist zurzeit abgeschaltet.",
            },
            benutzer,
        )

    kennung = request.client.host if request.client else "unbekannt"
    try:
        ratenbegrenzung.pruefen_und_zaehlen(
            "offene_pruefung", kennung, ratenbegrenzung.OEFFENTLICHE_PRUEFUNG
        )
        inhalt = await datei.read()
        bericht = dienst.pruefen_ohne_speichern(inhalt)
    except (ratenbegrenzung.ZuVieleVersuche, DateiAbgelehnt) as fehler:
        return antworten(
            request,
            "landing/check.html",
            {
                "regeln": startkatalog(),
                "preis": LISTENPREIS[Modul.CHECK],
                "offen": True,
                "fehler": str(fehler),
            },
            benutzer=benutzer,
            status_code=400,
        )

    _log.info(
        "Offene Pruefung",
        extra={
            "dokument_hash": bericht.dokument_hash[:16],
            "befunde": len(bericht.ergebnis.befunde),
        },
    )
    return antworten(
        request,
        "landing/check.html",
        {
            "regeln": startkatalog(),
            "preis": LISTENPREIS[Modul.CHECK],
            "offen": True,
            "probe": bericht,
        },
        benutzer=benutzer,
    )


# ---------------------------------------------------------------------------
# Zugangsanfrage
# ---------------------------------------------------------------------------


@router.post("/zugang", include_in_schema=False)
async def zugang_anfordern(
    request: Request,
    _csrf: CsrfAbh,
    benutzer: OptionalerBenutzerAbh,
    name: Annotated[str, Form()],
    buero: Annotated[str, Form()],
    email: Annotated[str, Form()],
    plz: Annotated[str, Form()] = "",
    modul: Annotated[str, Form()] = "",
    # Honeypot: ein für Menschen unsichtbares Feld. Ist es gefüllt, war ein Bot da.
    webseite: Annotated[str, Form()] = "",
) -> Response:
    kennung = request.client.host if request.client else "unbekannt"
    if webseite.strip():
        _log.info("Zugangsanfrage verworfen (Honeypot)")
        return _oeffentlich(request, "landing/danke.html", {}, benutzer)
    try:
        ratenbegrenzung.pruefen_und_zaehlen("zugang", kennung, ratenbegrenzung.PASSWORT_ZURUECK)
    except ratenbegrenzung.ZuVieleVersuche as fehler:
        return antworten(
            request, "landing/danke.html", {"fehler": str(fehler)}, benutzer=benutzer, status_code=429
        )

    async with sitzungsfabrik()() as sitzung:
        sitzung.add(
            Zugangsanfrage(
                name=name.strip()[:200],
                buero=buero.strip()[:200],
                email=email.strip().lower()[:320],
                plz=plz.strip()[:10] or None,
                modul=modul.strip()[:20] or None,
            )
        )
        await sitzung.commit()

    betreiber = einstellungen().betreiber_email
    if betreiber:
        mail.senden(
            mail.Nachricht(
                empfaenger=betreiber,
                betreff="Testzugang angefordert",
                text=(
                    f"Büro: {buero.strip()}\nName: {name.strip()}\n"
                    f"E-Mail: {email.strip()}\nPLZ: {plz.strip() or '—'}\n"
                    f"Modul: {modul.strip() or '—'}\n"
                ),
            )
        )
    return _oeffentlich(request, "landing/danke.html", {"modul": modul}, benutzer)


# ---------------------------------------------------------------------------
# Rechtstexte
# ---------------------------------------------------------------------------

RECHTSSEITEN = {
    "impressum": ("Impressum", "recht/impressum.html"),
    "datenschutz": ("Datenschutzerklärung", "recht/datenschutz.html"),
    "agb": ("Allgemeine Geschäftsbedingungen", "recht/agb.html"),
    "auftragsverarbeitung": ("Vertrag zur Auftragsverarbeitung", "recht/av_vertrag.html"),
    "tom": ("Technische und organisatorische Maßnahmen", "recht/tom.html"),
    "unterauftragsverarbeiter": ("Unterauftragsverarbeiter", "recht/unterauftragsverarbeiter.html"),
}


def _rechtsseite_bauen(pfad: str, titel: str, vorlage: str) -> None:
    """Jede Rechtsseite bekommt eine eigene Route.

    Ein Platzhalterpfad wie ``/{seite}`` würde je nach Reihenfolge der Router
    auch ``/anmelden`` einsammeln. Explizite Pfade schließen das aus.
    """

    async def seite(request: Request, benutzer: OptionalerBenutzerAbh) -> Response:
        return _oeffentlich(request, vorlage, {"titel": titel, "stand": STAND}, benutzer)

    seite.__name__ = f"rechtsseite_{pfad.strip('/')}"
    router.get(pfad, include_in_schema=False)(seite)


for _pfad, (_titel, _vorlage) in RECHTSSEITEN.items():
    _rechtsseite_bauen(f"/{_pfad}", _titel, _vorlage)


@router.get("/auftragsverarbeitung.pdf", include_in_schema=False)
async def av_vertrag_pdf() -> Response:
    """Der AV-Vertrag als ausfüllbares PDF (Querschnitt 6.4).

    Kaufvoraussetzung, kein Zusatz: ohne AV-Vertrag darf kein Sachverständiger
    das Werkzeug rechtssicher einsetzen.
    """
    from starlette.concurrency import run_in_threadpool

    from belegwerk.web import pdf

    daten = await run_in_threadpool(
        pdf.aus_vorlage, "pdf/av_vertrag.html", {"stand": STAND}
    )
    return Response(
        daten,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="belegwerk-av-vertrag.pdf"',
            "Cache-Control": ZWISCHENSPEICHER,
        },
    )
