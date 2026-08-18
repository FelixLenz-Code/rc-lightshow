# Bordplatine

Die kleine Variante: **zwei WS2812-Strips, zwei geschaltete Ausgänge, Pico
gesockelt**. Sie entspricht dem Beispiel in `firmware/plane/src/config.h` —
Strips auf GPIO 2 und 3, Relais auf GPIO 6 und 7 — und belegt sonst nur, was
`docs`/`hardware/README.md` ohnehin als Pinbelegung festlegt.

Der Schaltplan liegt als [`schaltplan.svg`](schaltplan.svg) daneben und wird von
`schaltplan.py` erzeugt:

```
python3 hardware/schaltplan.py
```

Netznamen im Bild und in der Netzliste hier sind dieselben. Wer eines ändert,
ändert beides.

## Netzliste

Pinnummern sind die physischen Pins des jeweiligen Bauteils, beim Pico also die
Nummern auf dem Board, nicht die GPIO-Nummern.

| Netz | Angeschlossen an |
|------|------------------|
| `+5V` | J1.1 · C1.1 · C3.1 · JP1.1 · JP2.1 · U1.39 (VSYS) · U2.14 · J2.1 · J3.1 |
| `+5V_RC` | JP1.2 · J4.2 |
| `GND` | J1.2 · C1.2 · C2.2 · C3.2 · U1.3 · U1.8 · U1.13 · U1.18 · U1.38 · U2.1 · U2.4 · U2.7 · U2.9 · U2.10 · U2.12 · U2.13 · J2.3 · J3.3 · J4.1 · J5.2 · J9.3 · Q1.S · Q2.S · R4.2 · R6.2 |
| `DATA1` | U1.4 (GP2) · U2.2 |
| `DATA1_5V` | U2.3 · R1.1 |
| `STRIP1_DIN` | R1.2 · J2.2 |
| `DATA2` | U1.5 (GP3) · U2.5 |
| `DATA2_5V` | U2.6 · R2.1 |
| `STRIP2_DIN` | R2.2 · J3.2 |
| `REL1` | U1.9 (GP6) · R3.1 |
| `GATE1` | R3.2 · R4.1 · Q1.G |
| `LOAD1` | Q1.D · D1.A · J6.2 |
| `REL2` | U1.10 (GP7) · R5.1 |
| `GATE2` | R5.2 · R6.1 · Q2.G |
| `LOAD2` | Q2.D · D2.A · J7.2 |
| `+VL` | JP2.2 · D1.K · D2.K · J6.1 · J7.1 |
| `VL_J5` | J5.1 · JP2.3 |
| `SBUS_IN` | J4.3 · R7.1 |
| `SBUS` | R7.2 · U1.7 (GP5) |
| `PWM1_IN` … `PWM4_IN` | J8.1 · R8.1 … J8.4 · R11.1 |
| `PWM1` … `PWM4` | R8.2 · U1.14 … R11.2 · U1.17 (GP10–GP13) |
| `UART_TX` | U1.1 (GP0) · J9.1 |
| `UART_RX` | U1.2 (GP1) · J9.2 |

Die übrigen Massepins des Pico (23, 28, 33) dürfen mit an `GND`, müssen aber
nicht — fünf Verbindungen reichen. **U1.40 (VBUS) bleibt frei.** Wer dort das
UBEC anschließt, speist an der USB-Schutzdiode vorbei ein.

## Gegengeprüft

Die Belegung — Strips auf GPIO 2/3, Lasten auf 6/7, SBUS auf 5, PWM auf 10–13 —
läuft ohne Beanstandung durch `config._parse_plane()`: kein Pin doppelt belegt,
SBUS auf einer UART1-RX-Leitung, GPIO 0/1 für die Konsole frei. Eine Platine,
die diese Netzliste umsetzt, kann also keine Konfiguration erzwingen, die die
Web-UI später ablehnt.

`planegen.power_estimate()` sagt für 2 × 30 LEDs **3,6 A worst case** und
**0,94 A typisch** bei `MAX_BRIGHTNESS 200` — daher die 2,5 mm unten.

