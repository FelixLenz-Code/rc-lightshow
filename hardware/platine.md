# Bordplatine — zwei Varianten

Beide steuern dasselbe: zwei WS2812-Strips und zwei geschaltete Ausgänge, Pico
gesockelt, SBUS vom Empfänger. Sie unterscheiden sich darin, **wo der Laststrom
fließt**.

| | [A · mit MOSFET](platine-mosfet.md) | [B · nur Signale](platine-signal.md) |
|---|---|---|
| Schaltet | die Platine selbst | ein externes Modul |
| Laststrom | über die Platine | nie über die Platine |
| Bahnbreiten | 0,25 / 2 / 3 mm | durchgehend 0,25 mm |
| Klemmen für die Last | drei | keine |
| Freilaufdiode | an Bord | am Modul |
| Geschätzte Größe | ~60 × 50 mm | deutlich kleiner |
| Zusätzliche Teile außerhalb | keine | ein Modul je Kanal |

**Variante A** ist die vollständige Lösung: Akku an die Klemme, Verbraucher an
die Klemme, fertig. Der Preis ist dickes Kupfer im Layout — und genau daran
scheitert es, wenn die Platine in ein kleines Modell soll.

**Variante B** verschiebt das Schalten nach außen. Die Platine gibt nur ein
5-V-Signal aus; was schaltet, sitzt beim Verbraucher. Damit trägt keine Bahn
mehr als 250 mA, alles wird 0,25 mm breit, und drei Schraubklemmen entfallen.
Der Preis: ein kleines Modul je Kanal und eine Signalleitung dorthin, die man
nicht neben das Motorkabel legen sollte.

Beide Varianten laufen mit **derselben Firmware und derselben Konfiguration** —
die Firmware treibt einen GPIO, was daran hängt, ist Sache der Platine. Für
fertige Relaismodule setzt man `active_low: true`.

Die allgemeine Verdrahtung — Pegelwandler, Massepunkte, Strombudget der
Streifen — steht unabhängig davon in [`README.md`](README.md).

## Die Platine in der Konfiguration

Eine gefertigte Platine bekommt einen Namen, den `plane.board` trägt:

| `board` | Was es heißt |
|---|---|
| `modell-2led-2relais-v1` | RC-Lightshow Modell-2LED-2Relais-v1: LED auf GP2/GP3, geschaltet auf GP6/GP7, SBUS auf GP5 |
| `pico` | frei verdrahtet, jeder GPIO steht zur Wahl |

Der Schlüssel nennt die Bestückung, nicht bloß eine Versionsnummer — bei mehreren
Platinen wäre `modell-v1` sonst nicht mehr eindeutig.

Das ist keine Beschriftung, sondern eine Prüfung: wer eine Platine nennt und
dann einen Streifen auf GP9 legt, bekommt eine Fehlermeldung — der Anschluss
existiert dort nicht. Im Wizard ist die Platine der **erste** Schritt, und die
Auswahl füllt SBUS-Pin, LED-Ausgänge und Relais-Pins gleich mit aus.

Welcher Verbraucher an welchem der beiden geschalteten Ausgänge hängt, bleibt
frei — das entscheidet der Lötkolben, nicht die Platine.

Eine weitere Platine ist **eine Zeile** in `BOARDS`
(`host/lightshow/config.py`). Von dort geht sie über `/api/config` in den
Wizard, prüft die Konfiguration und füllt die Felder aus — die Pins stehen nur
an dieser einen Stelle. Ein Foto und ein erklärender Satz kommen optional in
`WIZ_BOARD_ART` (`host/lightshow/web/wizard.js`) dazu; ohne das zeigt die Karte
die Pins als Text.
