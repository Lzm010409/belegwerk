# Phase 0 — offener Punkt vor dem Produktivgang

Alle drei Briefings beginnen mit einer Phase 0, die **echte Dokumente**
verlangt, und Delta enthält in 0.3 eine ausdrückliche **Abbruchentscheidung**.

## Was tatsächlich vorliegt

Dem bauenden Agenten lagen keine Echtdokumente vor. Der Testkorpus unter
`tests/fixtures/dokumente/` ist **synthetisch** und wird von
`tests/fixtures/generator.py` deterministisch erzeugt:

| Bestand | Anzahl | Zweck |
|---|---|---|
| DAT als TXT | 10 | Parserlogik, Rechenwege |
| DAT als PDF | 10 | beide Extraktionspfade, Spaltenerhalt |
| DAT als VXS | 10 | XML-Adapter |
| Audatex als PDF | 10 | zweites Vokabular, gleiche Struktur |
| Prüfberichte (ControlExpert, generisch) | 15 | Kürzungslogik, Paarbildung für Delta |
| Gutachten als PDF | 20 | Feldkatalog und Regelmaschine von Check |

Der Korpus prüft, dass die Maschine rechnet, zuordnet und ihre Unsicherheit
meldet. Er prüft **nicht**, ob die Muster echte Layoutvielfalt aushalten.

## Was noch zu tun ist

1. **0.1** 30 anonymisierte Echtdokumente je Format und 15 echte Prüfberichte
   von mindestens zwei Absendern in `tests/fixtures/dokumente/` ablegen
   (Namen, Kennzeichen, VIN, Adressen ersetzt).
2. **0.2** `skripte/extraktionsvergleich.py` über den Echtbestand laufen lassen.
   Es stellt beide Extraktionspfade nebeneinander und schreibt eine Tabelle.
3. **0.3** **Abbruchentscheidung.** Sind bei mindestens 80 % der Echtdokumente
   Positionszeilen zuverlässig als Zeilen erkennbar? Diese Entscheidung ist
   **nicht getroffen**.

Weil die Muster als Profile in `src/belegwerk/dokumente/profile/*.yaml` liegen,
ist die Anpassung an echte Layouts eine Ergänzung dieser Dateien und kein
Umbau (siehe ADR 0006). Die Golden-Tests laufen anschließend über beide
Bestände.

## Ebenso offen

- **Markenrecherche** (Querschnitt 0.2): DPMA Klassen 9 und 42, DENIC,
  Handelsregister. Siehe ADR 0001.
- **Anwaltliche Prüfung** (Querschnitt 6.7): Poolmodell bei Atlas, offene
  Dropzone bei Check, Rechtstexte. Die Rechtstexte im Repository sind
  vollständige Entwürfe, keine geprüften Dokumente.
