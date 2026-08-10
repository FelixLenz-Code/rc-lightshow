# Hardware

## Bodenseite: Signalgenerator

Raspberry Pi Pico (RP2040). Acht Ausgänge, jeder unabhängig als PPM oder SBUS
konfigurierbar.

| Pico-Pin | GPIO | Funktion            |
|----------|------|---------------------|
| 4        | 2    | Ausgang Port 0      |
| 5        | 3    | Ausgang Port 1      |
| 6        | 4    | Ausgang Port 2      |
| 7        | 5    | Ausgang Port 3      |
| 9        | 6    | Ausgang Port 4      |
| 10       | 7    | Ausgang Port 5      |
| 11       | 8    | Ausgang Port 6      |
| 12       | 9    | Ausgang Port 7      |
| 14       | 10   | Selbsttest-Eingang  |
| 3/8/13…  | GND  | gemeinsame Masse    |
| —        | 25   | Status-LED (onboard)|

GPIO10 ist ein reiner Messeingang. Ein Jumperkabel von einem Ausgang dorthin,
und die Firmware analysiert ihr eigenes Signal — Ruhepegel, Pulsbreite,
Framelänge und alle Kanalwerte erscheinen im Statusstrom. Ersetzt beim
Inbetriebnehmen das Oszilloskop.

Die `id` in `show.yaml` ist die Portnummer: `id: 0` → GPIO2.

Status-LED: leuchtet dauerhaft, solange der Host Frames schickt; blinkt langsam,
sobald die Verbindung weg ist.

### Ausgangsstufe je Port

```
GPIO ──[ 1k ]──┬── Tip (3,5-mm-Klinke)
               │
GND ───────────┴── Sleeve
```

Der 1-kΩ-Widerstand schützt den Pico, falls die Buchse selbst treibt. Masse muss
gemeinsam sein, sonst sieht der Sender nur Rauschen.

**Ring der Klinke offen lassen.** Manche Sender führen dort Akkuspannung.

### 5 V und Polarität

Die meisten Sender kommen mit den 3,3 V des Pico direkt zurecht. Braucht ein
Sender echte 5 V, kommt ein **74HCT14** (Hex-Schmitt-Inverter, 5-V-Versorgung
aus VBUS) dazwischen — HCT-Eingänge erkennen 3,3-V-Pegel zuverlässig:

- **invertiert, 5 V:** ein Gatter
- **nicht invertiert, 5 V:** zwei Gatter in Reihe

Ein Jumper je Port wählt zwischen beiden Abgriffen. Die logische Polarität lässt
sich zusätzlich in der Software umschalten (`polarity: normal | inverted`), also
zuerst dort probieren.

### Störungen

Acht Sender und ein PC an einer gemeinsamen Masse können brummen. Erst
Sternmasse am Pico probieren; hilft das nicht, USB-Isolator zwischen PC und Pico
oder Optokoppler (6N137) je Ausgang.

### Stückliste Bodenseite

| Teil                          | Menge | ca. Preis |
|-------------------------------|-------|-----------|
| Raspberry Pi Pico             | 1     | 5 €       |
| 74HCT14 (nur bei 5-V-Sendern) | 1     | 0,50 €    |
| Widerstand 1 kΩ               | 8     | —         |
| 3,5-mm-Klinkenstecker + Kabel | 8     | 8 €       |
| Lochrasterplatine, Gehäuse    | 1     | 5 €       |

---

## Bordseite: Lichtcontroller

**Raspberry Pi Pico** (51 × 21 mm, ~3 g ohne Stiftleisten). Dasselbe Board wie
am Boden — ein Ersatzteil für beide Seiten, ein Bauteil zum Nachbestellen.
Belegung in `firmware/plane/src/config.h`, Board-Definition als Default in der
`CMakeLists.txt`.

Der RP2040 ist hier die richtige Wahl, weil PIO das WS2812-Timing in Hardware
erzeugt — die Effektberechnung kann also beliebig lange dauern, ohne dass Pixel
flackern — und weil der UART 100 kBaud 8E2 nativ kann: SBUS braucht damit nur
`gpio_set_inover()` statt eines Invertertransistors.

Wird es im Rumpf eng oder zählt jedes Gramm, passt derselbe Code ohne Änderung
auf einen **Waveshare RP2040-Zero** (2,4 g, 23,5 × 18 mm) — alle belegten Pins
liegen dort auf den Castellated Pads:

```bash
cmake -S firmware/plane -B build/plane -DPICO_BOARD=waveshare_rp2040_zero
```

### Stromversorgung

Der Pico wird über **VSYS (Pin 39)** und GND (Pin 38) vom UBEC versorgt, nicht
über VBUS. VSYS nimmt 1,8–5,5 V, und die interne Schottky-Diode sorgt dafür,
dass ein gleichzeitig gestecktes USB-Kabel nichts kaputt macht — praktisch beim
Einrichten am Schreibtisch.

Der LED-Streifen bekommt seine 5 V **direkt vom UBEC**, nicht über den Pico.

