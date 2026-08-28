"""Erzeugt synthetische Gutachten-PDFs samt Sollwerten (Check-Todo 0.1/0.2).

Wie beim Kalkulationskorpus gilt: **keine echten Dokumente.** Siehe
``docs/PHASE-0.md``. Der Bestand deckt zwei Ausgabestile ab, damit die
labelbasierte Extraktion nicht auf eine einzige Schreibweise passt.

Zusätzlich baut ``regelfaelle()`` zu jeder der 20 Regeln ein Dokument, das sie
auslöst, und eines, das sie nicht auslöst (Todo 2.3).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

VERZEICHNIS = Path(__file__).parent / "gutachten"
ZENT = Decimal("0.01")


def _r(wert: Decimal) -> Decimal:
    return wert.quantize(ZENT, rounding=ROUND_HALF_UP)


def _de(wert: Decimal | None, stellen: int = 2) -> str:
    if wert is None:
        return ""
    text = f"{wert.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP):,.{stellen}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


@dataclass
class Gutachten:
    aktenzeichen: str = "0326/1147TG"
    gutachtenart: str = "Haftpflichtschaden"
    kennzeichen: str = "OL-AB 1234"
    kennzeichen_text: str | None = None
    vin: str = "WVWZZZAUZMW123456"
    erstzulassung: date = date(2023, 6, 14)
    laufleistung: int = 48320
    laufleistung_bewertung: int | None = None
    schadendatum: date = date(2026, 3, 12)
    besichtigungsdatum: date = date(2026, 3, 15)
    stundensatz_mechanik: Decimal = Decimal("142.00")
    stundensatz_karosserie: Decimal = Decimal("156.00")
    stundensatz_text: Decimal | None = None
    upe_aufschlag: Decimal = Decimal("18.0")
    reparaturkosten_netto: Decimal = Decimal("3832.07")
    mehrwertsteuersatz: Decimal = Decimal("19.0")
    wbw_brutto: Decimal = Decimal("12800.00")
    wbw_netto: Decimal | None = None
    restwert: Decimal = Decimal("5200.00")
    wertminderung: Decimal | None = Decimal("800.00")
    wertminderung_methode: str | None = "Ruhkopf/Sahm"
    wertminderung_begruendung: bool = False
    schadenfall: str = "Reparaturfall"
    reparaturdauer: int | None = 5
    wiederbeschaffungsdauer: int | None = 12
    umsatzsteuer_regime: str = "regelbesteuert"
    umsatzsteuer_regime_bewertung: str | None = "regelbesteuert"
    vorschaden: bool = False
    vorschaden_bewertet: bool | None = None
    altschaden: bool = False
    altschaden_abgegrenzt: bool | None = None
    weiterbenutzung: bool = False
    besichtigung_erlaeuterung: bool = False
    stil: str = "a"
    hinweise: list[str] = field(default_factory=list)

    @property
    def reparaturkosten_brutto(self) -> Decimal:
        return _r(self.reparaturkosten_netto * (Decimal(100) + self.mehrwertsteuersatz) / Decimal(100))

    @property
    def wbw_netto_effektiv(self) -> Decimal:
        if self.wbw_netto is not None:
            return self.wbw_netto
        return _r(self.wbw_brutto / Decimal("1.19"))


_BEZEICHNUNGEN = {
    "a": {
        "aktenzeichen": "Aktenzeichen",
        "gutachtenart": "Gutachtenart",
        "kennzeichen": "Amtl. Kennzeichen",
        "vin": "Fahrzeug-Identifizierungsnummer",
        "erstzulassung": "Erstzulassung",
        "laufleistung": "Laufleistung",
        "schadendatum": "Schadentag",
        "besichtigungsdatum": "Besichtigungstag",
        "reparaturkosten_netto": "Reparaturkosten netto",
        "reparaturkosten_brutto": "Reparaturkosten brutto",
        "wbw_brutto": "Wiederbeschaffungswert brutto",
        "wbw_netto": "Wiederbeschaffungswert netto",
        "restwert": "Restwert",
        "wertminderung": "Merkantile Wertminderung",
        "ergebnis": "Ergebnis",
    },
    "b": {
        "aktenzeichen": "Gutachten-Nr.",
        "gutachtenart": "Art des Gutachtens",
        "kennzeichen": "Kennzeichen",
        "vin": "FIN",
        "erstzulassung": "EZ",
        "laufleistung": "Kilometerstand",
        "schadendatum": "Schadendatum",
        "besichtigungsdatum": "Besichtigt am",
        "reparaturkosten_netto": "Reparaturkosten ohne MwSt",
        "reparaturkosten_brutto": "Reparaturkosten inkl. MwSt",
        "wbw_brutto": "WBW brutto",
        "wbw_netto": "WBW netto",
        "restwert": "Restwert brutto",
        "wertminderung": "Minderwert",
        "ergebnis": "Feststellung",
    },
}


def als_text(g: Gutachten) -> str:
    b = _BEZEICHNUNGEN[g.stil]
    kennzeichen_im_text = g.kennzeichen_text or g.kennzeichen
    zeilen = [
        "SACHVERSTAENDIGENBUERO MUSTER                       Schadengutachten",
        f"{b['aktenzeichen']:<34}{g.aktenzeichen}",
        f"{b['gutachtenart']:<34}{g.gutachtenart}",
        "",
        "1. Fahrzeug",
        f"{b['kennzeichen']:<34}{g.kennzeichen}",
        f"{b['vin']:<34}{g.vin}",
        f"{b['erstzulassung']:<34}{g.erstzulassung.strftime('%d.%m.%Y')}",
        f"{b['laufleistung']:<34}{_de(Decimal(g.laufleistung), 0)} km",
        "",
        "2. Schadenhergang und Besichtigung",
        f"{b['schadendatum']:<34}{g.schadendatum.strftime('%d.%m.%Y')}",
        f"{b['besichtigungsdatum']:<34}{g.besichtigungsdatum.strftime('%d.%m.%Y')}",
        f"Das Fahrzeug mit dem amtlichen Kennzeichen {kennzeichen_im_text} wurde am "
        f"{g.besichtigungsdatum.strftime('%d.%m.%Y')} in Augenschein genommen.",
        f"Vorschaeden                       {'liegt vor' if g.vorschaden else 'keine'}",
        f"Altschaeden                       {'liegt vor' if g.altschaden else 'keine'}",
    ]
    if g.vorschaden_bewertet:
        zeilen.append("Bewertung des Vorschadens         liegt vor")
    if g.altschaden_abgegrenzt:
        zeilen.append("Abgrenzung zum Altschaden         liegt vor")
    if g.besichtigung_erlaeuterung:
        zeilen.append(
            "Erlaeuterung zur Besichtigung     liegt vor: Das Fahrzeug stand bis zur "
            "Freigabe durch den Versicherer still."
        )

    zeilen += [
        "",
        "3. Kalkulation",
        f"Lohn Mechanik                     {_de(g.stundensatz_mechanik)} EUR",
        f"Lohn Karosserie                   {_de(g.stundensatz_karosserie)} EUR",
        f"UPE-Aufschlag                     {_de(g.upe_aufschlag, 1)} %",
        f"{b['reparaturkosten_netto']:<34}{_de(g.reparaturkosten_netto)} EUR",
        f"{b['reparaturkosten_brutto']:<34}{_de(g.reparaturkosten_brutto)} EUR",
        f"Mehrwertsteuersatz                {_de(g.mehrwertsteuersatz, 1)} %",
    ]
    if g.stundensatz_text is not None:
        zeilen.append(
            f"Der Kalkulation liegt ein Stundenverrechnungssatz von {_de(g.stundensatz_text)} EUR zugrunde."
        )

    zeilen += [
        "",
        "4. Bewertung",
        f"Umsatzsteuer                      {g.umsatzsteuer_regime}",
    ]
    if g.umsatzsteuer_regime_bewertung:
        zeilen.append(
            f"Bewertungsgrundlage Umsatzsteuer   {g.umsatzsteuer_regime_bewertung}"
        )
    if g.laufleistung_bewertung is not None:
        zeilen.append(
            f"Laufleistung (Bewertung)          {_de(Decimal(g.laufleistung_bewertung), 0)} km"
        )
    zeilen += [
        f"{b['wbw_brutto']:<34}{_de(g.wbw_brutto)} EUR",
        f"{b['wbw_netto']:<34}{_de(g.wbw_netto_effektiv)} EUR",
        f"{b['restwert']:<34}{_de(g.restwert)} EUR",
    ]
    if g.wertminderung is not None:
        zeilen.append(f"{b['wertminderung']:<34}{_de(g.wertminderung)} EUR")
    if g.wertminderung_methode:
        zeilen.append(f"Wertminderung nach                {g.wertminderung_methode}")
    if g.wertminderung_begruendung:
        zeilen.append(
            "Begruendung der Wertminderung     liegt vor: Das Fahrzeug weist trotz "
            "seines Alters eine unterdurchschnittliche Laufleistung auf."
        )

    zeilen += ["", "5. Ergebnis", f"{b['ergebnis']:<34}{g.schadenfall}"]
    if g.reparaturdauer is not None:
        zeilen.append(f"Reparaturdauer                    {g.reparaturdauer} Arbeitstage")
    if g.wiederbeschaffungsdauer is not None:
        zeilen.append(
            f"Wiederbeschaffungsdauer           {g.wiederbeschaffungsdauer} Arbeitstage"
        )
    if g.weiterbenutzung:
        zeilen.append(
            "Weiterbenutzung                   Das Fahrzeug ist nach fachgerechter "
            "Reparatur sechs Monate weiter zu benutzen."
        )
    zeilen += g.hinweise
    zeilen += [
        "",
        "Die fachliche Verantwortung fuer dieses Gutachten liegt beim unterzeichnenden",
        "Sachverstaendigen.",
        "",
    ]
    return "\n".join(zeilen) + "\n"


def sollwerte(g: Gutachten) -> dict[str, Any]:
    """Die von Hand erwarteten Feldwerte (Todo 0.2)."""
    art = {
        "Haftpflichtschaden": "haftpflicht",
        "Kaskoschaden": "kasko",
        "Wertgutachten": "wertgutachten",
        "Kurzgutachten": "kurzgutachten",
    }[g.gutachtenart]
    return {
        "aktenzeichen": g.aktenzeichen,
        "gutachtenart": art,
        "kennzeichen": g.kennzeichen,
        "vin": g.vin,
        "erstzulassung": g.erstzulassung.isoformat(),
        "laufleistung": str(g.laufleistung),
        "schadendatum": g.schadendatum.isoformat(),
        "besichtigungsdatum": g.besichtigungsdatum.isoformat(),
        "reparaturkosten_netto": str(_r(g.reparaturkosten_netto)),
        "reparaturkosten_brutto": str(g.reparaturkosten_brutto),
        "wiederbeschaffungswert_brutto": str(_r(g.wbw_brutto)),
        "wiederbeschaffungswert_netto": str(g.wbw_netto_effektiv),
        "restwert": str(_r(g.restwert)),
        "wertminderung": str(_r(g.wertminderung)) if g.wertminderung is not None else None,
        "mehrwertsteuersatz": str(g.mehrwertsteuersatz.quantize(Decimal("0.1"))),
        "stundensatz_mechanik": str(_r(g.stundensatz_mechanik)),
        "stundensatz_karosserie": str(_r(g.stundensatz_karosserie)),
        "upe_aufschlag": str(g.upe_aufschlag.quantize(Decimal("0.1"))),
        "umsatzsteuer_regime": g.umsatzsteuer_regime,
        "schadenfall": "reparaturfall" if g.schadenfall == "Reparaturfall" else "totalschaden",
        "reparaturdauer": str(g.reparaturdauer) if g.reparaturdauer is not None else None,
        "wiederbeschaffungsdauer": (
            str(g.wiederbeschaffungsdauer) if g.wiederbeschaffungsdauer is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# Je Regel ein ausloesender und ein nicht ausloesender Fall (Todo 2.3)
# ---------------------------------------------------------------------------


def regelfaelle() -> dict[str, tuple[Gutachten, Gutachten]]:
    """Zu jeder der 20 Regeln ein Paar: (loest aus, loest nicht aus)."""
    return {
        "restwert_ueber_wbw": (
            Gutachten(restwert=Decimal("13000.00")),
            Gutachten(),
        ),
        "reparaturfall_ueber_130": (
            Gutachten(reparaturkosten_netto=Decimal("15000.00"), schadenfall="Reparaturfall"),
            Gutachten(),
        ),
        "hundert_bis_130_ohne_weiterbenutzung": (
            Gutachten(reparaturkosten_netto=Decimal("11831.93"), weiterbenutzung=False),
            Gutachten(reparaturkosten_netto=Decimal("11831.93"), weiterbenutzung=True),
        ),
        "totalschaden_ohne_wiederbeschaffungsdauer": (
            Gutachten(
                schadenfall="Totalschaden", wiederbeschaffungsdauer=None, reparaturdauer=None
            ),
            Gutachten(schadenfall="Totalschaden", reparaturdauer=None),
        ),
        "wertminderung_ohne_methode": (
            Gutachten(wertminderung_methode=None),
            Gutachten(),
        ),
        "wertminderung_bei_altem_fahrzeug": (
            Gutachten(erstzulassung=date(2018, 4, 2), wertminderung_begruendung=False),
            Gutachten(erstzulassung=date(2018, 4, 2), wertminderung_begruendung=True),
        ),
        "wertminderung_ueber_zehn_prozent": (
            Gutachten(wertminderung=Decimal("1500.00")),
            Gutachten(),
        ),
        "umsatzsteuerregime_widerspruechlich": (
            Gutachten(
                umsatzsteuer_regime="regelbesteuert",
                umsatzsteuer_regime_bewertung="differenzbesteuert",
            ),
            Gutachten(),
        ),
        "wbw_differenz_kein_steuersatz": (
            Gutachten(wbw_netto=Decimal("11000.00")),
            Gutachten(),
        ),
        "differenzbesteuert_mit_neunzehn": (
            Gutachten(
                umsatzsteuer_regime="differenzbesteuert",
                umsatzsteuer_regime_bewertung="differenzbesteuert",
                wbw_netto=Decimal("12500.00"),
                mehrwertsteuersatz=Decimal("19.0"),
            ),
            Gutachten(
                umsatzsteuer_regime="differenzbesteuert",
                umsatzsteuer_regime_bewertung="differenzbesteuert",
                wbw_netto=Decimal("12500.00"),
                mehrwertsteuersatz=Decimal("2.4"),
            ),
        ),
        "reparaturfall_ohne_reparaturdauer": (
            Gutachten(reparaturdauer=None),
            Gutachten(),
        ),
        "vorschaden_nicht_bewertet": (
            Gutachten(vorschaden=True, vorschaden_bewertet=None),
            Gutachten(vorschaden=True, vorschaden_bewertet=True),
        ),
        "altschaden_nicht_abgegrenzt": (
            Gutachten(altschaden=True, altschaden_abgegrenzt=None),
            Gutachten(altschaden=True, altschaden_abgegrenzt=True),
        ),
        "besichtigung_vor_schaden": (
            Gutachten(besichtigungsdatum=date(2026, 3, 10)),
            Gutachten(),
        ),
        "besichtigung_spaet": (
            Gutachten(besichtigungsdatum=date(2026, 6, 20), besichtigung_erlaeuterung=False),
            Gutachten(besichtigungsdatum=date(2026, 6, 20), besichtigung_erlaeuterung=True),
        ),
        "laufleistung_abweichend": (
            Gutachten(laufleistung_bewertung=50000),
            Gutachten(laufleistung_bewertung=48320),
        ),
        "vin_unplausibel": (
            Gutachten(vin="WVWZZZAUZMW12345"),
            Gutachten(),
        ),
        "kennzeichen_abweichend": (
            Gutachten(kennzeichen_text="OL-CD 9999"),
            Gutachten(),
        ),
        "stundensatz_abweichend": (
            Gutachten(stundensatz_text=Decimal("140.00")),
            Gutachten(stundensatz_text=Decimal("156.00")),
        ),
        # Regel 20 braucht ein in den Einstellungen hinterlegtes Muster; der
        # Test setzt es, deshalb hier nur die beiden Aktenzeichen.
        "aktenzeichen_format": (
            Gutachten(aktenzeichen="XY-2026-7"),
            Gutachten(aktenzeichen="0326/1147TG"),
        ),
    }


# ---------------------------------------------------------------------------
# Bestand schreiben
# ---------------------------------------------------------------------------


def _pdf(text: str) -> bytes:
    from html import escape

    from weasyprint import HTML

    html = (
        "<html><head><meta charset='utf-8'><style>"
        "@page { size: A4; margin: 12mm; }"
        "pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 8pt; "
        "line-height: 1.3; white-space: pre-wrap; }"
        "</style></head><body><pre>" + escape(text) + "</pre></body></html>"
    )
    return bytes(HTML(string=html).write_pdf())


def erzeugen(mit_pdf: bool = True) -> int:
    """20 Gutachten als PDF mit Sollwertdatei (Todo 0.1 und 0.2)."""
    VERZEICHNIS.mkdir(parents=True, exist_ok=True)
    for alt in VERZEICHNIS.glob("*"):
        alt.unlink()

    zufall = random.Random(4242)
    anzahl = 0
    for i in range(20):
        wbw = Decimal(zufall.randrange(450_000, 3_500_000, 1000)) / 100
        g = Gutachten(
            aktenzeichen=f"{zufall.randint(100, 999):04d}/{zufall.randint(1000, 9999)}TG",
            gutachtenart="Haftpflichtschaden" if i % 3 else "Kaskoschaden",
            kennzeichen=f"OL-{chr(65 + zufall.randrange(26))}{chr(65 + zufall.randrange(26))} {zufall.randint(10, 9999)}",
            vin="WVWZZZ" + "".join(zufall.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(11)),
            erstzulassung=date(2026, 1, 1) - timedelta(days=zufall.randint(500, 2400)),
            laufleistung=zufall.randrange(15_000, 190_000, 10),
            schadendatum=date(2026, 1, 1) + timedelta(days=zufall.randint(0, 200)),
            stundensatz_mechanik=Decimal(zufall.randrange(11000, 17500, 100)) / 100,
            stundensatz_karosserie=Decimal(zufall.randrange(12000, 18500, 100)) / 100,
            reparaturkosten_netto=_r(wbw * Decimal(zufall.randrange(20, 70)) / Decimal(100)),
            wbw_brutto=wbw,
            restwert=_r(wbw * Decimal(zufall.randrange(15, 45)) / Decimal(100)),
            wertminderung=Decimal(zufall.randrange(0, 90000, 5000)) / 100 or None,
            stil="a" if i % 2 == 0 else "b",
        )
        g.besichtigungsdatum = g.schadendatum + timedelta(days=zufall.randint(1, 25))
        text = als_text(g)
        name = f"gutachten_{i:02d}"
        (VERZEICHNIS / f"{name}.txt").write_text(text, encoding="utf-8")
        if mit_pdf:
            (VERZEICHNIS / f"{name}.pdf").write_bytes(_pdf(text))
        (VERZEICHNIS / f"{name}.soll.json").write_text(
            json.dumps(sollwerte(g), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        anzahl += 1
    return anzahl


if __name__ == "__main__":
    print(f"{erzeugen()} Gutachten in {VERZEICHNIS}")
