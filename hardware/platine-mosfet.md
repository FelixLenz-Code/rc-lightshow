# Bordplatine

Die kleine Variante: **zwei WS2812-Strips, zwei geschaltete Ausgänge, Pico
gesockelt**. Sie belegt genau die Pins, die das Beispiel in
`firmware/plane/src/config.h` schon benutzt.

Der Schaltplan liegt als [`schaltplan-mosfet.svg`](schaltplan-mosfet.svg) daneben und wird von
`schaltplan_mosfet.py` erzeugt:

```
python3 hardware/schaltplan_mosfet.py
```

Netznamen im Bild und in der Netzliste hier sind dieselben. Wer eines ändert,
ändert beides.

## Die Platine steuert, sie versorgt nicht

Das ist die wichtigste Eigenschaft dieses Entwurfs, und sie bestimmt fast alles
andere:

```
                    ┌──────────────▶ Strip 1   +5V, GND   (dick, direkt)
                    │
UBEC 5 V ───────────┼──────────────▶ Strip 2   +5V, GND   (dick, direkt)
   │                │
   │                └──────────────▶ J1        +5V, GND   (dünn, ~100 mA)
   │                                            │
   └── Sternpunkt                            Platine ─── DIN ──▶ Strips
```

Der LED-Strom läuft **nicht** über die Platine. Sie bekommt zwei Adern vom UBEC
für sich selbst — Pico und Pegelwandler ziehen zusammen rund 100 mA — und gibt
an die Streifen nur `DIN` und eine dünne Signalmasse ab. Der Sternpunkt liegt
damit am UBEC, außerhalb der Platine.

Das räumt die unangenehmste Fehlerquelle der ersten Fassung ab: dort lief der
gesamte Streifenstrom über die Platinenmasse, und jede Helligkeitsänderung hob
das Bezugspotential des Pico an.

**Warum trotzdem eine Masse an J2/J3.** Die Datenleitung braucht einen
Rückweg für ihre Flanken. Ohne benachbarte Masseader spannt `DIN` eine große
Schleife auf, deren Rückstrom sich irgendeinen Weg über das UBEC sucht — bei
Flankenzeiten im Nanosekundenbereich ist das eine Antenne. Die Signalmasse an
J2 Pin 2 gibt dem Rückstrom einen definierten, kurzen Weg.

Der Preis ist eine Masseschleife: Streifenmasse liegt sowohl am UBEC als auch
an der Platine. Ein Teil des LED-Stroms teilt sich nach Widerstandsverhältnis
auf. Bei dicker Versorgungsader (0,5 mm², ~10 mΩ) gegen dünne Signalmasse plus
Platinenzug (~60 mΩ) sind das etwa 15 %, also grob 500 mA bei 3,6 A. Über einen
1 mm breiten Massezug fallen davon rund 7 mV ab — für das Bezugspotential des
Pico bedeutungslos. Deshalb ist die Schleife hier akzeptabel; ohne die dicke
Ader direkt zum UBEC wäre sie es nicht.

**Am Massepad des Streifens treffen sich zwei Adern.** Eine dicke zum UBEC,
die den LED-Strom zurückführt, und eine dünne zur Platine, die den Rückstrom
der Datenflanken führt:

```
                 Streifen
   ┌──────────┬──────┬──────┐
   │   +5V    │ DIN  │ GND  │
   └────┬─────┴──┬───┴───┬──┘
        │        │       │
   dick │   dünn │  dünn │ dick
        │        │       │
        │        │       └────────▶ UBEC GND       0,5 mm²
        │        └────────────────▶ J2.1  DIN
        │                 └───────▶ J2.2  Signalmasse
        └─────────────────────────▶ UBEC +5V       0,5 mm²
```

Löten muss man das nicht am Pad. Bequemer ist eine **Spleißstelle wenige
Zentimeter vor dem Streifen**: eine Ader an den Streifen, kurz dahinter
aufgetrennt, verlötet, geschrumpft. Bei einem Streifen mit dem üblichen
dreiadrigen Pigtail spleißt man in die schwarze Ader hinein.

