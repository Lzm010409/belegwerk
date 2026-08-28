# ADR 0001 — Name und Modulschnitt

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Querschnittsdatei Abschnitt 0 verlangt, den Namen vor Beginn festzulegen: er
steckt in Repository-, Datenbank- und Image-Namen. Im Raum standen „Prüfwerk"
mit Delta/Atlas/Check sowie „Fixpunkt" mit Gegenmaß/Marktmaß/Endmaß.

## Entscheidung

Dachmarke **Belegwerk**, Module **Delta** (Kalkulationsvergleich), **Atlas**
(Stundensatz-Register), **Check** (Endkontrolle).

Ausschlaggebend ist das bereits bestehende Repository `Lzm010409/belegwerk`.
Ein abweichender Produktname hätte Repository, Branch-Vorgabe und Deployment
auseinanderlaufen lassen. Die Modulnamen bleiben bei den Arbeitsnamen der
Briefings, weil sie in allen vier Vorgabedateien durchgehend verwendet werden
und fachlich treffen.

## Folgen

- Datenbankname, Docker-Image und Coolify-Projekt heißen `belegwerk`.
- Pfade: `/delta`, `/atlas`, `/check`, Anwendung unter `/app`.
- Die markenrechtliche Recherche (DPMA Klassen 9 und 42, DENIC, Handelsregister)
  aus Todo 0.2 ist **nicht** erledigt und bleibt offen. Sie ist keine technische
  Aufgabe und muss vor einer Markenanmeldung nachgeholt werden.
