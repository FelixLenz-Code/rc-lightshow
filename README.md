# Lightshow

Musiksynchrone Lichtshow mit Modellflugzeugen. Die Show wird in Ardour als
MIDI-Automation gebaut, eine Bridge setzt das in RC-Kanäle um, ein RP2040
speist sie als PPM oder SBUS in die Lehrer/Schüler-Buchse von bis zu acht
Fernsteuerungen, und im Modell erzeugt ein zweiter Mikrocontroller daraus die
eigentlichen Lichteffekte.

```
Ardour ──MIDI──▶ host/ ──USB──▶ firmware/pico/ ──Klinke──▶ Sender ──RF──▶ Empfänger
  Automation      Bridge          8× PPM/SBUS    Trainer                     │
                                                                             │
                                                         firmware/plane/ ◀───┘
                                                          Effekt-Engine
                                                               │
                                                            WS2812
```

**Inhalt**

1. [Konzept](#konzept)
2. [Stand des Projekts](#stand-des-projekts)
3. [Bedienoberfläche](#bedienoberfläche)
4. [Hardware](#hardware)
5. [Installation](#installation)
6. [Konfiguration](#konfiguration)
7. [Ardour](#ardour)
8. [Inbetriebnahme in fünf Stufen](#inbetriebnahme-in-fünf-stufen)
9. [Testverfahren](#testverfahren)
10. [Fehlersuche](#fehlersuche)
11. [Sicherheit](#sicherheit)
12. [Aufbau des Codes](#aufbau-des-codes)

---

## Konzept

### Warum ein Controller im Modell

Die Funkstrecke liefert nur etwa 45 Updates pro Sekunde bei realistisch 6–7
nutzbaren Bit je Kanal. Das reicht für weiche Fades, **nicht** für Strobes oder
Lauflichter. Ein Kanal je Lampe wäre außerdem sofort am Kanallimit.

Deshalb überträgt die Show pro Modell nur **vier Parameterkanäle**:

| Kanal | Rolle        | Bedeutung                                       |
|-------|--------------|-------------------------------------------------|
| 1     | `cue`        | Effektnummer, 32 Stufen, Stufe 0 = alles aus    |
| 2     | `hue`        | Farbton 0–255                                   |
| 3     | `brightness` | Master-Dimmer, optional 14 Bit für weiche Fades |
| 4     | `param`      | Tempo bzw. zweiter Effektparameter              |

Langsame, musikalisch exakte Werte kommen vom Boden, schnelle Effekte erzeugt
das Modell selbst. Die Cue-Nummer wird in 32 grobe Stufen quantisiert und jeder
Wert in die **Mitte** seiner Stufe gelegt, damit ein verrauschter Kanal nie auf
einer Stufengrenze sitzt.

Vollständige Effektliste: [`docs/cues.md`](docs/cues.md).

### Was das für die Skalierung heißt

Vier Kanäle je Modell bedeutet: ein 16-Kanal-Sender trägt **vier Modelle**. Alle
Empfänger auf dasselbe Sendermodell binden, jedes Modell greift sich über
`base_channel` seiner Zone den passenden Kanalblock. Acht Modelle brauchen also
zwei Sender, nicht acht.

---

## Stand des Projekts

**Fertig und automatisiert getestet:**

- Bridge läuft, end-to-end mit echtem ALSA-MIDI geprüft
- Beide Firmwares kompilieren warnungsfrei (`-Wall -Wextra` auf den eigenen Targets)
- Web-UI mit Live-Status, Modelleditor und Anschlussübersicht
- 78 Tests, darunter ein Abgleich der C- gegen die Python-Implementierung des
  Protokolls, eine Verifikation der PPM-Timing-Rechnung und ein Compiler-Lauf
  über die generierte Bordkonfiguration

**Nie auf echter Hardware gelaufen.** Ungetestet ist damit alles Physische: das
Signal an der Trainer-Buchse, der komplette SBUS-Pfad, die LEDs, das
Strombudget, die Ethos-Menüführung. Die Reihenfolge unter
[Inbetriebnahme](#inbetriebnahme-in-fünf-stufen) ist genau darauf ausgelegt,
diese Unsicherheiten einzeln aufzulösen.

---

## Bedienoberfläche

Die Bridge bringt eine lokale Web-UI mit. Sie startet automatisch mit:

```bash
cd host && ./.venv/bin/python -m lightshow
# web interface: http://127.0.0.1:8765/
```

Sie braucht keine zusätzlichen Pakete — reine Python-Bordmittel. Mit
`--web-host 0.0.0.0` ist sie auch vom Handy im selben WLAN erreichbar,
`--no-web` schaltet sie ab.

**Live** — ob die DAW verbunden ist (über `aconnect` ausgelesen, also die echte
Verbindung, nicht nur „es kommt was an"), ob der Pico hängt, und was auf jedem
Kanal ankommt: Mikrosekunden, Pegelbalken und der dekodierte Wert. Bei
`cue` steht dort die erkannte Stufe, sonst der Prozentwert. Kanäle, auf denen
noch nichts kam, sind als Failsafe markiert.

**Modelle** — LED-Strips, Relais und Positionslichter je Modell anlegen und
bearbeiten. Beim Speichern läuft dieselbe Prüfung wie beim Start, Fehler kommen
im Klartext zurück („GPIO 5 wird von SBUS und Strip 'flaeche_links' benutzt").
Die Vorversion bleibt als `show.yaml.bak` liegen.

> Solange MIDI hereinkommt, ist die Bearbeitung **gesperrt**. Zum Ändern die
> Wiedergabe in der DAW stoppen. Das verhindert, dass sich die Zuordnung mitten
> in einer Show verschiebt.

**Anschluss** — je Modell eine Tabelle, wo was an den Pico im Flieger kommt,
inklusive **physischer Pinnummer** auf der Platine, dazu der geschätzte
LED-Strom und die fertige `config.h`. Ein Knopf schreibt sie nach
`firmware/plane/generated/<modell>.h`.

### Warum die Bordkonfiguration generiert wird

Zum Flieger führt kein Datenweg außer den RC-Kanälen — man kann ihn nicht zur
Laufzeit umkonfigurieren. Deshalb ist die Modelldefinition in `show.yaml` die
einzige Quelle, und daraus entsteht der Header, mit dem die Bordfirmware
übersetzt wird:

```bash
cd host && ./.venv/bin/python -m lightshow --generate eule
cmake -S firmware/plane -B build/plane-eule -DPLANE_CONFIG=generated/eule.h
cmake --build build/plane-eule -j4
```

Ohne `-DPLANE_CONFIG` baut das dokumentierte Beispiel aus `src/config.h`. Nach
jeder Änderung an den Ausgängen eines Modells muss dessen Firmware neu
generiert und geflasht werden — die Bridge allein reicht nicht.

---

## Hardware

Vollständige Stückliste, Pinbelegung und Strombudget:
[`hardware/README.md`](hardware/README.md). Das Wichtigste hier.

### Bodenstation

Ein **Raspberry Pi Pico**. Ausgänge auf GPIO2–GPIO9 (Port 0–7), Selbsttest-
Eingang auf GPIO10, Status-LED onboard.

Je Ausgang:

```
GPIO ──[ 1k ]──┬── Tip (3,5-mm-Klinke)
               │
GND ───────────┴── Sleeve
```

**Ring der Klinke offen lassen** — dort führen manche Sender Akkuspannung.
Masse muss gemeinsam sein, sonst sieht der Sender nur Rauschen.

Die meisten Sender kommen mit 3,3 V direkt zurecht. Braucht einer echte 5 V oder
eine invertierte Flanke, kommt ein **74HCT14** dazwischen. Polarität zuerst in
der Software probieren, das kostet nichts.

### Im Modell

Ein **Raspberry Pi Pico** — dasselbe Board wie am Boden, also ein Ersatzteil für
beide Seiten. Der RP2040 passt hier aus zwei handfesten Gründen: PIO erzeugt das
WS2812-Timing in Hardware, sodass die Effektberechnung nie Pixel flackern lässt,
und der UART kann 100 kBaud 8E2 nativ — SBUS braucht damit nur
`gpio_set_inover()` statt eines Invertertransistors.

Wird es im Rumpf eng, läuft derselbe Code unverändert auf einem Waveshare
RP2040-Zero (2,4 g statt ~3 g): `-DPICO_BOARD=waveshare_rp2040_zero`.

| GPIO   | Funktion                                  |
|--------|-------------------------------------------|
| 0 / 1  | Debug-UART                                |
| 2, 3   | WS2812-Daten, ein Pin je Strip            |
| 5      | SBUS vom Empfänger                        |
| 6, 7   | Relais-Ausgänge                           |
| 10–13  | PWM-Eingänge, Fallback ohne SBUS          |

Versorgung über **VSYS (Pin 39)** und GND (Pin 38) vom UBEC, nicht über VBUS —
so stört ein gleichzeitig gestecktes USB-Kabel beim Einrichten nicht.

SBUS wird bevorzugt, PWM automatisch genutzt, wenn keine SBUS-Frames ankommen.
Beides läuft gleichzeitig, es gibt keinen Umschalter.

Der Pegelwandler vor den LED-Strips ist **nicht optional**: 3,3 V Datenpegel an
einem 5-V-Streifen funktioniert mal und setzt mal aus, gern erst in der Luft.
Relais brauchen ebenfalls eine Treiberstufe — ein GPIO kann keine Spule
schalten. Schaltbilder in [`hardware/README.md`](hardware/README.md).

### Ausgänge je Modell konfigurieren

`firmware/plane/src/config.h` beschreibt die Ausgangsstufe als drei Tabellen:
bis zu **8 WS2812-Strips** und **8 Relais**, gruppiert in **Zonen**. Nur diese
Datei wird je Modell angefasst.

```c
#define STRIP_COUNT 2
#define STRIPS { \
    /* pin, count, zone, offset, reverse */              \
    /* linke Fläche, läuft nach außen  */ {2, 30, 0, 0, false}, \
    /* rechte Fläche, gespiegelt       */ {3, 30, 0, 0, true},  \
}

#define RELAY_COUNT 2
#define RELAYS { \
    /* pin, zone, source, arg, threshold, active_low, min_on, min_off */ \
    /* Scheinwerfer, MOSFET, blitzt im Takt   */ {6, 0, RELAY_SRC_PIXEL, 0, 64, false,   0,   0}, \
    /* Rauch, Relaismodul, ab Cue 5           */ {7, 0, RELAY_SRC_CUE,   5,  0, true,  200, 200}, \
}
```

**Zonen** bündeln Ausgänge, die denselben Effekt zeigen. Eine Zone belegt vier
RC-Kanäle. Zwei Zonen heißen: Flächen und Rumpf laufen unabhängig, kosten aber
acht Kanäle.

**`offset`** bestimmt, wie Strips zusammenspielen: gleicher Offset spiegelt sie,
fortlaufende Offsets machen aus mehreren Strips eine lange virtuelle Kette, über
die ein Lauflicht durchläuft. **`reverse`** dreht einen verkehrt herum
eingebauten Strip um, damit ein Lauflicht auf beiden Flächen wirklich nach außen
läuft.

**Relais-Quellen** — was ein Relais schalten lässt:

| Quelle                 | Verhalten                                              |
|------------------------|--------------------------------------------------------|
| `RELAY_SRC_PIXEL`      | folgt einem Pixel der Zone, blitzt exakt mit dem Effekt |
| `RELAY_SRC_BRIGHTNESS` | an, solange der Master-Dimmer über der Schwelle liegt   |
| `RELAY_SRC_CUE`        | an ab Cue `arg`                                        |
| `RELAY_SRC_CHANNEL`    | an über einen eigenen RC-Kanal                         |

Nur `RELAY_SRC_CHANNEL` kostet einen zusätzlichen Kanal; die anderen drei werden
aus der Effekt-Engine abgeleitet. Cue 0 schaltet immer alle Relais ab.

`min_on_ms` / `min_off_ms` erlauben den Mischbetrieb: **0** für MOSFETs, die
jedem Blitzmuster folgen, **~200** für mechanische Relais — die hängen dann am
selben Effekt, schalten aber nur so oft, wie sie es überleben.

---

## Installation

### Bridge

Ubuntu 24.04 ist PEP-668-verwaltet, deshalb zwingend ein venv:

```bash
cd host
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt pytest
```

### Firmware-Toolchain

```bash
sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi \
                 libstdc++-arm-none-eabi-newlib
git clone --depth 1 --recurse-submodules \
    https://github.com/raspberrypi/pico-sdk ~/pico-sdk
```

`PICO_SDK_PATH` muss beim Bauen gesetzt sein — entweder je Aufruf oder dauerhaft
in `~/.bashrc`:

```bash
export PICO_SDK_PATH=~/pico-sdk
```

### Bauen

```bash
cmake -S firmware/pico  -B build/pico  -DCMAKE_BUILD_TYPE=Release
cmake --build build/pico  -j4

cmake -S firmware/plane -B build/plane -DCMAKE_BUILD_TYPE=Release
cmake --build build/plane -j4
```

Ergebnis:

| Datei                            | Ziel                    | Größe            |
|----------------------------------|-------------------------|------------------|
| `build/pico/lightshow_tx.uf2`    | Pico an der Bodenstation| 46 KB Flash      |
| `build/plane/lightshow_plane.uf2`| Pico im Modell          | 31 KB Flash      |

Beide Firmwares bauen per Default für den Raspberry Pi Pico; ein anderes Board
über `-DPICO_BOARD=<name>`.

### Flashen

BOOTSEL gedrückt halten, USB anstecken, Taste loslassen. Das Board meldet sich
als Laufwerk `RPI-RP2`. Die passende `.uf2` daraufkopieren, das Board startet
selbständig neu.

---

## Konfiguration

Alles Senderspezifische steht in [`host/config/show.yaml`](host/config/show.yaml).
Ein anderer Sender heißt: eine Zeile ändern. Kein Neuflashen, kein Umlöten.

```yaml
serial_port: /dev/ttyACM0
rate_hz: 100
midi_port_name: lightshow
blackout_cc: 119        # CC >= 64 schaltet sofort alles auf Failsafe
global_offset_ms: 0     # Licht verzögern; negativ geht nicht

tx_ports:
  - id: 0               # id 0 = GPIO2, id 1 = GPIO3, ...
    name: frsky_ethos
    format: ppm         # ppm | sbus | off
    polarity: normal    # normal | inverted
    nchan: 8
    frame_us: 22500
    sync_us: 400
    min_us: 1000
    max_us: 2000

models:
  - name: eule
    midi_channel: 1     # so wie Ardour ihn anzeigt, 1..16
    tx_port: 0
    tx_offset: 0        # erster belegter Kanal des Ports
    channels:
      - {role: cue,        cc: 20, quantize: 32, failsafe: 1000}
      - {role: hue,        cc: 21,               failsafe: 1500}
      - {role: brightness, cc: 22, cc_lsb: 54,   failsafe: 1000}
      - {role: param,      cc: 23,               failsafe: 1500}
```

Prüfen ohne Hardware:

```bash
cd host && ./.venv/bin/python -m lightshow --check
```

Die Prüfung ist streng und meldet konkret: überlappende Kanalblöcke, doppelt
vergebene CCs, zu kurze PPM-Frames, Failsafe-Werte außerhalb des Kanalbereichs.

Details zu weiteren Sendermarken und zum Betrieb mehrerer Modelle an einem
Sender: [`docs/sender-setup.md`](docs/sender-setup.md).

---

## Ardour

Ausführlich in [`docs/ardour-setup.md`](docs/ardour-setup.md). Kurzfassung:

1. **Bridge zuerst starten.** Sie legt den virtuellen MIDI-Port `lightshow` an;
   ohne laufende Bridge gibt es in Ardour nichts zu verbinden.
2. Je Flugzeug ein MIDI-Track ohne Instrument, Ausgang auf `lightshow`.
3. Am Track den ausgehenden **MIDI-Kanal erzwingen** — sonst senden alle Tracks
   auf Kanal 1 und steuern dasselbe Modell.
4. Vier Automationsspuren je Track (CC 20–23), Automationsmodus auf **Play**.
5. `cue` als **Stufen** zeichnen, nicht als Rampe: eine Rampe löst beim
   Durchlaufen alle Effekte dazwischen kurz aus.

---

## Inbetriebnahme in fünf Stufen

Jede Stufe fügt genau ein Stück Unsicherheit hinzu. Wenn eine fehlschlägt,
weißt du ohne Suchen, woran es liegt. **Bis Stufe 4 bleibt der Propeller ab.**

### Stufe 1 — Bridge ohne jede Hardware

```bash
cd host && ./.venv/bin/python -m lightshow --dry-run
```

*Erwartet:* TUI mit einem Balken je Kanal, alle Werte auf ihren
Failsafe-Positionen, `link: dry-run`.

Dann Ardour verbinden und die Automation abspielen. Die Balken müssen der
Automation folgen, `b` schaltet Blackout.

*Damit belegt:* MIDI-Routing, Mapping, Quantisierung, Fades. Kostet nichts.

### Stufe 2 — Pico allein

Firmware flashen, USB anstecken, `serial_port` prüfen:

```bash
ls /dev/ttyACM*
cd host && ./.venv/bin/python -m lightshow
```

*Erwartet:* Status-LED des Pico leuchtet **dauerhaft**, in der TUI steht
`link: /dev/ttyACM0 ok`, und in den Statuszeilen erscheint einmal pro Sekunde:

```
STAT link=1 ports=1 frames=... crc_err=0 bad=0 gaps=0 cfg=1
```

`crc_err` und `bad` müssen 0 bleiben, `cfg=1` bestätigt die angenommene
Portkonfiguration.

*Damit belegt:* USB-Verbindung, Framing, CRC, Portkonfiguration.

### Stufe 3 — Signal gegenprüfen, ohne Oszilloskop

**Ein Jumperkabel von GPIO2 nach GPIO10.** Die Firmware misst ihr eigenes
Ausgangssignal und meldet einmal pro Sekunde:

```
SELFTEST ppm idle=low (normal) mark=400us frame=22500us nch=8 [1000 1500 1000 1500 ...]
```

*Zu prüfen:*

- `idle` passt zur konfigurierten `polarity`
- `mark` entspricht `sync_us`
- `frame` entspricht `frame_us`
- die Kanalwerte entsprechen dem, was die TUI anzeigt — auf wenige Mikrosekunden

*Damit belegt:* PPM-Erzeugung, Timing, Polarität, Kanalreihenfolge. Das ist die
Stufe, die sonst ein Oszilloskop bräuchte.

### Stufe 4 — Erster Sender

Klinke an die Trainer-Buchse, Tip auf GPIO2 über 1 kΩ, Sleeve auf GND, **Ring
offen**. Im Sender den Trainer-Eingang auf Master/Jack mit PPM stellen.

*Erwartet:* Im Kanalmonitor des Senders bewegen sich die Trainer-Kanäle mit der
Ardour-Automation.

Trainer-Kanäle jetzt **ausschließlich auf die Lichtkanäle** mischen.

### Stufe 5 — Modell

Bordfirmware flashen, `config.h` an das Modell anpassen: Zonen, Strips, Relais,
Positionslichter. Empfänger und LED-Streifen auf dem Tisch aufbauen, eigenes
UBEC für die LEDs.

**Relais zuerst ohne Last testen** — nur der Treiber, die geschaltete Leitung
noch nicht angeschlossen. Ein falsch gesetztes `active_low` schaltet sonst beim
Einschalten sofort durch, und bei einem Rauchsystem oder einem Scheinwerfer auf
der Werkbank ist das kein guter Moment, das zu merken.

*Erwartet:* Positionslichter leuchten sofort und dauerhaft. Cue-Wechsel in
Ardour ändern den Effekt, `brightness` dimmt weich. Relais schalten gemäß ihrer
Quelle; bei Cue 0 fallen alle ab.

*Failsafe prüfen:* Sender ausschalten. Nach 500 ms muss das Modell auf langsames
bernsteinfarbenes Pulsen umschalten und **alle Relais müssen abfallen**. Die
Farbe kommt in keinem Cue vor — du siehst im Flug sofort, welches Modell die
Verbindung verloren hat.

Danach: komplettes Musikstück auf dem Tisch durchlaufen lassen, erst dann ein
Modell im Flug, dann skalieren.

---

## Testverfahren

### Automatisierte Tests

```bash
cd host && ./.venv/bin/python -m pytest tests -v
```

78 Tests. Die interessanten sind keine Unit-Tests, sondern Kreuzprüfungen:
`tools/ctest/` kompiliert die **echten** Firmware-Quellen für den PC und prüft
sie gegen die Python-Seite. Driftet eine Seite weg, schlägt der Test fehl.

| Datei                  | Prüft                                                        |
|------------------------|--------------------------------------------------------------|
| `test_protocol.py`     | CRC gegen Referenzvektor, Frame-Layout                        |
| `test_config.py`       | Konfigurationsprüfung: Überlappungen, doppelte CCs, Grenzen   |
| `test_mapping.py`      | MIDI → Mikrosekunden, 14 Bit, Invertierung, Blackout, Panic   |
| `test_cross_check.py`  | C-Parser gegen Python-Encoder: CRC, Byte-Reihenfolge, Resync  |
| `test_ppm_frame.py`    | PPM-Timing aus dem echten Frame-Builder rekonstruiert         |
| `test_relay_logic.py`  | Relais-Quellen und Mindestschaltzeiten der Bordfirmware       |
| `test_planegen.py`     | generierte Bordkonfiguration, Anschlussliste, YAML-Roundtrip  |

Drei davon lohnen eine Erklärung:

**`test_ppm_frame.py`** rechnet die tatsächlichen Pulslängen zurück. Das
PIO-Programm verbraucht drei feste Takte je Halbwelle, der Puffer enthält also
`Dauer − 3`. Wäre diese Kompensation falsch, wären alle Kanäle um denselben
Betrag daneben — am Sender als Trimmfehler sichtbar und mühsam zu finden. Der
Test prüft Kanalabstände, Gesamtframelänge auf die Mikrosekunde und die
Mindest-Sync-Lücke.

**`test_cross_check.py`** prüft unter anderem, dass jeder Cue-Schritt den
Rundweg übersteht: was die Bridge kodiert, muss die Bordfirmware als denselben
Schritt dekodieren — auch mit ±13 µs Störung auf dem Kanal.

**`test_relay_logic.py`** simuliert ein 10-Hz-Strobe über drei Sekunden und
prüft, dass ein mechanisches Relais dabei nie schneller schaltet als erlaubt,
aber trotzdem noch blinkt statt in einem Zustand hängenzubleiben. Dazu die
Sonderfälle: Cue 0 schaltet jede Quelle ab, und ein Aussetzer, der kürzer ist
als die Mindestzeit, wird nicht nachträglich durchgereicht.

Die C-Werkzeuge einzeln bauen:

```bash
make -C tools/ctest
```

### Manuelle Prüfungen

| Was                     | Wie                                                        |
|-------------------------|------------------------------------------------------------|
| MIDI kommt an           | `aconnect -l \| grep lightshow`, dann `aseqdump -p lightshow` |
| Mapping stimmt          | `python -m lightshow --dry-run`                            |
| Konfiguration gültig    | `python -m lightshow --check`                              |
| UI erreichbar           | Bridge starten, `http://127.0.0.1:8765/` öffnen            |
| PPM-Signal korrekt      | Jumper GPIO2 → GPIO10, `SELFTEST`-Zeile lesen              |
| Failsafe Bodenstation   | USB im Betrieb abziehen → Ausgänge binnen 250 ms auf Failsafe |
| Failsafe Modell         | Sender ausschalten → nach 500 ms bernsteinfarbenes Pulsen, alle Relais fallen ab |
| Relais am Boden prüfen  | Cue auf 0 stellen → jedes Relais muss abfallen             |

---

## Fehlersuche

**Der MIDI-Port taucht in Ardour nicht auf.** Die Bridge muss laufen, bevor du
in Ardour verbindest — der Port existiert nur, solange sie läuft. Prüfen mit
`aconnect -l | grep lightshow`.

**Alle Tracks steuern dasselbe Modell.** Der ausgehende MIDI-Kanal ist am Track
nicht erzwungen, alles geht auf Kanal 1.

**`link: DOWN` in der TUI.** Gerätepfad prüfen (`ls /dev/ttyACM*`) und ob du in
der Gruppe `dialout` bist (`groups`). Die Bridge verbindet sich selbständig neu,
sobald das Gerät wieder da ist.

**`crc_err` zählt hoch.** Kabel oder USB-Port wechseln. Die Frames werden
verworfen, nicht falsch interpretiert.

**Im Sender bewegt sich nichts.** In dieser Reihenfolge:

1. Stufe 3 wiederholen — liegt am Ausgang überhaupt das erwartete Signal?
2. `polarity: inverted` setzen, Bridge neu starten
3. `sync_us: 300` probieren
4. 74HCT14 als 5-V-Puffer einschleifen
5. Masseverbindung prüfen — der häufigste Fehler

**Cue springt zwischen zwei Effekten.** In Ardour eine Rampe statt einer Stufe
gezeichnet. `cue` verträgt keine Zwischenwerte.

**LEDs flackern oder zeigen falsche Farben.** Pegelwandler fehlt oder die
Stromversorgung bricht ein. Nicht am Empfänger-BEC betreiben.

**Brummen bei mehreren Sendern.** Sternmasse am Pico; hilft das nicht,
USB-Isolator zwischen PC und Pico.

---

## Sicherheit

- Trainer-Kanäle im Sender **ausschließlich** auf Lichtkanäle mischen, niemals
  auf Gas oder Ruder. Ein Fehler in der Show darf das Modell nicht steuern.
- **Positionslichter** (rot links, grün rechts, weiß Heck) laufen in der
  Bordfirmware unabhängig von der Show und lassen sich nicht abschalten. Der
  Pilot braucht sie zur Lageerkennung.
- `MAX_BRIGHTNESS` in `firmware/plane/src/config.h` deckelt Spitzenstrom und
  Blendwirkung.
- Zwei unabhängige Failsafes: Host weg → Ausgänge nach 250 ms auf Failsafe;
  Funk weg → Modell nach 500 ms auf ein Muster, das in keinem Cue vorkommt.
- **Relais fallen bei Funkausfall sofort ab**, ohne Rücksicht auf
  Mindestschaltzeiten. Beim Booten werden die Pins auf den Aus-Pegel getrieben,
  bevor sonst etwas läuft — ein Relaisboard klickt also nicht beim Einschalten
  an. Prüf `active_low` trotzdem ohne angeschlossene Last.
- Alle Tests bis Stufe 4 ohne Propeller.
- Nachtflug: EU-Drohnen-VO und Auflagen des Vereins vorab klären.

---

## Aufbau des Codes

| Pfad              | Inhalt                                                     |
|-------------------|------------------------------------------------------------|
| `host/lightshow/` | Bridge: `config`, `mapping`, `midi`, `link`, `monitor`, `webui`, `planegen` |
| `host/tests/`     | Testsuite, inklusive der Kreuzprüfungen gegen die Firmware  |
| `firmware/pico/`  | Bodenstation: PPM/SBUS über PIO und DMA, Selbsttest         |
| `firmware/plane/` | Bordcontroller: RC-Eingang, Effekt-Engine, Strips, Relais   |
| `tools/ctest/`    | Firmware-Logik nativ kompiliert, für die Tests              |
| `docs/`           | Ardour-Setup, Sender-Setup, Cue-Liste                       |
| `hardware/`       | Pinbelegung, Pegel, Stückliste, Strombudget                 |

Drei Header sind bewusst frei von SDK-Abhängigkeiten, damit ihre Rechnungen auf
dem PC prüfbar sind: `firmware/pico/src/ppm_frame.h` (Frame-Timing),
`firmware/plane/src/rc_decode.h` (Kanaldekodierung) und
`firmware/plane/src/relay_logic.h` (Relais-Entscheidung und Schaltzeiten). Genau
dort steckt die Logik, deren Fehler in der Luft am teuersten wären.

Das Wire-Protokoll ist an einer Stelle beschrieben:
`firmware/pico/src/protocol.h`. `host/lightshow/protocol.py` ist dessen
Spiegelbild — ändert sich eines, schlägt `test_cross_check.py` fehl.
