# ADR 0002 — Handgeschriebenes CSS statt Tailwind-CLI

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Die Plattformdatei nennt Tailwind CSS (CLI, einmalig gebaut) als Styling-Schicht
und ein zweistufiges Dockerfile, dessen erste Stufe das CSS baut.

## Entscheidung

Das Stylesheet (`web/static/belegwerk.css`, rund 260 Zeilen) ist von Hand
geschrieben und benennt die Tokens aus Abschnitt 6 direkt als CSS-Variablen.
Keine Node-Stufe im Dockerfile.

## Begründung

Die Gestaltungsvorgabe ist eng und eigenwillig: Positionsraster, Haarlinien,
Tabellen mit Mono-Ziffern, Gerätefront-Anmutung. Davon kommt nichts aus einer
Utility-Bibliothek; Tailwind hätte fast ausschließlich über `@apply` und
Custom-Properties benutzt werden müssen. Der Gegenwert wäre eine zusätzliche
Build-Stufe, eine Node-Abhängigkeit im Bau und ein Generierungsschritt zwischen
Quelltext und Ergebnis gewesen.

Die Vorgabe aus Abschnitt 6 („Tokens und Signature-Vorgabe entscheiden über das
Aussehen") bleibt vollständig erfüllt — sie ist der Inhalt der Datei.

## Folgen

- Ein Bauschritt weniger, Image kleiner, Deployment schneller.
- Wer die Gestaltung ändert, ändert eine Datei, nicht eine Konfiguration plus
  Klassenlisten in Vorlagen.
- Fehlt eine Utility-Klasse, muss sie geschrieben werden. Bei diesem
  Oberflächenumfang ist das der geringere Aufwand.
