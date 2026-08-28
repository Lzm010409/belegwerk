# ADR 0005 — Mandantentrennung über Row Level Security mit eigener App-Rolle

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Querschnitt 1 verlangt, dass die Trennung nicht davon abhängt, dass jede
Abfrage ihr `WHERE mandant_id = ?` mitbringt. Vorgesehen ist PostgreSQL Row
Level Security mit der Sitzungsvariablen `app.mandant_id`.

Dabei gibt es eine Falle: **PostgreSQL umgeht RLS für Superuser vollständig.**
Coolify legt die Datenbank mit einem Benutzer an, der Superuser ist. Eine
Policy allein wäre in diesem Betrieb wirkungslos gewesen — und zwar lautlos.

## Entscheidung

1. Die Migration legt die Rolle `belegwerk_app` an: `NOLOGIN NOSUPERUSER
   NOBYPASSRLS`, mit DML-Rechten auf den Tabellen, ohne DDL-Rechte.
2. Jede Anfrage arbeitet in einer Transaktion, die mit
   `SET LOCAL ROLE belegwerk_app` und
   `set_config('app.mandant_id', …, true)` beginnt. Nach dem Commit ist beides
   wieder weg.
3. Die Policies vergleichen gegen
   `NULLIF(current_setting('app.mandant_id', true), '')::uuid`. Ohne gesetzte
   Variable ist die Bedingung unerfüllbar, die Abfrage liefert null Zeilen.
   `NULLIF` verhindert, dass eine leere Variable beim Cast einen Fehler wirft.
4. Nur Anmeldung, Auftragsarbeiter, Wartungsjobs, Erststart, die öffentlichen
   Endpunkte und der Atlas-Pool arbeiten unter der Eigentümerrolle. Diese Liste
   steht in `tests/test_architektur.py` und wächst nur bewusst.
5. Anwendungsseitige Filter bleiben zusätzlich bestehen. RLS ist das Netz, nicht
   die Entschuldigung.

## Nachweis

`tests/test_mandantentrennung.py` findet die zu prüfenden Tabellen über
Introspektion des Modellregisters und prüft für **jede** von ihnen:
Lesen über Kreuz, Schreiben unter fremder `mandant_id` (`WITH CHECK`), Löschen
fremder Zeilen, Abfrage ohne gesetzten Kontext. Zusätzlich wird geprüft, dass
`belegwerk_app` weder Superuser ist noch `BYPASSRLS` trägt — genau die
Eigenschaft, an der die Konstruktion still scheitern würde.

## Folgen

- Ein neues Modell mit `MandantMixin` wird vom Test automatisch erfasst; seine
  Migration muss die Policy anlegen, sonst fehlt der Zugriff für `belegwerk_app`
  und der Test schlägt fehl.
- Wartungsjobs müssen bewusst gegen alle Mandanten arbeiten und stehen deshalb
  auf der Ausnahmeliste.
