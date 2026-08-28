# ADR 0007 — Atlas: Pool anonym über eigene Datensätze, PLZ-Daten aus offenen Quellen

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Atlas ist das einzige Modul mit einem mandantenübergreifenden Feature. Zugleich
ist genau dort der gefährlichste Fehler der Plattform möglich: ein Büro, das
sieht, welcher Kollege eine Erhebung eingetragen hat. Das Briefing sagt dazu:
im Pool sichtbar sind Betrieb, Anschrift, Sätze, Erhebungsdatum und Nachweisart
— **nicht**, wer erfasst hat, nicht die Nachweisdokumente, nicht der Fallbezug.

## Entscheidung Pool

`atlas/pool.py` gibt **niemals** ein ORM-Objekt heraus, sondern ausschließlich
`PoolErhebung` — einen `slots`-Datensatz, der schlicht kein Feld für die
Mandantenkennung besitzt. Es gibt damit keinen Pfad, über den sie hinausgelangen
könnte, auch nicht durch ein späteres Versehen in einer Vorlage oder einem
JSON-Export.

Der Test dazu prüft nicht eine Beispielausgabe, sondern die Struktur: keines der
`__slots__` enthält „mandant" oder „nachweis". Ein neues Feld, das die Herkunft
verriete, fällt damit beim ersten Testlauf auf.

Ob der Pool überhaupt angeboten wird, entscheidet der Betreiber über
`ATLAS_POOL_FREIGEGEBEN`; die Voreinstellung ist **an**, weil das Register der
Stundenverrechnungssätze das gemeinsame Feature der Plattform ist. Ist der
Schalter aus, ist Atlas ein reines Einzelplatz-Register — auch das ist
verkaufbar, und das Briefing sieht diesen Start ausdrücklich als Möglichkeit vor.

Die wettbewerbsrechtliche Prüfung aus Querschnitt 6.7 bleibt davon unberührt und
ist **nicht erledigt**. Sie steht als offener Punkt in `docs/BETRIEB.md` und im
Modulkopf. Die Konstruktion ist danach tragfähig, weil Preise Dritter erhoben
werden und nicht die Honorare der Teilnehmer — geprüft ist sie nicht.

## Entscheidung PLZ-Mittelpunkte

Das Briefing nennt eine PLZ-Mittelpunkttabelle aus OpenStreetMap-Daten. Die
Bauumgebung hat keinen Zugang zu OSM oder GeoNames. Gebaut wurde die Tabelle
deshalb aus zwei über die Paketregister erreichbaren offenen Quellen:
PLZ → Ortsname und Ortsname → Koordinate.

Ergebnis: 8.168 Postleitzahlen, davon 7.189 mit Gemeindemittelpunkt und 979 als
Median ihrer Leitregion. Die Genauigkeit steht als Spalte in der Datei, wird in
`daten/HERKUNFT.md` beziffert, und die Auswertung **weist in der Anlage aus**,
wenn ihr Zentrum nur auf Leitregionsebene bekannt ist.

Das ist bewusst keine stille Näherung: eine ungenannte Ungenauigkeit in einer
Gutachtenanlage wäre der schlechtere Fehler. Vor dem Produktivgang ist die
Tabelle über `skripte/plz_tabelle_bauen.py` durch amtliche Mittelpunkte zu
ersetzen — ein Dateitausch, kein Codeeingriff.

## Folgen

- Die Haversine-Rechnung ist gegen bekannte Entfernungen getestet und bleibt
  unter zwei Kilometern Abweichung; die verbleibende Unschärfe stammt aus der
  Tabelle, nicht aus der Rechnung. Beide Fehlerquellen sind getrennt benannt.
- Der Pool lässt sich freischalten, ohne dass an der Anonymisierung etwas zu
  ändern wäre.