Entscheidend ist, **wo** der Abzweig sitzt: dicht am Streifen. Zweigt die dünne
Masse erst am UBEC ab, läuft der Flankenrückstrom den ganzen Umweg über das
UBEC — dann kann man sie sich auch sparen.

Wer den zweiten Draht nicht will, kann `DIN` allein verlegen. Bei kurzen Wegen
im Flügel und Datenkabel im selben Bündel wie die Platinenversorgung läuft das
meistens. Bei langen Wegen oder einem ESC daneben fängt man sich Störungen ein,
die aussehen wie ein Firmware-Fehler.

**Die geschalteten Lasten sind der Sonderfall.** Bei ihnen geht es nicht:
Q1/Q2 sitzen auf der Platine und schalten low-side, also *muss* der Laststrom
durch den FET und über die Platinenmasse zurück. Deshalb behält J5 seine
eigene, dicke Masseklemme — der Lastrückstrom darf nicht durch die dünne
Versorgungsader von J1 laufen. Wer das auch noch von der Platine haben will,
müsste auf fertige Relaismodule mit eigenem Treiber wechseln; dann wäre der
MOSFET überflüssig.

## Netzliste

Pinnummern sind die physischen Pins des jeweiligen Bauteils, beim Pico also die
Nummern auf dem Board, nicht die GPIO-Nummern.

| Netz | Angeschlossen an |
|------|------------------|
| `+5V` | J1.1 · C1.1 · U1.39 (VSYS) · U2.14 |
| `GND` | J1.2 · C1.2 · C2.2 · U1.3 · U1.8 · U1.13 · U1.18 · U1.38 · U2.1 · U2.4 · U2.7 · U2.9 · U2.10 · U2.12 · U2.13 · J2.2 · J3.2 · J4.1 · J5.2 · J9.3 · Q1.S · Q2.S · R4.2 · R6.2 |
| `DATA1` | U1.4 (GP2) · U2.2 |
| `DATA1_5V` | U2.3 · R1.1 |
| `STRIP1_DIN` | R1.2 · J2.1 |
| `DATA2` | U1.5 (GP3) · U2.5 |
| `DATA2_5V` | U2.6 · R2.1 |
| `STRIP2_DIN` | R2.2 · J3.1 |
| `REL1` | U1.9 (GP6) · R3.1 |
| `GATE1` | R3.2 · R4.1 · Q1.G |
| `LOAD1` | Q1.D · D1.A · J6.2 |
| `REL2` | U1.10 (GP7) · R5.1 |
| `GATE2` | R5.2 · R6.1 · Q2.G |
| `LOAD2` | Q2.D · D2.A · J7.2 |
| `+VL` | J5.1 · D1.K · D2.K · J6.1 · J7.1 |
| `SBUS_IN` | J4.3 · R7.1 |
| `SBUS` | R7.2 · U1.7 (GP5) |
| `UART_TX` | U1.1 (GP0) · J9.1 |
| `UART_RX_IN` | J9.2 · R12.1 |
| `UART_RX` | R12.2 · U1.2 (GP1) |

J4 Pin 2 ist unbeschaltet. Die übrigen Massepins des Pico (23, 28, 33) dürfen
mit an `GND`, müssen aber nicht. **U1.40 (VBUS) bleibt frei** — wer dort das
UBEC anschließt, speist an der USB-Schutzdiode vorbei ein.

## Gegengeprüft

Die Belegung — Strips auf GPIO 2/3, Lasten auf 6/7, SBUS auf 5, `pwm_pins`
leer — läuft ohne Beanstandung durch `config._parse_plane()`: kein Pin doppelt
belegt, SBUS auf einer UART1-RX-Leitung, GPIO 0/1 für die Konsole frei. Eine
Platine, die diese Netzliste umsetzt, kann keine Konfiguration erzwingen, die
die Web-UI später ablehnt.