## Stückliste

| Ref | Bauteil | Package | Anmerkung |
|-----|---------|---------|-----------|
| U1 | Raspberry Pi Pico | 2 × Buchsenleiste 20-pol, RM 2,54, Reihenabstand 17,78 mm | steckbar, nicht löten |
| U2 | SN74AHCT125N | DIP-14 | **HCT**, nicht AHC. Sockel empfohlen |
| Q1, Q2 | AO3400A | SOT-23 | 30 V / 5,7 A, Logic Level |
| D1, D2 | SS14 | SMA | nur bei induktiver Last bestücken |
| R1, R2 | 330 Ω | 0805 | Serienwiderstand Datenleitung |
| R3, R5 | 100 Ω | 0805 | Gate-Vorwiderstand |
| R4, R6 | 100 kΩ | 0805 | Gate-Pulldown, hält den FET beim Booten aus |
| R7–R11 | 1 kΩ | 0805 | Strombegrenzung RC-Eingänge |
| C1 | 1000 µF / 16 V | Elko radial, RM 5 mm | Einschaltspitze der Strips |
| C2, C3 | 100 nF X7R | 0805 | Abblockung U2 und VSYS |
| J1, J5, J6, J7 | Schraubklemme 2-pol | RM 5,08 mm | Versorgung und Lasten |
| J2, J3 | JST-XH 3-pol | RM 2,50 mm | LED-Strips |
| J4, J9 | Stiftleiste 3-pol | RM 2,54 mm | SBUS, Konsole |
| J8 | Stiftleiste 4-pol | RM 2,54 mm | PWM-Signale |
| JP1 | Lötbrücke | — | 5 V an den Empfänger |
| JP2 | Stiftleiste 3-pol + Shunt | RM 2,54 mm | wählt die Quelle für `+VL` |

**LCSC-Nummern habe ich bewusst nicht eingetragen.** Sie hängen am
Lagerbestand, und eine erfundene C-Nummer kostet dich eine Bestellrunde. Die
Bauteile hier sind alle Standard und in EasyEDA über den Namen zu finden;
AO3400A und SS14 sind bei JLCPCB üblicherweise Basic Parts, der SN74AHCT125N
als DIP nicht.

Bestückung von Hand ist der realistische Weg: Pico, U2, Klemmen und Leisten sind
durchkontaktiert, und JLCPCB berechnet THT gesondert. 0805 und SOT-23 lassen
sich problemlos mit dem Kolben setzen.

## Layout

Zweilagig, 1,6 mm, 35 µm Kupfer reicht. Geschätzte Größe rund **70 × 60 mm**,
im Wesentlichen bestimmt vom Pico (21 × 51 mm) und den vier Schraubklemmen.

**Die Masse ist ein Stern.** Streifenmasse, Lastmasse und Controllermasse
treffen sich am UBEC-Anschluss, nicht in Reihe. Wenn der LED-Strom durch die
Massefläche unter dem Pico läuft, hebt jede Helligkeitsänderung dessen
Bezugspotential an — und der SBUS-Eingang liest daneben.

**Bahnbreiten** bei 35 µm und 10 K Erwärmung:

| Netz | Strom | Breite |
|------|-------|--------|
| `+5V`, `GND` zum Streifen | bis 3,6 A | ≥ 2,5 mm oder Fläche |
| `+VL`, `LOAD1/2` | nach Last | Faustregel 1 mm je 1,5 A |
| Signale | µA | 0,25 mm |

**C1 gehört ans Ende der 5-V-Bahn**, dicht an J2/J3 — dort entsteht die
Einschaltspitze, und nur dort nützt er etwas. C2 direkt an U2 Pin 14 und 7,
nicht am Platinenrand.

**Die 3,3-V-Seite kurz halten.** U2 so dicht an den Pico wie möglich; die
5-V-Seite hinter den 330 Ω darf lang sein, die ungepufferte Seite davor nicht.
R1 und R2 sitzen am U2-Ausgang, nicht am Streifenstecker — sie sollen die
Flanke dort dämpfen, wo sie entsteht.

