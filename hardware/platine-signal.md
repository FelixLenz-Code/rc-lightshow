# Bordplatine · Variante B — nur Signale

Die Platine steuert, sie schaltet nicht. Zwei WS2812-Strips und zwei
**Schaltausgänge mit 5-V-Logik**, an die extern hängt, was tatsächlich schaltet:
ein fertiges Relaismodul, ein kleines MOSFET-Platinchen, ein Halbleiterrelais.

Der Unterschied zu [Variante A](platine-mosfet.md) ist nicht die Funktion,
sondern der Strom: **hier fließt nirgends mehr als etwa 250 mA.** Damit sind
alle Bahnen 0,25 mm, es gibt keinen Lastpfad, keinen Sternpunkt für Ampere und
keine drei Schraubklemmen für die Lastseite. Die Platine wird deutlich kleiner —
das war der Grund für diese Variante.

Schaltplan: [`schaltplan-signal.svg`](schaltplan-signal.svg), erzeugt von
`schaltplan_signal.py`.

## Die Ausgänge liefern 5 V, nicht 3,3 V

Der SN74AHCT125N hat vier Treiber. Zwei heben die WS2812-Daten von 3,3 V auf
5 V; die anderen beiden lagen in Variante A brach auf Masse. Hier machen sie
dasselbe für die Schaltsignale.

Das kostet **kein einziges zusätzliches Bauteil** und nimmt der Ausgangsseite
jede Pegelfrage: 5-V-Logik nimmt jedes Relaismodul an, und ein Logic-Level-FET
bekommt volle Gate-Spannung statt knapper 3,3 V.

Grenze: der Treiber liefert **8 mA je Ausgang**. Für einen Optokoppler-Eingang
oder ein Gate reicht das mit Abstand; ein Modul, das mehr zieht, gehört nicht
direkt an diesen Pin.

## Was an J5 und J6 gehört

| Pin | Netz | |
|-----|------|---|
| 1 | `GND` | gemeinsame Masse — zwingend, sonst hat das Signal keinen Bezug |
| 2 | `+5V` | Versorgung für die Logikseite des Moduls |
| 3 | `SIG` | 5-V-Schaltsignal über 100 Ω |

Das ist die übliche Dreierbelegung, ein Modulkabel passt direkt.

**Relaismodul.** Braucht alle drei Pins. Die meisten sind **active low** —
sie ziehen an, wenn der Eingang auf Masse geht. Dafür gibt es in der
Konfiguration `active_low: true` je Relais; die Firmware dreht das Signal dann
um. Der Freilauf für die Spule sitzt auf dem Modul.

**MOSFET-Platinchen.** Braucht nur Pin 1 und 3. Freilaufdiode gehört dorthin,
nicht hierher.

**Halbleiterrelais.** Wie das Relaismodul, aber ohne Freilaufproblem.

> **Die Last darf niemals über diese Platine laufen.** Ihre Versorgung kommt
> direkt vom Akku oder vom UBEC zum Modul, nur die drei dünnen Adern gehen
> hierher. Wer das Lastplus über J5 Pin 2 zieht, schickt Ampere durch eine
> 0,25-mm-Bahn.

## Netzliste

| Netz | Angeschlossen an |
|------|------------------|
| `+5V` | J1.1 · C1.1 · U1.39 (VSYS) · U2.14 · J5.2 · J6.2 |
| `GND` | J1.2 · C1.2 · C2.2 · U1.3 · U1.8 · U1.13 · U1.18 · U1.38 · U2.1 · U2.4 · U2.7 · U2.10 · U2.13 · J2.2 · J3.2 · J4.1 · J5.1 · J6.1 · J7.3 · R3.2 · R4.2 |
| `DATA1` | U1.4 (GP2) · U2.2 |
| `DATA1_5V` | U2.3 · R1.1 |
| `STRIP1_DIN` | R1.2 · J2.1 |
| `DATA2` | U1.5 (GP3) · U2.5 |
| `DATA2_5V` | U2.6 · R2.1 |
| `STRIP2_DIN` | R2.2 · J3.1 |
| `REL1` | U1.9 (GP6) · U2.9 (3A) · R3.1 |
| `OUT1` | U2.8 (3Y) · R5.1 |
| `OUT1_SIG` | R5.2 · J5.3 |
| `REL2` | U1.10 (GP7) · U2.12 (4A) · R4.1 |
| `OUT2` | U2.11 (4Y) · R6.1 |
| `OUT2_SIG` | R6.2 · J6.3 |
| `SBUS_IN` | J4.3 · R7.1 |
| `SBUS` | R7.2 · U1.7 (GP5) |
| `UART_TX` | U1.1 (GP0) · J7.1 |
| `UART_RX_IN` | J7.2 · R8.1 |
| `UART_RX` | R8.2 · U1.2 (GP1) |

