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

## Mehrere Modelle an einem Sender

16 Kanäle geteilt durch vier Kanäle je Modell ergibt vier Modelle pro Sender.
Alle Empfänger auf dasselbe Sendermodell binden, dann bekommt jeder alle
Kanäle und die Bordfirmware greift sich über das `base_channel` ihrer Zone den
passenden Block.

```yaml
tx_ports:
  - {id: 0, name: seriell, format: sbus, nchan: 16, frame_us: 7000,
     min_us: 1000, max_us: 2000}

models:
  - {name: eule,  midi_channel: 1, tx_port: 0, tx_offset: 0,  channels: [...]}
  - {name: falke, midi_channel: 2, tx_port: 0, tx_offset: 4,  channels: [...]}
  - {name: bussard, midi_channel: 3, tx_port: 0, tx_offset: 8,  channels: [...]}
  - {name: milan, midi_channel: 4, tx_port: 0, tx_offset: 12, channels: [...]}
```

Dazu in `firmware/plane/src/config.h` je Modell das `base_channel` der Zone auf
`tx_offset + 1` setzen — also 1, 5, 9, 13:

```c
#define ZONE_COUNT 1
#define ZONES { {9}, }   // Bussard: Kanäle 9..12
```

Mit PPM statt SBUS gilt dasselbe, aber ein 16-Kanal-PPM-Frame braucht
mindestens `frame_us: 35400`; die Konfigurationsprüfung sagt das auch.
