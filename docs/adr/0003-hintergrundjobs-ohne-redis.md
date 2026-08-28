# ADR 0003 — Hintergrundjobs über eine Tabelle statt ARQ/Redis

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Die Plattformdatei sieht ARQ auf Redis für asynchrones PDF-Parsing vor, damit
das Parsing nicht im Request läuft, sowie vier Coolify-Ressourcen (App,
Postgres, Redis, Landing).

## Entscheidung

Aufträge liegen in der Tabelle `auftrag` in PostgreSQL. Ein Arbeiter-Task im
Anwendungsprozess holt sie mit `SELECT … FOR UPDATE SKIP LOCKED` und arbeitet
sie ab. Die Oberfläche fragt den Fortschritt per HTMX-Polling ab. Kein Redis.

## Begründung

- Die fachliche Anforderung ist „nicht im Request", nicht „Redis". Sie ist mit
  einer Tabelle erfüllt.
- Eine Ressource weniger im Betrieb heißt: eine Ressource weniger im Backup, im
  Health-Check und in der Unterauftragsverarbeiter-Liste.
- `FOR UPDATE SKIP LOCKED` erlaubt später mehrere Replicas ohne Umbau.
- Die Aufträge sind langlebig und nachvollziehbar (Fehlertext, Versuche,
  Dauer je Adapter) — das ist die Grundlage für die Metriken aus
  Querschnitt 4.3, die eine Redis-Queue so nicht liefert.

## Folgen

- Bei sehr hohem Durchsatz wäre die Tabelle ein Engpass. Bei einem Markt von
  rund 3.000 Büros ist das keine reale Größe.
- Der Arbeiter läuft im Anwendungscontainer. Ein hängendes Parsing kann einen
  Worker-Slot blockieren; deshalb Zeitgrenze je Auftrag und begrenzte
  Nebenläufigkeit.