J4 Pin 2 ist unbeschaltet. **U1.40 (VBUS) bleibt frei.**

## Stückliste

| Ref | Bauteil | Package | Anmerkung |
|-----|---------|---------|-----------|
| U1 | Raspberry Pi Pico | 2 × Buchsenleiste 20-pol, RM 2,54, Reihenabstand 17,78 mm | steckbar |
| U2 | SN74AHCT125N | DIP-14 | **HCT**, nicht AHC |
| R1, R2 | 330 Ω | 0805 | Serienwiderstand Datenleitung |
| R3, R4 | 100 kΩ | 0805 | Pulldown am Treibereingang |
| R5, R6 | 100 Ω | 0805 | Serienwiderstand Schaltausgang |
| R7, R8 | 1 kΩ | 0805 | Strombegrenzung SBUS und Konsolen-RX |
| C1 | 10 µF MLCC, X7R/X5R | 0805 | Eingangspuffer an J1 |
| C2 | 100 nF X7R | 0805 | Abblockung U2, an Pin 14/7 |
| J1 | Schraubklemme 2-pol | RM 5,08 mm | Versorgung der Platine |
| J2, J3 | JST-XH 2-pol | RM 2,50 mm | nur DIN und Signalmasse |
| J4, J7 | Stiftleiste 3-pol | RM 2,54 mm | SBUS, Konsole |
| J5, J6 | Stiftleiste 3-pol | RM 2,54 mm | Schaltausgänge |

Gegenüber Variante A entfallen: drei Schraubklemmen, zwei MOSFETs, zwei
Schottkydioden. Dazu kommen zwei Stiftleisten. Unter dem Strich **rund 30 × 10 mm
weniger Fläche** und keine dicken Bahnen mehr.

## Strombudget an J1

| Verbraucher | Strom |
|---|---|
| Pico (Pico W etwas mehr) | ~50 mA |
| SN74AHCT125N | wenige mA |
| Zwei Relaismodule, angezogen | ~160 mA |
| **Summe** | **~250 mA** |

Eine 0,25-mm-Bahn trägt rund 900 mA. Es bleibt also auch mit zwei angezogenen
Relais reichlich Reserve, und alle Bahnen dürfen dieselbe Breite haben.

Wenn du Module ohne Optokoppler mit größerem Eingangsstrom benutzt, rechne
nach — nicht wegen der Bahn, sondern wegen der 8 mA je Treiberausgang.

## Firmware

**Unverändert.** Die Firmware treibt einen GPIO; was daran hängt, ist Sache der
Platine. Die Relaiseinträge bleiben wie sie sind:

```yaml
relays:
  - name: last1
    pin: 6
    source: pixel
    arg: 0
  - name: last2
    pin: 7
    source: brightness
    threshold: 64
    active_low: true    # fertige Relaismodule schalten meist so
```

`active_low` gab es schon vorher — in `config.py` mit dem Kommentar, dass die
meisten fertigen Relaisplatinen so arbeiten. Für ein MOSFET-Platinchen bleibt
es aus.

`min_on_ms` und `min_off_ms` sind bei mechanischen Relais weiterhin sinnvoll,
damit sich ein Relais nicht an einem Strobe zerlegt.

## Layout

Zweilagig, 1,6 mm, 35 µm. **Alle Bahnen 0,25 mm** — es gibt keinen Pfad, der
mehr trägt. GND als Fläche auf der Unterseite, dann bleibt die Oberseite fast
leer.

Der Sternpunkt liegt am UBEC, außerhalb der Platine: Streifen, Schaltmodule und
Platine bekommen jeweils eine eigene Ader dorthin.

Es bleiben die Regeln, die nichts mit Strom zu tun haben:

- **DIN und Signalmasse als Paar** zum Streifen führen, R1/R2 an die
  U2-Ausgänge setzen, nicht an J2/J3.
- **Signalmasse zu J2/J3 dünn halten**, damit sie keinen LED-Strom abzweigt.
- **U2 dicht an den Pico**, C2 wenige Millimeter an Pin 14 und 7.
- **Die Gate-Leitungen zu J5/J6 nicht neben dem Motorkabel verlegen.** Sie sind
  jetzt lange Signalleitungen — das ist der Preis dieser Variante.
