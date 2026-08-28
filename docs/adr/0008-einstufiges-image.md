# ADR 0008 — Einstufiges Image

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Das Dockerfile war zunächst zweistufig: eine Baustufe mit `build-essential`,
die ein virtuelles Environment füllt, und eine schlanke Laufzeitstufe, die es
übernimmt. Der erste Bau auf Coolify schlug fehl, ohne dass die API ein
Protokoll herausgibt.

## Entscheidung

Ein Abschnitt, kein `build-essential`, keine `# syntax`-Direktive.

## Begründung

Der zweite Bauabschnitt sollte den Compiler aus dem Ergebnis heraushalten.
Geprüft man die Abhängigkeitsliste, braucht keine davon einen Compiler: asyncpg,
lxml, Pillow, cffi (für argon2), pydantic-core, rapidfuzz, cryptography und die
Beschleuniger von uvicorn liegen alle als manylinux-Wheels für CPython 3.12 vor.
Ohne Compiler im Bau bringt die Trennung nichts mehr — sie kostet nur eine
weitere Fehlerquelle in einer Umgebung, deren Bauprotokoll nicht abrufbar ist.

Die `# syntax`-Direktive fällt aus demselben Grund weg: sie zieht ein weiteres
Image aus einer Registry, ohne dass eine BuildKit-Besonderheit gebraucht würde.

## Folgen

- Das Image ist geringfügig größer als die Laufzeitstufe es gewesen wäre, weil
  `pip` und `setuptools` darin bleiben.
- Der Bau ist deutlich schneller, weil `build-essential` nicht mehr installiert
  wird.
- Sollte künftig eine Abhängigkeit ohne Wheel dazukommen, ist die Baustufe in
  der Historie dieser Datei nachlesbar.
