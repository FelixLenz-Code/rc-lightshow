# Ardour-Setup

Die Show entsteht als MIDI-Automation. Ein Track je Flugzeug, vier
Automationsspuren je Track — mehr Struktur braucht es nicht.

## 1. Bridge starten

```bash
cd host
./.venv/bin/python -m lightshow
```

Die Bridge legt einen virtuellen ALSA-MIDI-Eingang namens `lightshow` an. Der
existiert nur, solange die Bridge läuft — also zuerst starten, dann in Ardour
verbinden.

Prüfen:

```bash
aconnect -l | grep -i lightshow
```

## 2. Tracks anlegen

Je Flugzeug ein MIDI-Track:

1. `Track → Add Track` → MIDI-Track, ohne Instrument.
2. Ausgang des Tracks im Routing-Grid mit `lightshow` verbinden.
3. Den MIDI-Kanal des Tracks auf den Wert aus `show.yaml` festlegen
   (`midi_channel`) — Track-Kontextmenü, Channel-Einstellungen, ausgehenden
   Kanal erzwingen. Ohne das landen alle Tracks auf Kanal 1 und steuern
   dasselbe Modell.

## 3. Automationsspuren

Pro Track vier Spuren, passend zu `show.yaml`:

| Spur         | Controller           | Kurvenform                        |
|--------------|----------------------|-----------------------------------|
| `cue`        | CC 20                | Stufen, keine Rampen              |
| `hue`        | CC 21                | frei                              |
| `brightness` | CC 22 (+ CC 54)      | Rampen — das sind die Fades       |
| `param`      | CC 23                | frei                              |

`A` am Track öffnet die Automation, dann den Controller wählen. Automationsmodus
auf **Play**, sonst wird nichts gesendet.

`cue` ist quantisiert: 32 Stufen über den Reglerweg. Die Bridge legt jeden Wert
in die Mitte seiner Stufe, deshalb hier **Stufen zeichnen, keine Rampen** — eine
Rampe würde beim Durchlaufen alle Effekte dazwischen kurz auslösen.

### 14 Bit für Fades

`brightness` nutzt CC 22 als MSB und CC 54 als LSB. Zeichnet man nur CC 22,
funktioniert das Dimmen bereits, hat aber 128 Stufen — bei sehr langsamen Fades
sichtbar als Treppe. Für ganz weiche Verläufe zusätzlich CC 54 automatisieren.

## 4. Blackout

CC 119 mit Wert ≥ 64 auf einem beliebigen Kanal setzt sofort alles auf Failsafe.
In der TUI der Bridge macht `b` dasselbe.

Ardour sendet beim Stoppen All-Notes-Off; die Bridge nimmt das als „zurück auf
Failsafe" für den betroffenen Kanal. Die Show bleibt also nach dem Stopp nicht
stehen und leuchtet weiter.

## 5. Timing

Gesamtlatenz unter 40 ms: MIDI, USB und ein PPM-Frame von 22,5 ms. Für Licht zu
Musik unkritisch.

`global_offset_ms` in `show.yaml` verzögert das Licht, falls es zu früh wirkt.
Vorziehen geht nicht — dafür stattdessen das Audio in Ardour nach hinten
schieben.

## 6. Arbeiten ohne Hardware

```bash
./.venv/bin/python -m lightshow --dry-run
```

Die TUI zeigt für jedes Modell die Kanalwerte in Mikrosekunden, bei `cue`
zusätzlich die erkannte Stufe. Damit lässt sich die komplette Show am
Schreibtisch bauen und prüfen, bevor ein Sender angeschlossen wird.