`planegen.power_estimate()` meldet für 2 × 30 LEDs 3,6 A worst case und 0,94 A
typisch bei `MAX_BRIGHTNESS 200`. Diese Zahl ist jetzt eine Vorgabe für **UBEC
und Streifenzuleitung**, nicht mehr für die Leiterbahnen.

## Stückliste

| Ref | Bauteil | Package | Anmerkung |
|-----|---------|---------|-----------|
| U1 | Raspberry Pi Pico | 2 × Buchsenleiste 20-pol, RM 2,54, Reihenabstand 17,78 mm | steckbar, nicht löten |
| U2 | SN74AHCT125N | DIP-14 | **HCT**, nicht AHC. Sockel empfohlen |
| Q1, Q2 | AO3400A | SOT-23 | 30 V / 5,7 A, bei 2,5 V und 4,5 V spezifiziert |
| D1, D2 | SS14 bzw. SS34 | SMA | **nach Laststrom wählen**, siehe unten |
| R1, R2 | 330 Ω | 0805 | Serienwiderstand Datenleitung |
| R3, R5 | 100 Ω | 0805 | Gate-Vorwiderstand |
| R4, R6 | 100 kΩ | 0805 | Gate-Pulldown |
| R7 | 1 kΩ | 0805 | Strombegrenzung SBUS-Eingang |
| R12 | 1 kΩ | 0805 | Strombegrenzung Konsolen-RX |
| C1 | 10 µF MLCC, X7R/X5R | 0805 | Eingangspuffer an J1 |
| C2 | 100 nF X7R | 0805 | Abblockung U2, an Pin 14/7 |
| J1 | Schraubklemme 2-pol | RM 5,08 mm | Versorgung der Platine, ~100 mA |
| J2, J3 | JST-XH 2-pol | RM 2,50 mm | **nur DIN und Signalmasse** |
| J4, J9 | Stiftleiste 3-pol | RM 2,54 mm | SBUS, Konsole |
| J5, J6, J7 | Schraubklemme 2-pol | RM 5,08 mm | Lastversorgung (extern) und Lasten |

Der 1000-µF-Elko aus `hardware/README.md` ist **nicht** auf der Platine. Er
gehört an die Streifenzuleitung, wo die Einschaltspitze entsteht — also ans
UBEC-Ende, nicht hierher.

**LCSC-Nummern habe ich bewusst nicht eingetragen.** Sie hängen am
Lagerbestand, und eine erfundene C-Nummer kostet eine Bestellrunde.

Bestückung von Hand ist der realistische Weg: Pico, U2, Klemmen und Leisten sind
durchkontaktiert, und JLCPCB berechnet THT gesondert. 0805 und SOT-23 lassen
sich problemlos mit dem Kolben setzen.

## Grenzen, die man kennen muss

**Das Plus der Last muss aus J6.1 bzw. J7.1 kommen.** Holt man es woanders her
— etwa 12 V direkt vom Akku, während `+VL` auf 5 V steht — liegt D1 mit der
Kathode auf 5 V und der Anode auf 12 V. Die Diode leitet und schiebt die fremde
Spannung ins 5-V-Netz.

**D1/D2 müssen den Laststrom führen.** SS14 hält 1 A: genug für eine
Relaisspule, zu wenig für einen 3-A-Scheinwerfer. Dann SS34.

**J1 hat keinen Verpolschutz.** Vertauschte UBEC-Adern töten Pico und U2
sofort. Eine Serien-Schottky wäre hier verkraftbar, weil nur ~100 mA fließen;
sauberer ist ein verpolsicherer Steckverbinder statt der Schraubklemme.

**JST-XH ist mit 3 A je Kontakt spezifiziert.** Für J2/J3 spielt das keine
Rolle mehr, seit dort nur noch Daten laufen — aber die *Streifenzuleitung* vom
UBEC muss entsprechend dimensioniert sein, mindestens 0,5 mm².

## Die zwei Spannungen

`+5V` kommt vom UBEC an J1 und versorgt nur die Platine selbst: Pico (VSYS),
Pegelwandler und C1. Rund 100 mA.

