"""PDF-Ausgabe über WeasyPrint — dieselben Vorlagen wie die Weboberfläche.

Die erzeugten Anlagen gehen an Versicherer und Gerichte. Deshalb: A4, lesbare
Größen, Beträge in Mono untereinander, Kopf- und Fußzeile auf jeder Seite,
Briefkopf des Mandanten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from weasyprint import CSS, HTML

from belegwerk.web.vorlagen import STATIK_VERZEICHNIS, VORLAGEN_VERZEICHNIS, vorlagen

DRUCK_CSS = """
@page {
  size: A4;
  margin: 18mm 15mm 20mm 15mm;
  @bottom-left { content: string(fusszeile); font-size: 7pt; color: #4A5058; }
  @bottom-right { content: "Seite " counter(page) " von " counter(pages);
                  font-size: 7pt; color: #4A5058; }
}
body { font-family: 'Public Sans', sans-serif; font-size: 9pt; color: #14181D; background: #fff; }
h1 { font-family: 'Archivo', sans-serif; font-size: 15pt; margin: 0 0 2mm; }
h2 { font-family: 'Archivo', sans-serif; font-size: 11pt; margin: 6mm 0 2mm; }
.mono, .zahl, td.zahl, th.zahl { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
.zahl { text-align: right; white-space: nowrap; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 1.2mm 2mm; border-bottom: 0.2mm solid #C3C8CE; text-align: left; vertical-align: top; }
thead th { background: #14181D; color: #ECEEF0; font-size: 7.5pt; text-transform: uppercase;
           letter-spacing: 0.04em; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
.briefkopf { border-bottom: 0.4mm solid #14181D; padding-bottom: 2mm; margin-bottom: 5mm;
             display: flex; justify-content: space-between; align-items: flex-end; gap: 6mm; }
.briefkopf .absender { font-size: 8pt; line-height: 1.35; white-space: pre-line; }
.briefkopf img { max-height: 18mm; max-width: 55mm; }
.kopfdaten { font-size: 8.5pt; }
.kopfdaten dt { float: left; width: 42mm; color: #4A5058; }
.kopfdaten dd { margin: 0 0 1mm 42mm; }
.methodik { font-size: 7.5pt; color: #4A5058; border-top: 0.2mm solid #C3C8CE;
            margin-top: 6mm; padding-top: 2mm; }
.fuss { string-set: fusszeile content(); }
.marker { font-family: 'JetBrains Mono', monospace; font-size: 7pt; text-transform: uppercase;
          border: 0.2mm solid currentColor; padding: 0.3mm 1mm; }
.marker-fehler { color: #C8102E; }
.marker-warnung { color: #8a6300; }
.marker-hinweis { color: #4A5058; }
.quittiert { color: #4A5058; }
.summenzeile td { border-top: 0.4mm solid #14181D; font-weight: 600; }
"""


def _schriften_css() -> str:
    """Bindet die lokalen Schriften mit absoluten Dateipfaden ein.

    WeasyPrint kennt keine variablen Achsen und verwirft Bereichsangaben wie
    ``font-weight: 100 900`` samt zugehöriger Schrift. Für den PDF-Pfad wird
    deshalb je Datei ein Schnitt in 400 und einer in 700 deklariert; den fetten
    Schnitt setzt WeasyPrint synthetisch. Im Browser bleibt die variable
    Deklaration unverändert.
    """
    import re

    quelle = (STATIK_VERZEICHNIS / "schriften.css").read_text(encoding="utf-8")
    quelle = quelle.replace("/static/fonts/", f"{(STATIK_VERZEICHNIS / 'fonts').as_uri()}/")
    quelle = re.sub(r"\s*font-stretch:[^;]+;\n", "\n", quelle)
    quelle = quelle.replace("format('woff2-variations')", "format('woff2')")

    bloecke = re.findall(r"@font-face\s*\{[^}]*\}", quelle)
    gebaut: list[str] = []
    for block in bloecke:
        for gewicht in ("400", "700"):
            gebaut.append(re.sub(r"font-weight:\s*[\d ]+;", f"font-weight: {gewicht};", block))
    return "\n".join(gebaut)


def aus_vorlage(name: str, kontext: dict[str, Any]) -> bytes:
    """Rendert eine Jinja-Vorlage und macht ein PDF daraus."""
    html = vorlagen.get_template(name).render(**kontext)
    dokument = HTML(string=html, base_url=str(VORLAGEN_VERZEICHNIS))
    return bytes(
        dokument.write_pdf(stylesheets=[CSS(string=_schriften_css()), CSS(string=DRUCK_CSS)])
    )


def logo_datei_uri(pfad: str | None) -> str | None:
    if not pfad:
        return None
    datei = Path(pfad)
    return datei.as_uri() if datei.exists() else None