| GPIO   | Funktion                                    |
|--------|---------------------------------------------|
| 0 / 1  | Debug-UART (Konsolenausgabe)                |
| 2, 3   | WS2812-Daten, ein Pin je Strip              |
| 5      | SBUS vom Empfänger (UART1 RX, invertiert)   |
| 6, 7   | Relais-Ausgänge                             |
| 10–13  | PWM-Eingänge, Fallback ohne SBUS            |
| 39/38  | VSYS / GND vom UBEC                         |

Das ist die Vorgabe in `config.h`. Strips, Relais und Zonen stehen dort als
Tabellen — bis zu 8 Strips (je eine PIO-State-Machine) und 8 Relais, jedes
Modell so, wie es gebraucht wird.

SBUS wird bevorzugt: eine Leitung statt vier, und alle Kanäle des Empfängers
stehen zur Verfügung — genug für ein Modell mit mehreren Zonen, die je vier
Kanäle brauchen. Die PWM-Eingänge werden nur benutzt, wenn keine SBUS-Frames
ankommen; beides ist gleichzeitig aktiv, ein Umschalter entfällt.

### WS2812-Beschaltung

```
GPIO2 ──▶ 74AHCT125 ──[ 330R ]──▶ DIN Strip 1
GPIO3 ──▶ 74AHCT125 ──[ 330R ]──▶ DIN Strip 2
5V ──┬── LED-Streifen +5V
     └── 1000 µF ── GND
```

Der Pegelwandler ist nicht optional: 3,3 V Datenpegel an einem 5-V-Streifen
läuft mal und setzt mal aus, gern erst in der Luft. Der 330-Ω-Widerstand
schützt die erste LED, der Elko fängt Einschaltspitzen ab.

Ein 74AHCT125 enthält vier Treiber, versorgt aus 5 V — er reicht also für vier
Strips.

### Relais-Ausgänge

Ein GPIO kann **kein** Relais direkt treiben: 3,3 V bei wenigen Milliampere
gegen eine Spule, die 5 V und 70 mA will. Es braucht immer eine Treiberstufe.

**MOSFET** — die Wahl für alles, was im Takt schaltet:

```
GPIO ──[ 100R ]──┬── Gate   IRLML2502 / AO3400 (Logic Level!)
                 │
             [ 100k ]
                 │
GND ─────────────┴── Source        Drain ──▶ Last ──▶ +V
```

Der 100-kΩ-Widerstand zieht das Gate beim Booten sicher auf Masse, solange der
Pin noch hochohmig ist. „Logic Level" ist zwingend: ein normaler MOSFET
schaltet bei 3,3 V Gate-Spannung nicht durch, sondern wird heiß. Für induktive
Lasten zusätzlich eine Freilaufdiode über die Last.

**Fertiges Relaismodul** — direkt an den GPIO, aber `active_low: true` in
`config.h` setzen: die üblichen optogekoppelten Module schalten bei Low ein.
Versorgung des Moduls aus 5 V, **nicht** aus dem 3,3-V-Pin des Pico.

| | MOSFET | Relaismodul |
|---|---|---|
| Gewicht je Kanal | ~1 g | 10–15 g |
| Schaltzeit | µs | 5–10 ms |
| Blitzen möglich | ja | nein |
| Geräusch | keins | klackert |
| Lebensdauer | praktisch unbegrenzt | einige 100 000 Schaltspiele |
| Potentialfrei | nein | ja |

Wenn du beides mischst, setz bei den mechanischen Kanälen
`min_on_ms`/`min_off_ms` auf etwa 200. Das Relais folgt dann demselben Effekt,
schaltet aber nur so oft, wie es verträgt — statt sich an einem Strobe zu
zerlegen.

### Strombudget

WS2812 ziehen bis **60 mA je LED** bei Weiß auf voller Helligkeit.

| LEDs | Worst Case (Weiß) | typische Farbe, `MAX_BRIGHTNESS 200` |
|------|-------------------|--------------------------------------|
| 30   | 1,8 A             | ~0,5 A                               |
| 60   | 3,6 A             | ~1,0 A                               |
| 120  | 7,2 A             | ~2,0 A                               |

Nicht am Empfänger-BEC anschließen. Eigenes UBEC (5 V / 3 A) direkt am
Flugakku, Zuleitung mindestens 0,5 mm². `MAX_BRIGHTNESS` in `config.h` begrenzt
den Spitzenstrom und gleichzeitig die Blendwirkung für den Piloten.

### Stückliste je Modell

| Teil                              | Menge     | ca. Preis |
|-----------------------------------|-----------|-----------|
| Raspberry Pi Pico                 | 1         | 5 €       |
| 74AHCT125 (4 Strips je Baustein)  | 1         | 0,50 €    |
| WS2812-Streifen 60 LED            | 1–8       | 10 €      |
| UBEC 5 V / 3 A                    | 1         | 6 €       |
| 1000 µF / 10 V, 330 Ω je Strip    | 1         | —         |
| IRLML2502 + 100 R + 100 k je MOSFET-Kanal | 0–8 | 0,30 €    |
| Relaismodul je mechanischem Kanal | 0–8       | 2 €       |

Beim Strombudget die Relais-Lasten nicht vergessen: ein Landescheinwerfer zieht
schnell mehr als der ganze LED-Streifen. Die geschalteten Lasten hängen direkt
am Akku oder an einem eigenen UBEC, nicht am 5-V-Zweig des Controllers.
