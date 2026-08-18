# Lightshow

Musiksynchrone Lichtshow mit Modellflugzeugen. Die Show wird im Browser gebaut —
Musik und Effektspuren oben, Lichtspuren je Modell darunter. Die Bridge spielt
die Musik selbst und ist damit die Uhr; sie setzt die Lichtspuren in RC-Kanäle
um, ein RP2040 speist sie als PPM oder SBUS in die Lehrer/Schüler-Buchse von bis
zu acht Fernsteuerungen, und im Modell erzeugt ein zweiter Mikrocontroller
daraus die eigentlichen Lichteffekte.

```
Browser ──▶ host/ ──┬──▶ Soundkarte
 Editor     Bridge  │      Musik
                    └──USB──▶ firmware/pico/ ──Klinke──▶ Sender ──RF──▶ Empfänger
                                8× PPM/SBUS    Trainer                     │
                                                                           │
                                                       firmware/plane/ ◀───┘
                                                        Effekt-Engine
                                                             │
                                                       WS2812 + Relais
```

**Inhalt**

1. [Konzept](#konzept)
2. [Stand des Projekts](#stand-des-projekts)
3. [Bedienoberfläche](#bedienoberfläche)
4. [Hardware](#hardware)
5. [Installation](#installation)
6. [Konfiguration](#konfiguration)
7. [Show-Editor](#show-editor)
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

### Ein Modell, ein Empfänger, ein Sender

Jedes Flugzeug hat seinen **eigenen Empfänger**, gebunden an seine **eigene
Fernsteuerung**. Die Show erreicht dieses Modell nur über den Trainer-Eingang
genau dieses Senders. Ein Modell heißt also: ein Empfänger, ein Sender, eine
PPM-Buchse, ein Ausgang am Signalgenerator.

Genau deshalb hat die Bodenstation **acht Ausgänge** (GPIO2–GPIO9). Acht
Modelle heißen acht Sender, acht Klinkenkabel, acht Ports:

```
       Bridge
         │
    ┌────┴────┬─────────┬─────────┐
  Port 0    Port 1    Port 2    Port 3     (GPIO2, 3, 4, 5 …)
    │         │         │         │
  Sender A  Sender B  Sender C  Sender D   (Trainer-/PPM-Buchse)
    │         │         │         │
  Empf. A   Empf. B   Empf. C   Empf. D
    │         │         │         │
   eule     falke     bussard    milan
```

Die vier Kanäle je Modell liegen damit normalerweise auf **Kanal 1–4 seines
eigenen Senders**, `tx_offset` bleibt 0. Höher wird es nur in zwei Fällen: ein
Modell mit **mehreren Zonen** belegt je Zone vier Kanäle (Zone 0 auf 1–4, Zone 1
auf 5–8), und wer zwei Empfänger bewusst auf dasselbe Sendermodell bindet, kann
sie sich einen Sender teilen lassen. Der Normalfall ist das nicht.

---

## Stand des Projekts

**Fertig und automatisiert getestet:**

- Show-Editor mit Audiospuren, Lichtspuren und Projektverwaltung; die Bridge
  spielt die Musik und liefert die Uhr
- Bridge läuft, end-to-end mit echtem ALSA-MIDI geprüft
- Beide Firmwares kompilieren warnungsfrei (`-Wall -Wextra` auf den eigenen Targets)
- Web-UI mit Live-Status, Modelleditor, Anschlussübersicht sowie Bauen und
  Aufspielen der Firmware
- 150 Tests, darunter ein Abgleich der C- gegen die Python-Implementierung des
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

Die Oberfläche ist ein festes Anwendungsfenster mit vier Ansichten in der
Leiste links — kein Framework, kein Bundler, vier Dateien in
`host/lightshow/web/`. Dunkel ist der entworfene Zustand, weil damit nachts auf
dem Platz gearbeitet wird; der Knopf unten links schaltet auf hell.

**Sie zeigt Licht.** Die Effekt-Engine der Bordfirmware ist nach JavaScript
portiert, also rechnet der Browser dasselbe Muster wie der Controller im Rumpf.
Das trägt die ganze Bedienung: Ein Effektblock in der Timeline zeigt seinen
eigenen Effekt laufend an, der Effekt-Wähler ist ein Raster aus elf laufenden
Vorschauen statt einer Klappliste, und in der Bühnen-Ansicht steht je Modell ein
LED-Streifen, der zeigt, was dieses Flugzeug gerade macht.

> Diese Vorschau ist nur etwas wert, wenn sie stimmt. `tools/ctest/effect_dump.c`
> übersetzt die echte `effects.c` und `host/tests/test_effects_preview.py`
> vergleicht beide Pixel für Pixel über alle Cues, Farbtöne, Tempi und
> Pixelzahlen. Läuft die Portierung weg, schlägt der Test fehl.

**Show** — der Editor. Timeline mit Audiospuren und Lichtspuren, Spurköpfe
links, Inspektor rechts. Spurkopf und Inspektor nennen die Leuchtmittel, die
eine Lichtspur wirklich ansteuert (`flaeche_links + flaeche_rechts · 60 Pixel`),
und zeigen je Block, welche Relais der Effekt schaltet. Ausführlich unter
[Show-Editor](#show-editor).

**Bühne** — je Modell und Zone eine Karte: der laufende LED-Streifen, der Name
des Effekts, Farbton, Helligkeit und Tempo als Balken, darunter aufklappbar die
Rohwerte in Mikrosekunden. Modelle ohne Signal pulsen bernsteinfarben — genau
wie das echte Flugzeug im Failsafe. Darunter die Verbindungen: ob die DAW
verbunden ist (über `aconnect` ausgelesen, also die echte Verbindung, nicht nur
„es kommt was an“) und ob die Bodenstation hängt.

**Modelle** — je Modell eine Karte mit seiner **Sender-Buchse**, den LED-Strips,
Relais und Positionslichtern. Doppelt vergebene GPIOs werden schon beim Tippen
rot markiert, samt Hinweis, wer den Pin sonst benutzt; zwei Modelle auf derselben
Sender-Buchse ergeben eine Warnung. Beim Speichern läuft dieselbe Prüfung wie
beim Start, Fehler kommen im Klartext zurück („GPIO 5 wird von SBUS und Strip
'flaeche_links' benutzt"). Die Vorversion bleibt als `show.yaml.bak` liegen.

> Solange eine Show läuft, ist die Bearbeitung hier **gesperrt**. Das verhindert,
> dass sich die Zuordnung mitten in einer Show verschiebt.

**Anschluss** — je Modell eine Tabelle, wo was an den Pico im Flieger kommt,
inklusive **physischer Pinnummer** auf der Platine, dazu der geschätzte
LED-Strom und die fertige `config.h`. Ein Knopf schreibt sie nach
`firmware/plane/generated/<modell>.h`.

**Firmware bauen und aufspielen** — im selben Tab, ohne Terminal. Die UI prüft
vorher die Toolchain und sagt konkret, was fehlt, statt einen Compiler-Fehler zu
zeigen. Der Build läuft im Hintergrund, das Log steht live auf der Seite.

Beim Aufspielen unterscheiden sich die beiden Boards, und das lässt sich nicht
wegprogrammieren:

| Board | Weg in den Bootloader |
|---|---|
| **Bodenstation** | macht die UI selbst — der Pico hat USB-Stdio, und die SDK-Vorgabe „Reset über Baudrate 1200“ ist aktiv. Kein picotool, kein sudo, keine udev-Regeln. |
| **Pico im Flieger** | von Hand: BOOTSEL halten, USB anstecken, loslassen. Dort ist USB-Stdio abgeschaltet (im Flug ist der Port ohnehin stromlos), also meldet sich das Board gar nicht am Rechner. |

Sobald ein Board im Bootloader hängt, erscheint es als Laufwerk `RPI-RP2` und
die UI kopiert die `.uf2` hinüber — ein reiner Dateikopiervorgang. Stecken zwei
Boards gleichzeitig im Bootloader, bricht sie ab statt zu raten.

> Bauen, Flashen und das Schreiben der `config.h` greifen auf den Rechner zu und
> sind deshalb **nur von localhost** erlaubt. Über `--web-host 0.0.0.0` sieht man
> die Oberfläche zwar, aber die Knöpfe antworten mit 403 — und die UI sagt das
> auch, statt sie einfach nicht zu tun.

### Jedes Modell bekommt seine eigene Firmware

Jedes Flugzeug darf andere Lichter haben — andere Strips, andere Pixelzahlen,
andere Relais, andere Pins, andere Kanäle. Aus jedem Modell entsteht ein
eigener Header, ein eigenes Build-Verzeichnis und ein eigenes Image:

```
firmware/plane/generated/eule.h    → build/plane-eule/lightshow_plane_eule.uf2
firmware/plane/generated/falke.h   → build/plane-falke/lightshow_plane_falke.uf2
```

In der UI wählt die Modellauswahl im Anschluss-Tab, was gebaut und aufgespielt
wird. Auf der Kommandozeile derselbe Weg mit `--generate <modell>` und
`-DPLANE_CONFIG=generated/<modell>.h`.

> **Wichtig:** Die Modelle unterscheiden sich nicht nur in den Lichtern, sondern
> auch in der **Pinbelegung**. Ein falsch aufgespieltes Image lässt ein Relais
> etwas anderes schalten, als auf diesem Rumpf angeschlossen ist. Deshalb heißt
> jedes Image nach seinem Modell, und die Bordfirmware meldet beim Start auf der
> Debug-Konsole, für welches Modell sie gebaut wurde:
>
> ```
> lightshow plane: model=eule zones=1 strips=2 relays=2
> ```
>
> Danach steht der Modellname in jeder Statuszeile. Wer nicht mehr weiß, was auf
> einem Board läuft, hängt die Konsole an GP0/GP1 und liest nach.

### Warum die Bordkonfiguration generiert wird

Zum Flieger führt kein Datenweg außer den RC-Kanälen — man kann ihn nicht zur
Laufzeit umkonfigurieren. Deshalb ist die Modelldefinition in `show.yaml` die
einzige Quelle, und daraus entsteht der Header, mit dem die Bordfirmware
übersetzt wird. Auf der Kommandozeile geht dasselbe:

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
| 10–13  | frei                                      |

Versorgung über **VSYS (Pin 39)** und GND (Pin 38) vom UBEC, nicht über VBUS —
so stört ein gleichzeitig gestecktes USB-Kabel beim Einrichten nicht.

Der Empfänger spricht **nur SBUS**. Bleiben die Frames aus, läuft das Modell
ins Failsafe — es gibt keinen zweiten Weg.

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
| `build/pico/lightshow_tx.uf2`    | Pico an der Bodenstation| 42 KB Flash      |
| `build/plane-<modell>/lightshow_plane_<modell>.uf2` | Pico im Modell | 28 KB Flash |

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

## Show-Editor

Im Tab **Show**: oben die Audiospuren, darunter je Modell eine Lichtspur.
Ausführlich in [`docs/show-editor.md`](docs/show-editor.md).

1. Projektnamen eingeben, **Anlegen**. Es entsteht `projects/<name>/` mit zwei
   Audiospuren und einer Lichtspur je Modell und Zone — benannt nach dem Modell,
   nicht nach CC-Nummern.
2. Musik auf eine Audiospur ziehen. Die Datei wird ins Projekt kopiert, damit
   der Ordner für sich allein lauffähig bleibt. WAV, FLAC, OGG und MP3.
3. **＋ Effekt** setzt einen Block am Abspielkopf auf die Lichtspur: Effekt,
   Farbe, Helligkeit, Tempo, Ein- und Ausblendung. Ziehen verschiebt, an der
   Kante längen, <kbd>Entf</kbd> löscht. Kanten rasten am Raster ein, <kbd>Alt</kbd>
   beim Ziehen schaltet das ab.
4. Leertaste startet und stoppt. Klicken oder Ziehen im Lineal setzt den
   Abspielkopf; während der Wiedergabe scrollt die Ansicht mit.
5. Klick auf einen Spurkopf öffnet die Spureinstellungen — Name, Lautstärke,
   stumm, bzw. Modell und Zone. Dort lassen sich Spuren auch löschen; `+A` und
   `+L` über den Köpfen legen neue an.

Blöcke auf einer Spur dürfen sich **nicht überlappen** — eine Zone zeigt immer
genau einen Effekt, weil `cue` ein einzelner Kanal ist. Für einen Übergang den
einen aus- und den nächsten einblenden lassen. Der Editor setzt das selbst
durch: Ein Block lässt sich nicht über seinen Nachbarn schieben, und eine zu
lange Blende wird auf die Blocklänge zurückskaliert. Was sich bauen lässt, lässt
sich also auch speichern.

Während der Wiedergabe ist die Modellkonfiguration gesperrt; der Editor selbst
bleibt bedienbar und Speichern setzt die Wiedergabe nicht zurück.

### Uhr und Synchronität

Die Bridge mischt das Projekt einmal zusammen und spielt es über die Soundkarte.
Ihre Abspielposition ist die Zeitreferenz für die Lichter — Ton und Licht kommen
aus demselben Prozess und derselben Uhr und können nicht auseinanderlaufen. Die
Position wird zwischen den Audio-Callbacks interpoliert und um die
Ausgabelatenz korrigiert, damit sie zu dem passt, was hörbar ist.

**Ohne Audiogerät läuft die Uhr trotzdem**, sodass sich eine Show auch auf einem
Rechner ohne Audio vollständig prüfen lässt.

### MIDI bleibt möglich

Der virtuelle MIDI-Port existiert weiter. Läuft kein Transport, kommen die Werte
von dort — für schnelle Versuche im Hangar oder eine bestehende Ardour-Session
([`docs/ardour-setup.md`](docs/ardour-setup.md)). Startet die Wiedergabe,
übernimmt die Timeline; nach dem Stoppen wieder MIDI. Ohne Umschalter.

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

Dann im Tab **Show** ein Projekt anlegen, einen Effekt-Block setzen und die
Wiedergabe starten. Die Balken müssen den Blöcken folgen, `b` schaltet Blackout.

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

290 Tests. Die interessanten sind keine Unit-Tests, sondern Kreuzprüfungen:
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
| `test_flasher.py`      | Bootloader-Erkennung, Kopiervorgang, Toolchain-Prüfung        |
| `test_timeline.py`     | Effekt-Blöcke, Blenden, Projektformat                         |
| `test_audio.py`        | Mixdown und die Transportuhr, mit und ohne Audiogerät         |
| `test_session.py`      | woher die Kanalwerte kommen, Projektverwaltung                |
| `test_webui.py`        | Auslieferung der Oberfläche, Pfadschutz, die localhost-Sperre  |
| `test_effects_preview.py` | Effektvorschau im Browser gegen die echte `effects.c`      |
| `test_sweep.py`        | Auswertung der Funkstreckenmessung, gegen bekannte Fehler      |

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

### Die Funkstrecke vermessen

Eine Zahl trägt den ganzen Entwurf: wie weit ein Kanalwert unterwegs verrutscht.
Sie ist bisher eine Annahme (±13 µs im Kreuztest), keine Messung. Das Werkzeug
dafür steht bereit und braucht nur die Hardware:

```bash
cmake -S firmware/plane -B build/plane-measure -DMEASURE=ON -DPLANE_CONFIG=generated/eule.h
cd host && ./.venv/bin/python -m lightshow --sweep eule --plane-port /dev/ttyACM1
```

Die Bridge fährt alle Cue-Stufen und den Kanalhub ab, zeichnet die Konsole des
Modells auf derselben Uhr mit und sagt am Ende, wie viele Bit ein Kanal wirklich
trägt. Vollständig in
[`docs/funkstrecke-messen.md`](docs/funkstrecke-messen.md).

### Manuelle Prüfungen

| Was                     | Wie                                                        |
|-------------------------|------------------------------------------------------------|
| MIDI kommt an           | `aconnect -l \| grep lightshow`, dann `aseqdump -p lightshow` |
| Mapping stimmt          | `python -m lightshow --dry-run`                            |
| Konfiguration gültig    | `python -m lightshow --check`                              |
| UI erreichbar           | Bridge starten, `http://127.0.0.1:8765/` öffnen            |
| Bauen aus der UI        | Anschluss-Tab → „Bordfirmware bauen“, Log muss durchlaufen |
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
| `host/lightshow/web/` | Oberfläche: `index.html`, `app.css`, `app.js`, `effects.js` — ohne Bundler |
| `host/tests/`     | Testsuite, inklusive der Kreuzprüfungen gegen die Firmware  |
| `firmware/pico/`  | Bodenstation: PPM/SBUS über PIO und DMA, Selbsttest         |
| `firmware/plane/` | Bordcontroller: RC-Eingang, Effekt-Engine, Strips, Relais   |
| `tools/ctest/`    | Firmware-Logik nativ kompiliert, für die Tests              |
| `docs/`           | Ardour-Setup, Sender-Setup, Cue-Liste, Funkstreckenmessung   |
| `hardware/`       | Pinbelegung, Pegel, Stückliste, Strombudget                 |

Drei Header sind bewusst frei von SDK-Abhängigkeiten, damit ihre Rechnungen auf
dem PC prüfbar sind: `firmware/pico/src/ppm_frame.h` (Frame-Timing),
`firmware/plane/src/rc_decode.h` (Kanaldekodierung) und
`firmware/plane/src/relay_logic.h` (Relais-Entscheidung und Schaltzeiten). Genau
dort steckt die Logik, deren Fehler in der Luft am teuersten wären.

Das Wire-Protokoll ist an einer Stelle beschrieben:
`firmware/pico/src/protocol.h`. `host/lightshow/protocol.py` ist dessen
Spiegelbild — ändert sich eines, schlägt `test_cross_check.py` fehl.
