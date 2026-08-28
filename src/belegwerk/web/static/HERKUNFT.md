# Herkunft der mitgelieferten Fremddateien

Keine dieser Dateien wird zur Laufzeit von einem fremden Server geladen; alles
liegt im Image (DSGVO, Content-Security-Policy ohne fremde Quellen).

| Datei | Paket | Version | Lizenz |
|---|---|---|---|
| `htmx.min.js` | `htmx.org` (npm) | 2.0.4 | BSD-2-Clause (Zero-Clause) |
| `alpine.min.js` | `alpinejs` (npm), `dist/cdn.min.js` | 3.14.8 | MIT |
| `fonts/archivo-*.woff2` | Archivo (Google Fonts), variabel | v25 | SIL Open Font License 1.1 |
| `fonts/publicsans-*.woff2` | Public Sans (Google Fonts), variabel | v21 | SIL Open Font License 1.1 |
| `fonts/jetbrainsmono-*.woff2` | JetBrains Mono (Google Fonts), variabel | v24 | SIL Open Font License 1.1 |

Nur die Subsets `latin` und `latin-ext` sind eingebunden.