`+VL` kommt ausschließlich von J5 und versorgt nur die geschalteten Lasten —
direkt vom Flugakku, von einem zweiten UBEC, oder vom selben UBEC mit eigenem
Aderpaar, wenn die Last mit 5 V läuft.

**Zwischen beiden gibt es keine Verbindung.** Kein Jumper, keine Brücke, keine
Stellung, die man falsch stecken kann. Was an J5 hängt, entscheidet allein die
Verdrahtung.

Ein früherer Entwurf hatte dafür einen dreipoligen Jumper, der `+VL` wahlweise
auf das 5-V-Netz legte. Das ist gestrichen, und zwar aus drei Gründen: der
Laststrom lief durch einen 2,54-mm-Shunt, der etwa 2 A verträgt; in dieser
Stellung kam die Lastspannung aus J1, also durch das dünne Aderpaar, das für
100 mA ausgelegt ist; und dasselbe Ergebnis erreicht man einfacher, indem man
J5 ans UBEC klemmt. Der Jumper konnte nur schlechter sein als das, was er
ersetzen sollte.

**Beide Pins von J5 gehören immer angeschlossen**, auch Pin 2. Er ist der
Rückweg des Laststroms von Q1/Q2 und muss dick sein.

Die Sperrspannung von Q1/Q2 richtet sich nach dem, was an J5 hängt:

| An J5 | Spannung | AO3400A (30 V) |
|-------|----------|----------------|
| UBEC 5 V | 5,0 V | reichlich |
| 3S LiPo | 12,6 V | gut |
| 4S LiPo | 16,8 V | gut |
| 6S LiPo | 25,2 V | zu knapp, anderer FET |

Wichtiger als die Zahl ist D1/D2: beim Abschalten einer induktiven Last schießt
die Drainspannung weit über die Versorgung hinaus, egal wie klein die war. Die
Freilaufdiode klemmt sie auf `+VL` + 0,5 V. Ohne sie ist die Sperrspannung des
FET gegenstandslos — dann stirbt jeder.

## Warum Last- und Signalmasse dasselbe Netz sind

Das sieht nach einem Fehler aus, ist aber die Voraussetzung dafür, dass ein
Low-Side-Schalter funktioniert.

Q1 schaltet über V_GS, die Spannung zwischen Gate und **Source**. Das Gate
treibt der Pico mit 3,3 V gegen die Platinenmasse, die Source liegt auf der
Platinenmasse — also V_GS = 3,3 V. Läge die Lastmasse getrennt, müsste die
Source dorthin, damit der Strom zurückfließen kann; dann wäre V_GS die Differenz
zwischen zwei Massen ohne definierte Beziehung. Der FET schaltet dann nicht,
unzuverlässig, oder gar nicht mehr ab. Eine echte Trennung bräuchte einen
Optokoppler oder einen isolierten Gate-Treiber.

Getrennt ist deshalb nicht das Netz, sondern der **Kupferweg**: Der Laststrom
läuft von Q1/Q2 über eine eigene, breite Bahn nach J5.2 und trifft die
Signalmasse erst am Sternpunkt. Gleiches Potential, verschiedene Wege.

## Der Empfänger hängt mit zwei Drähten dran

**Masse und Signal, sonst nichts.** J4 Pin 2 ist unbeschaltet, obwohl die
Buchse dreipolig bleibt — so passt ein normales Servokabel weiterhin direkt
hinein, und die +5-V-Ader endet an einem Pad, das nirgendwo hinführt. Der
Empfänger versorgt sich selbst.

**Kein PWM-Eingang.** Die Platine spricht ausschließlich SBUS. Das kostet den
Rückfallpfad: bleiben die SBUS-Frames aus, gibt es keine zweite Quelle mehr,
und die Firmware geht ins Failsafe. Dafür ist die Verdrahtung eine Leitung
statt vier. `rc_input.c:82` klammert den ganzen PWM-Zweig mit
`#if PWM_COUNT > 0`, und `pwm_pins: []` läuft ohne Beanstandung durch die
Konfigurationsprüfung.

