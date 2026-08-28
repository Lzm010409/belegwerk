# Betrieb auf Coolify

## Aufbau

Zwei getrennte Ressourcen im Projekt `belegwerk`, Umgebung `production` —
Oberfläche und Datenbank sind eigenständige Ressourcen mit eigenem
Lebenszyklus, eigener Sicherung und eigenem Neustart.

| Ressource | Art | Inhalt |
|---|---|---|
| `belegwerk-postgres` | PostgreSQL 16 (Alpine) | Datenbank, nicht öffentlich erreichbar |
| `belegwerk-app` | Anwendung aus `Dockerfile` | Oberfläche, Auftragsarbeiter, Wartung |

Die Anwendung erreicht die Datenbank ausschließlich über das interne
Docker-Netz des Projekts. Der Port der Datenbank ist nicht nach außen
veröffentlicht.

## Umgebungsvariablen

Secrets stehen ausschließlich als Coolify-Environment-Variablen; im Image liegt
keine `.env`.

| Variable | Bedeutung |
|---|---|
| `DATABASE_URL` | Interne Verbindung zur Postgres-Ressource. `postgres://` und `postgresql://` werden von der Anwendung auf den asyncpg-Treiber gehoben. |
| `SITZUNG_GEHEIMNIS` | Zufallswert. Ein Wechsel entwertet alle bestehenden Sitzungen. |
| `APP_BASIS_URL` | Öffentliche Adresse; steckt in Einladungs- und Rücksetzlinks. |
| `UMGEBUNG` | `produktion` schaltet HSTS ein und die API-Dokumentation aus. |
| `DATEN_VERZEICHNIS` | `/data` — das persistente Volume. |
| `ERSTER_ADMIN_*` | Legt beim allerersten Start Mandant und Inhaber an. Ist bereits ein Benutzer vorhanden, passiert nichts mehr. |
| `BETREIBER_EMAIL` | Empfänger für Rückmeldungen und Zugangsanfragen. |
| `AUFBEWAHRUNG_UPLOADS_TAGE` | Standard 90. |
| `AUFBEWAHRUNG_ERGEBNISSE_TAGE` | Standard 365. |
| `TESTPHASE_TAGE` | Standard 30. |
| `KONTO_KARENZ_TAGE` | Standard 14. |
| `OEFFENTLICHE_PRUEFUNG_AKTIV` | Schaltet die offene Dropzone auf `/check`. |
| `SMTP_*` | Ohne diese Angaben werden Mails nur protokolliert; die Anwendung läuft weiter und nennt Einladungslinks direkt in der Oberfläche. |
| `MISTRAL_API_SCHLUESSEL` | Ohne Schlüssel bleibt der Sprachmodellpfad global aus. |

## Migrationen

Migrationen laufen als **Pre-Deploy-Command** (`/app/skripte/vor-deployment.sh`),
nicht beim Start der Anwendung. Sonst würden bei mehreren Replicas zwei
Migrationen gegeneinander laufen.

Die erste Migration legt die Datenbankrolle `belegwerk_app` an und schaltet Row
Level Security ein. Sie muss unter dem Eigentümer der Datenbank laufen — genau
das tut der Pre-Deploy-Command.

## Health

`GET /gesundheit` prüft die Datenbankverbindung und antwortet mit 503, wenn sie
fehlt. Ein laufender Prozess allein gilt nicht als gesund. Der Container hat
zusätzlich einen eigenen `HEALTHCHECK`.

## Persistenz und Sicherung

Ein Volume auf `/data` mit den Unterordnern `uploads` und `ausgaben`.

**Noch einzurichten (Querschnitt 5):**

1. Tägliche Postgres-Sicherung in Coolify aktivieren, Aufbewahrung 30 Tage,
   Ziel außerhalb dieses Servers.
2. Das Volume `/data` in die Sicherung aufnehmen — dort liegen Kundendokumente.
3. **Wiederherstellung einmal vollständig durchspielen** und die Schritte
   notieren. Ein nie getestetes Backup ist kein Backup.

## Jobs im Anwendungscontainer

- **Auftragsarbeiter**: holt Verarbeitungsaufträge aus der Tabelle `auftrag`
  (`FOR UPDATE SKIP LOCKED`), meldet Fortschritt, wiederholt bis zu dreimal.
- **Wartung**: täglich. Aufbewahrungsfristen, abgelaufene Sitzungen,
  Erinnerung an Erhebungen über 24 Monate, Abo-Ablauf, fällige Kontolöschungen.

Beide laufen im Anwendungsprozess. Bei mehreren Replicas braucht die Wartung
eine Sperre über die Datenbank — der Auftragsarbeiter ist bereits dafür
ausgelegt.

## Skalierung

Eine Replica. Der Auftragsarbeiter verträgt mehrere; die Wartung nicht (siehe
oben), und das Rate-Limit liegt im Prozessspeicher. Vor der zweiten Replica sind
beide Punkte zu lösen.

## Was vor dem ersten externen Nutzer fehlt

1. Sicherung und erprobte Wiederherstellung (siehe oben).
2. SMTP mit SPF, DKIM und DMARC — ohne das landen Einladungen im Spam und das
   Onboarding bricht (Querschnitt 3.1).
3. Fehlerbenachrichtigung an den Betreiber (GlitchTip oder Sentry, selbst
   gehostet), Querschnitt 4.2.
4. Uptime-Prüfung von außen gegen `/gesundheit`, Querschnitt 4.5.
5. Anwaltliche Prüfung der Rechtstexte, des Atlas-Poolmodells und der offenen
   Dropzone auf `/check` (Querschnitt 6.7).
6. Die Punkte aus `docs/PHASE-0.md`: echter Dokumentenkorpus und die
   Abbruchentscheidung, amtliche PLZ-Mittelpunkte, Markenrecherche.
