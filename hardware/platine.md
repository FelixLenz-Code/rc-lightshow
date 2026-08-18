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