**Niemals einen Pull-up auf die SBUS-Leitung.** Der Pin wird in
`rc_input.c:121` mit `gpio_set_inover(INVERT)` invertiert, und der RP2040
startet seine Pads mit aktivem Pull-down. Ein abgezogener Empfänger liest
dadurch als UART-Ruhepegel — keine Störbytes. Ein externer Pull-up würde das
umdrehen und Dauer-Framing-Fehler erzeugen. Wer es explizit will, setzt einen
10-kΩ-Pull-down oder ein `gpio_pull_down(SBUS_RX_PIN)` in die Firmware; die
PWM-Pins bekommen das in Zeile 129 bereits.

**GPIO 10 bis 13 sind frei.** In einer späteren Version passen dort zwei
weitere Strips und zwei weitere Relais hin.

## Layout

Zweilagig, 1,6 mm, 35 µm Kupfer. Ohne die Streifenversorgung ist die Platine
deutlich kleiner geworden — geschätzt **60 × 50 mm**, im Wesentlichen bestimmt
vom Pico (21 × 51 mm) und den vier Schraubklemmen.

Welche Verbindung wie breit sein muss, steht als eigener Plan daneben:
[`strompfade-mosfet.svg`](strompfade.svg), erzeugt von `strompfade_mosfet.py`. Er zeigt die
**komplette** Platine — jede Leitung, eingefärbt nach nötiger Breite — und
benutzt die Bezeichner der EasyEDA-Zeichnung, nicht die dieser Netzliste.

**Ausgelegte Hülle**, solange die Last nicht feststeht:

| | Wert | Grund |
|---|---|---|
| `+VL` | 5 – 17 V | AO3400A hält 30 V, 4S ist die Grenze mit Reserve |
| je Kanal | bis 3 A | rund 50 W bei 4S; SOT-23 will dafür Kupferfläche am Drain-Pad |
| beide zusammen | bis 5 A | nur die Stämme zu J5 führen die Summe |

**Bahnbreiten** bei 35 µm und 10 K Erwärmung:

| Abschnitt | Strom | Breite |
|---|---|---|
| J5.1 bis zur ersten Verzweigung, und Sternpunkt bis J5.2 | bis 5 A | **3 mm** |
| Je Zweig: zu J6/J7, Drain, Source zum Sternpunkt, Freilaufdiode | bis 3 A | **2 mm** |
| `+5V` und `GND` der Platine | unter 100 mA | 0,3 mm |
| Signale, Daten, SBUS, Konsole | µA | 0,3 mm |

Rechnerisch trägt 2 mm rund 4 A und 3 mm rund 5,3 A — die Empfehlung liegt also
etwa das Anderthalbfache über dem Bedarf. Das ist Absicht: Ätztoleranz, Wärme im
Rumpf, und die 10 K gelten für eine frei liegende Platine.

**Hin- und Rückweg gleich breit.** Der Rückweg über Source und J5.2 führt
denselben Strom wie der Hinweg — das wird vergessen, weil „Masse" nach
Nebensache klingt.

**Vias im Lastpfad vermeiden.** Eine 0,3-mm-Via trägt etwa 1 bis 1,5 A; bei 3 A
bräuchte es drei bis vier nebeneinander. Der Lastpfad verbindet nur drei Klemmen
und zwei Transistoren — die kann man so setzen, dass er auf einer Lage bleibt.

Über 3 A lohnt sich **2 oz Außenkupfer** bei der Bestellung. Das halbiert die
nötige Breite und kostet auf einer so kleinen Platine wenig.

**Der Sternpunkt liegt am UBEC**, nicht auf der Platine. Streifen, Lastkreis und
Platine bekommen jeder eine eigene Ader dorthin.

**Die Signalmasse zu J2/J3 dünn halten.** Sie soll den Rückstrom der Flanken
führen, nicht Ampere aus dem Streifen abzweigen — je höher ihr Widerstand
gegenüber der dicken Streifenader, desto weniger LED-Strom nimmt den Umweg über
die Platine.

