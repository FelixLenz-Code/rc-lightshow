# Sender-Setup

Jeder Ausgang des Signalgenerators ist einzeln konfigurierbar. Ein anderer
Sender heißt: `tx_ports`-Eintrag in `host/config/show.yaml` anpassen. Kein
Neuflashen, kein Umlöten.

```yaml
tx_ports:
  - id: 0              # Portnummer, id 0 = GPIO2
    name: frsky_ethos
    format: ppm        # ppm | sbus | off
    polarity: normal   # normal | inverted
    nchan: 8
    frame_us: 22500    # Framelänge; bei sbus der Frameabstand
    sync_us: 400       # Breite des PPM-Sync-Pulses
    min_us: 1000
    max_us: 2000
```

Bedeutung von `polarity: normal`:

- **PPM:** positiver Shift — Ruhepegel low, High-Sync-Pulse. Das ist die
  übliche Variante.
- **SBUS:** normales, invertiertes SBUS. `inverted` liefert die nicht
  invertierte Variante, wie sie manche Flugregler wollen.

## FrSky mit Ethos

Der erste Zielsender. Die Vorgabe in `show.yaml` passt bereits.

**Verkabelung** — 3,5-mm-Klinke an der Trainer-Buchse:

| Kontakt | Belegung                                    |
|---------|---------------------------------------------|
| Tip     | Signal, an GPIO2 über 1 kΩ                  |
| Sleeve  | Masse, an Pico-GND                          |
| Ring    | **offen lassen** — dort kann Akkuspannung liegen |

**Im Sender:**

1. Trainer-Eingang auf Master/Jack mit PPM stellen. Die genaue Menübezeichnung
   unterscheidet sich je nach Ethos-Version — gesucht ist die Einstellung, bei
   der dieser Sender sendet und die Kanäle von der Buchse übernimmt.
2. Die Trainer-Kanäle als Quelle auf die **Lichtkanäle** mischen.
3. Im Kanalmonitor prüfen, dass sich die Kanäle mit der Ardour-Automation
   bewegen.

> Trainer-Kanäle niemals auf Gas oder Ruder mischen. Ein Fehler in der Show darf
> das Modell nicht steuern können.

**Wenn sich nichts rührt**, in dieser Reihenfolge:

1. `polarity: inverted` setzen und die Bridge neu starten.
2. `sync_us` auf 300 stellen.
3. 5-V-Puffer (74HCT14) einschleifen — siehe [`../hardware/README.md`](../hardware/README.md).
4. Mit einem zweiten Pico und `tools/ctest` gegenprüfen, dass am Ausgang
   überhaupt das erwartete Signal liegt.

## Andere Marken

Als Ausgangspunkt; im Zweifel `polarity` umschalten und messen.

| Sender                        | format | polarity | sync_us | Bemerkung                    |
|-------------------------------|--------|----------|---------|------------------------------|
| FrSky (Ethos, OpenTX/EdgeTX)  | ppm    | normal   | 400     | 3,3 V genügt                 |
| Graupner / Multiplex          | ppm    | inverted | 300     | oft negativer Shift, 5 V     |
| Futaba                        | ppm    | normal   | 400     | Pegel je Baujahr prüfen      |
| EdgeTX, serieller Trainer     | sbus   | normal   | —       | 16 Kanäle, `frame_us: 7000`  |

Neuen Sender vermessen? `tools/ctest/build/frame_decoder` hilft nur beim
USB-Protokoll. Für das Signal selbst am einfachsten: einen bekannten
Schüler-Sender an ein Oszilloskop oder einen zweiten Pico hängen und Ruhepegel,
Pulsbreite und Framelänge ablesen.

## Ein Sender je Modell

Jedes Flugzeug hat seinen eigenen Empfänger, gebunden an seine eigene
Fernsteuerung. Die Show erreicht ein Modell also **nur über die Trainer-Buchse
genau dieses Senders**. Zwei Modelle heißen zwei Sender, zwei Klinkenkabel und
zwei Ports am Signalgenerator — deshalb hat er acht davon.

