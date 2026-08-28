# Belegwerk

Drei Werkzeuge für unabhängige Kfz-Sachverständige unter einer Anmeldung:

| Modul | Aufgabe |
|---|---|
| **Delta** | Legt die eigene Schadenkalkulation neben den Prüfbericht des Versicherers und zeigt Position für Position, was gestrichen wurde und was es kostet. |
| **Atlas** | Regionale Stundenverrechnungssätze, UPE-Aufschläge und Verbringungskosten mit Erhebungsnachweis. |
| **Check** | Prüft das fertige Gutachten-PDF gegen einen Regelkatalog, bevor es beim Versicherer liegt. |

## Aufbau

```
src/belegwerk/
├─ dokumente/     Dokumentenpaket: Modell, Erkennung, Adapter — das Kernstück.
│                 Kein anderes Modul sieht jemals ein PDF.
├─ kern/          Auth, Mandanten, Abonnements, Uploads, Formate
├─ delta/         Kalkulationsvergleich
├─ atlas/         Stundensatz-Register
├─ check/         Endkontrolle
└─ web/           Vorlagen, Stylesheet, Schriften, Fehlerseiten
migrationen/      Alembic
tests/            pytest
docs/adr/         Architekturentscheidungen
```

## Entwicklung

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up -d datenbank
DATABASE_URL=postgresql://belegwerk:belegwerk@localhost:5432/belegwerk .venv/bin/alembic upgrade head
.venv/bin/uvicorn belegwerk.anwendung:app --reload
```

Tests: `.venv/bin/python -m pytest`  ·  Typen: `.venv/bin/mypy`

## Betrieb

Zwei getrennte Coolify-Ressourcen: eine PostgreSQL-Datenbank und die Anwendung
aus dem `Dockerfile`. Migrationen laufen als Pre-Deploy-Command
(`/app/skripte/vor-deployment.sh`), nicht beim Start. Secrets ausschließlich als
Environment-Variablen. Persistentes Volume auf `/data`.

Health: `GET /gesundheit` — prüft die Datenbank, nicht nur den Prozess.

## Grundsätze

- Geldbeträge sind immer `Decimal`, niemals `float`.
- Zahlen werden nie von einem Sprachmodell erzeugt, geschätzt oder korrigiert.
- Mandantentrennung wird in der Datenbank erzwungen (Row Level Security), nicht
  nur in der Anwendung.
- Deutsche Beschriftungen in der Oberfläche, deutsche Bezeichner im Code.

## Dokumentation

| Datei | Inhalt |
|---|---|
| `docs/BETRIEB.md` | Coolify-Aufbau, Umgebungsvariablen, Migrationen, Sicherung, offene Punkte |
| `docs/PHASE-0.md` | Was der Testkorpus leistet, was er nicht leistet, und welche Entscheidungen offen sind |
| `docs/adr/` | Architekturentscheidungen mit Begründung |

## Stand der Umsetzung

| Bereich | Stand |
|---|---|
| Mandantentrennung (RLS, Introspektionstest über alle Tabellen) | umgesetzt und belegt |
| Auth, Rollen, Einladungen, Rate-Limit, CSRF, CSP | umgesetzt |
| Dokumentenpaket: zwei Extraktionspfade, Profiladapter, Konfidenz | umgesetzt, Fixtures synthetisch |
| Check: Feldkatalog, sichere Regelmaschine, 20 Regeln, Quittierung, PDF | umgesetzt |
| Delta: Kaskade, elf Klassen, Kontrollrechnung, PDF und JSON | umgesetzt |
| Atlas: Umkreis, Statistik, Nachweispflicht, PDF und CSV | umgesetzt |
| Atlas-Pool | gebaut, bis zur wettbewerbsrechtlichen Prüfung abgeschaltet |
| Abonnements, Datenexport, Kontolöschung, Wartung | umgesetzt |
| Landingpages und Rechtstexte | umgesetzt, Rechtstexte als ungeprüfte Entwürfe gekennzeichnet |
| Abrechnung mit Zahlungsanbieter | nicht umgesetzt (Querschnitt 2.1 sieht das bewusst später vor) |
| Echtdokumente, Abbruchentscheidung, PLZ-Amtsdaten, Markenrecherche | offen, siehe `docs/PHASE-0.md` |