**Der Lastpfad bleibt getrennt.** J5 → Q1/Q2 → J6/J7 als eigene Bahnen führen
und erst am Sternpunkt auf die Signalmasse treffen lassen. Ein Landescheinwerfer
zieht mehr als der ganze Streifen.

## Die zwei Spannungen

Auf der Platine liegen **zwei getrennte Versorgungen**, die sich nur die Masse
teilen:

`+5V` kommt vom UBEC an J1 und versorgt genau vier Verbraucher — Pico (VSYS),
Pegelwandler, und die beiden Streifenstecker. Mehr hängt dort nicht.

`+VL` versorgt ausschließlich die geschalteten Lasten und kommt über JP2
entweder von J5 — direkt vom Flugakku oder von einem zweiten UBEC — oder aus
dem 5-V-Netz. So steht es in
`hardware/README.md`: die Lasten gehören nicht an den 5-V-Zweig, weil ein
Landescheinwerfer mehr zieht als der ganze Streifen.

**JP2 wählt aus, woher `+VL` kommt.** Ein dreipoliger Jumper, Pin 2 in der
Mitte ist der gemeinsame Anschluss:

| Shunt | `+VL` liegt auf | Anwendung |
|-------|-----------------|-----------|
| 1–2 | `+5V` | 5-V-Lasten aus dem UBEC, J5 bleibt leer |
| 2–3 | `VL_J5` | alles andere, J5 an Akku oder zweites UBEC |

Die Aufteilung auf drei Pins ist Absicht. Eine Lötbrücke hätte gereicht, aber
sie erlaubt den Fall, der die Platine zerlegt: Brücke geschlossen **und** Akku
an J5, dann liegen bei 3S 12,6 V auf dem 5-V-Netz — also auf VSYS, dem
Pegelwandler und den Streifen, die alle 5,5 V vertragen. Mit dem Shunt ist das
mechanisch ausgeschlossen; er steckt entweder auf 1–2 oder auf 2–3.

Bei Stellung 1–2 teilt sich die Last die 3 A des UBEC mit den Streifen — bei
60 LEDs ist davon nicht mehr viel übrig.

Die Sperrspannung von Q1/Q2 richtet sich nach dem, was an `+VL` liegt. Bei
Stellung 1–2 sind es 5 V, und jeder Logic-Level-FET reicht. Bei Stellung 2–3
zählt die Zellenzahl dessen, was an J5 hängt:

| `+VL` | Spannung | AO3400A (30 V) |
|-------|----------|----------------|
| JP2 auf 1–2, aus dem UBEC | 5,0 V | reichlich |
| 3S LiPo | 12,6 V | gut |
| 4S LiPo | 16,8 V | gut |
| 6S LiPo | 25,2 V | zu knapp, anderer FET |

Wichtiger als die Zahl ist D1/D2: beim Abschalten einer induktiven Last schießt
die Drainspannung weit über die Versorgung hinaus, egal wie klein die war. Die
Freilaufdiode klemmt sie auf `+VL` + 0,5 V. Ohne sie ist die Sperrspannung des
FET gegenstandslos — dann stirbt jeder.

## Zwei Entscheidungen, die Begründung brauchen

**Serienwiderstände an den RC-Eingängen (R7–R11).** Die Pico-GPIOs sind nicht
5-V-fest. Die meisten Empfänger geben SBUS und PWM mit 3,3 V aus, aber nicht
alle — und welcher es ist, merkt man sonst erst, wenn der Pin tot ist. 1 kΩ
begrenzt den Strom in die Schutzdioden auf unter 2 mA und stört das Signal bei
100 kBaud nicht. Steht in `hardware/README.md` bisher nicht.

**Gate-Pulldown (R4, R6).** Zwischen Anlegen der Versorgung und dem ersten
`gpio_set_dir()` in `outputs_init()` ist der GPIO hochohmig. Ohne Pulldown
entscheidet die Gate-Ladung des FET, ob der Scheinwerfer beim Einschalten
kurz angeht. 100 kΩ zieht sicher auf Masse und kostet keinen nennenswerten
Strom.
