# ADR 0006 — Adapterprofile als YAML statt Regexe im Code

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Die Plattformdatei nennt sechs Adapter (`dat_vxs`, `dat_pdf`, `dat_txt`,
`audatex_pdf`, `pruefbericht_controlexpert`, `pruefbericht_generisch`). Naiv
umgesetzt sind das sechs Python-Module mit je fünfzig verstreuten regulären
Ausdrücken.

Zwei Beobachtungen sprechen dagegen:

1. DAT-PDF und DAT-TXT unterscheiden sich **nicht** fachlich, sondern nur im
   Extraktionspfad davor. Zwei Module wären zwei Kopien derselben Logik.
2. Audatex und die Prüfberichte unterscheiden sich von DAT nur in den Wörtern
   („Teilepositionen" statt „Ersatzteile", „AZ-Satz" statt „Lohn"), nicht in
   der Struktur: Kopfdaten, Verrechnungssätze, Positionsblöcke, Summen.

## Entscheidung

Eine profilgesteuerte Maschine (`adapter/tabellen.py`) liest die Struktur; die
Wörter stehen in einem YAML-Profil je Absender. Das Profil benennt außerdem,
welchen Adapternamen es je Quellformat nach außen trägt — die Namen aus dem
Briefing bleiben damit erhalten.

VXS bleibt ein eigenes Modul: XML ist keine Zeilenstruktur.

## Begründung

Der eigentliche Wert dieses Produkts nach einem Jahr sind die gepflegten
Muster, nicht der Code darum. Ein neues Absenderlayout muss eine Datei sein,
die jemand ergänzt, kein Programmierauftrag. Dasselbe Argument steht im
Check-Briefing für den Feldkatalog — hier gilt es genauso.

## Folgen

- Ein neues Layout: eine YAML-Datei, kein Deployment einer neuen Codepfad-Logik.
- Fehlerhafte Muster fallen beim Laden auf (`ProfilFehler` nennt Datei und
  Ausdruck), nicht erst zur Laufzeit beim Kunden.
- Die Profile sind Teil des Images und damit versioniert und testbar.
- Grenze: Layouts, die sich nicht zeilenweise lesen lassen (echte Tabellen mit
  Zellenumbrüchen), brauchen weiterhin ein eigenes Modul. Der VXS-Adapter zeigt,
  wie das aussieht.
