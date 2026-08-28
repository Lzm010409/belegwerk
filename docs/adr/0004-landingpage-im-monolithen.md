# ADR 0004 — Landingpages im Anwendungscontainer statt als Astro-Site

**Status:** entschieden · **Datum:** 2026-08-28

## Kontext

Die Plattformdatei sieht für die Landingpages eine statisch gebaute Astro-Site
in einem eigenen Coolify-Container vor.

## Entscheidung

Die vier öffentlichen Seiten (Start plus drei Produktseiten) und die Rechtstexte
werden von derselben FastAPI-Anwendung als Jinja-Vorlagen ausgeliefert, mit
demselben Stylesheet und denselben Tokens.

## Begründung

Zwei der drei geforderten Hero-Elemente sind gar nicht statisch:

- Atlas verlangt ausdrücklich Live-Zahlen aus der Datenbank („eine geschönte
  Zahl auf dieser Seite zerstört genau das Vertrauen, das das Produkt verkauft").
- Check verlangt eine funktionierende Dropzone, die tatsächlich prüft.

Beide bräuchten aus einer statischen Site heraus ohnehin Endpunkte der
Hauptanwendung. Eine zweite Toolchain (Node, Astro), ein zweites Image und ein
zweiter Container für vier Seiten, von denen zwei dynamisch sind, ist Aufwand
ohne Gegenwert. Der Delta-Hero (scrollende Delta-Tabelle) funktioniert
serverseitig gerendert genauso.

## Folgen

- Eine Ressource weniger im Betrieb, ein gemeinsames Stylesheet, kein
  Auseinanderdriften der Gestaltung zwischen Marketing und Anwendung.
- Die öffentlichen Seiten werden aggressiv zwischengespeichert (`Cache-Control`),
  damit die Ladezeitvorgabe unter einer Sekunde erreichbar bleibt.
- Die geforderte Trennung „Oberfläche und Datenbank" im Betrieb bleibt
  unberührt: das sind weiterhin zwei getrennte Coolify-Ressourcen.