```yaml
tx_ports:
  - {id: 0, name: eule_sender,  format: ppm, nchan: 8, frame_us: 22500,
     sync_us: 400, min_us: 1000, max_us: 2000}
  - {id: 1, name: falke_sender, format: ppm, nchan: 8, frame_us: 22500,
     sync_us: 400, min_us: 1000, max_us: 2000}

models:
  - {name: eule,  midi_channel: 1, tx_port: 0, tx_offset: 0, channels: [...]}
  - {name: falke, midi_channel: 2, tx_port: 1, tx_offset: 0, channels: [...]}
```

In der Web-UI steht dieselbe Zuordnung als **Sender-Buchse** an jedem Modell,
und sie warnt, wenn zwei Modelle auf derselben Buchse landen.

## Fliegende Modelle: Licht über die Flugkanäle legen

Ein Modell, das auch geflogen wird, braucht seine Flugkanäle auf demselben
Sender. Beides geht gleichzeitig — der Empfänger gibt die Servokanäle als PWM
aus **und** alle 16 Kanäle über SBUS:

```
                    ┌── PWM 1..8 ──▶ Servos, Motor, Klappen
   Empfaenger ──────┤
                    └── SBUS     ──▶ Licht-Pico (GP5), eine Leitung
```

Der Licht-Pico liest den ganzen SBUS-Rahmen und greift sich über `base_channel`
nur seinen Block. Damit die Blöcke sich nicht überschneiden, muss `tx_offset`
die Flugkanäle überspringen:

```yaml
models:
  - name: eule
    tx_port: 0
    tx_offset: 8        # Kanal 1-8 fliegen, Licht ab Kanal 9
    channels: [ ... ]   # Zone 0 -> Kanal 9-12, Zone 1 -> 13-16
```

Im Sender liegen Knüppel und Schalter auf Kanal 1–8, der Trainer-Eingang auf
Kanal 9–16.

> **Trainer-Kanäle niemals auf Gas oder Ruder mischen.** Ein Fehler in der Show
> darf das Modell nicht steuern können. Das ist der Grund, warum die Lichtkanäle
> oben liegen und nicht unten.

Wieviel für Licht übrig bleibt, ergibt sich daraus direkt — je Zone vier Kanäle:

| Flugkanäle | frei | Lichtzonen |
|------------|------|------------|
| 4          | 12   | 3          |
| 6          | 10   | 2          |
| 8          | 8    | 2          |

Prüfen: Manche Empfänger schalten einen Port zwischen SBUS und Servoausgang um,
ganz kleine haben nur SBUS. Das steht im Handbuch des Empfängers.

`tx_offset` bleibt nur dann 0, wenn das Modell **nicht** geflogen wird — etwa
eine Bodendekoration an einem eigenen Sender.

## Mehrere Zonen an einem Modell

Ein Modell darf Flächen und Rumpf unabhängig ansteuern. Jede **Zone** kostet
vier weitere Kanäle **auf demselben Sender**:

```yaml
models:
  - name: eule
    tx_port: 0
    tx_offset: 0
    channels: [ ... 8 Einträge: Zone 0 auf 1–4, Zone 1 auf 5–8 ... ]
```

Die Bordfirmware greift sich über das `base_channel` der Zone den passenden
Block; der generierte Header setzt das automatisch:

```c
#define ZONE_COUNT 2
#define ZONES { {1}, {5}, }   // Zone 0: Kanäle 1..4, Zone 1: 5..8
```

Ab zwei Zonen lohnt der serielle Trainer-Eingang: SBUS überträgt 16 Kanäle über
eine Leitung. Mit PPM geht es auch, aber ein 16-Kanal-PPM-Frame braucht
mindestens `frame_us: 35400`; die Konfigurationsprüfung sagt das auch.

## Ausnahme: zwei Empfänger an einem Sender

Technisch lassen sich zwei Empfänger auf dasselbe Sendermodell binden. Dann
teilen sich beide Modelle einen Port, und `tx_offset` trennt ihre Kanalblöcke
(0 und 4). Beide Flugzeuge hängen damit an einem Sender — fällt der aus, sind
beide dunkel, und keines lässt sich einzeln steuern. Der Normalfall ist das
nicht; die UI weist deshalb darauf hin.
