# PLZ-Mittelpunkttabelle — Herkunft und Genauigkeit

`plz_mittelpunkte.csv` enthält 8.168 deutsche Postleitzahlen mit einem
Mittelpunkt. Die Tabelle wurde aus zwei offenen Quellen zusammengesetzt
(`skripte/plz_tabelle_bauen.py`):

| Quelle | Inhalt | Lizenz |
|---|---|---|
| npm `postleitzahlen@1.0.0` | PLZ → Ortsname (8.171 PLZ) | offen, ohne Lizenzangabe im Paket |
| npm `all-the-cities@3.1.0` | Ortsname → Koordinate, Einwohnerzahl (GeoNames) | MIT, Daten CC-BY 4.0 (GeoNames) |

## Genauigkeit — bitte vor dem Produktivgang lesen

Die Spalte `genauigkeit` sagt, wie der Punkt zustande kam:

- **`ort`** (7.189 PLZ): Mittelpunkt der Gemeinde, der diese PLZ zugeordnet ist.
  In Flächengemeinden und Großstädten teilen sich viele PLZ denselben Punkt —
  alle Berliner PLZ liegen auf dem Stadtmittelpunkt. Für eine Umkreissuche mit
  20 bis 50 km Radius ist das brauchbar, für eine Aussage „5 km um 10115" nicht.
- **`leitregion`** (979 PLZ): der Ort war in der Koordinatenquelle nicht
  enthalten (Gemeinden unter 1.000 Einwohnern). Verwendet wird der Median der
  Punkte derselben Leitregion (erste zwei Ziffern). Das ist eine grobe
  Näherung; Abweichungen von 20 km und mehr sind möglich.

**Vor dem Produktivgang zu ersetzen** durch echte PLZ-Gebietsmittelpunkte aus
OpenStreetMap oder dem GeoNames-Postleitzahlenexport. Die Anwendung liest
ausschließlich diese CSV; ein Austausch ist ein Dateitausch, kein Codeeingriff.
Das Format ist `plz,ort,lat,lon,genauigkeit`.

Die Oberfläche weist bei einer Auswertung, deren Zentrum nur auf Leitregions-
genauigkeit liegt, ausdrücklich darauf hin — eine stille Ungenauigkeit wäre in
einer Gutachtenanlage der schlechtere Fehler.