**DIN und Signalmasse als Paar verlegen**, nebeneinander bis zum Streifen. R1
und R2 sitzen am U2-Ausgang, nicht am Streifenstecker — sie sollen die Flanke
dort dämpfen, wo sie entsteht.

**Der Lastpfad bleibt getrennt.** Der ganze Kreis läuft J5.1 → J6/J7 → Last →
Q1/Q2 → J5.2 und berührt J1 an keiner Stelle. Auf der Platine heißt das: die
Massebahn von Q1/Q2 geht auf kurzem, breitem Weg nach J5.2, und **dort liegt
der Sternpunkt** — Pico, U2, Signalmassen und J1.2 hängen daran, tragen aber
keinen Laststrom.

Speist die Last aus demselben UBEC wie die Platine, bilden J1.2 und J5.2 eine
Schleife über die beiden Zuleitungen. Der Strom teilt sich nach Widerstand auf,
also fast vollständig über die dicke J5-Ader — dieselbe Rechnung wie bei der
Signalmasse der Streifen.

**Zwei Kondensatoren, zwei Aufgaben.** C1 sitzt an J1 und deckt die
Induktivität der Zuleitung ab — der Pico zieht über seinen Auf-/Abwärtswandler
pulsierenden Strom aus VSYS, den soll er lokal bekommen und nicht durch 30 cm
Draht holen. C2 gehört zu U2, nicht zur Versorgung.

Ein zweiter, kleinerer Kondensator neben C1 wäre nur dann sinnvoll, wenn C1 ein
Elko oder Tantal wäre: solche Bauformen haben hohen ESR und hohe
Eigeninduktivität und sind bei schnellen Stromänderungen praktisch nicht da.
**Mit einem 10-µF-MLCC entfällt das** — er deckt beides selbst ab. Zwei
Keramiken parallel bilden zudem eine Antiresonanz, eine Frequenz, bei der die
Impedanz der Kombination höher ist als die jedes einzelnen. Hier schadet das
nichts, aber es ist auch kein Grund, ein Bauteil zu bestücken.

Wer C1 doch als Tantal bestückt, setzt 100 nF daneben.

**Die 3,3-V-Seite kurz halten.** U2 so dicht an den Pico wie möglich; die
5-V-Seite hinter den 330 Ω darf lang sein, die ungepufferte Seite davor nicht.

**C2 gehört zwischen U2 Pin 14 und Pin 7**, so dicht am Gehäuse wie das Layout
es zulässt — wenige Millimeter, nicht am Platinenrand. Er ist der lokale
Ladungsspeicher für die Umschaltmomente: jedes Mal, wenn ein Treiber
umschaltet, zieht U2 kurzzeitig einen Stromimpuls, den die Zuleitung wegen
ihrer Induktivität nicht schnell genug liefern kann. Ohne C2 bricht die
Versorgung von U2 bei jeder Flanke ein, und ein Pegelwandler mit
einbrechender Versorgung macht genau das, wogegen er eingebaut wurde.

## Zwei Entscheidungen, die Begründung brauchen

**Serienwiderstände an den Eingängen (R7, R12).** Die Pico-GPIOs sind nicht
5-V-fest. Die meisten Empfänger geben SBUS mit 3,3 V aus, aber nicht alle, und
ein USB-Seriell-Adapter mit 5-V-Pegel ist häufig — welcher es ist, merkt man
sonst erst am toten Pin. 1 kΩ begrenzt den Strom in die Schutzdioden auf unter
2 mA und stört weder 100 kBaud noch die Konsole. GP0 braucht das nicht, der ist
ein Ausgang.

**Gate-Pulldown (R4, R6).** Zwischen Anlegen der Versorgung und dem ersten
`gpio_set_dir()` in `outputs_init()` ist der GPIO hochohmig. Ohne Pulldown
entscheidet die Gate-Ladung des FET, ob der Scheinwerfer beim Einschalten kurz
angeht. 100 kΩ zieht sicher auf Masse und kostet keinen nennenswerten Strom.
