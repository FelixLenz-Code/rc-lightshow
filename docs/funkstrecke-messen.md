# Die Funkstrecke vermessen

Der ganze Entwurf steht auf einer Zahl: **wie weit ein Kanalwert auf dem Weg von
der Bridge zum Modell verrutscht.** Daraus folgt, ob 32 Cue-Stufen sicher sind,
wie viele Zonen ein Sender trägt und ob sich eine dichtere Codierung lohnt.

Bisher ist diese Zahl eine Annahme (±13 µs im Kreuztest), keine Messung. Diese
Anleitung macht eine Messung daraus — in zwei Durchläufen, deren Differenz genau
der Beitrag der Funkstrecke ist.

## Was Du brauchst

| Teil | Anmerkung |
|---|---|
| 2× Raspberry Pi Pico | Bodenstation und Modell |
| Sender mit Trainer-Eingang | derselbe, der später fliegt |
| Empfänger, gebunden | mit SBUS-Ausgang |
| 3,5-mm-Klinkenkabel | Ring offen lassen |
| 1 kΩ Widerstand | in die Signalleitung |
| Jumperkabel | für den Referenzlauf GPIO2→GPIO10 |
| 5-V-Versorgung (UBEC) | für den Pico im Modell, an VSYS |

**Keinen USB-Seriell-Adapter.** Der Messmodus schaltet USB-Stdio ein — der Pico
im Modell hängt einfach am Laptop. Abgeschaltet ist USB nur im Flugbuild, weil
der Port in der Luft stromlos ist; auf dem Tisch gilt das nicht.

> Falls Du doch die UART-Konsole nutzen willst: Es muss ein USB-**UART**-Wandler
> sein — CP2102, CP2104, CH340, FT232. Ein **CP2112** ist ein I²C-Baustein und
> kann das nicht. Ein Arduino mit nativem USB (Leonardo, Micro, Pro Micro) geht
> mit einem Dreizeiler als Brücke; beim Uno/Nano muss man den Sketch per RESET
> umgehen. Gebraucht wird nur die Richtung Pico-TX → Adapter-RX plus Masse.

## Vorbereiten

Messfirmware bauen und aufspielen:

```bash
cmake -S firmware/plane -B build/plane-measure -DMEASURE=ON \
      -DPLANE_CONFIG=generated/eule.h
cmake --build build/plane-measure -j4
# BOOTSEL halten, USB anstecken, .uf2 kopieren
```

Beim Start meldet sie sich:

```
lightshow plane: model=eule zones=1 strips=2 relays=2
MEASURE build: eine MEAS-Zeile je RC-Frame, 32 Cue-Stufen, 1000..2000 us
```

Danach eine Zeile je empfangenem RC-Frame:

```
MEAS ms=12345 seq=678 src=1 c1=1487 c2=1502 c3=1000 c4=1500 step=15
```

`seq` zählt **dekodierte** Frames. Der Empfänger hält bei Ausfall seinen letzten
Wert und sagt nichts dazu — an dieser Zahl sieht man Aussetzer trotzdem.

## Durchlauf A — Referenz ohne Funk

Drahtbrücke von **GPIO2 nach GPIO10** an der Bodenstation. Kein Sender, kein
Empfänger.

```bash
cd host && ./.venv/bin/python -m lightshow --sweep eule
```

Der Selbsttest der Bodenstation meldet, was sie tatsächlich ausgibt. Das ist
Deine Nulllinie: der Eigenfehler ohne Funk. Er sollte bei wenigen Mikrosekunden
liegen.

## Durchlauf B — dieselbe Messung über die Luft

```
  Bodenstation                                          Modellseite
  ┌───────────┐                                     ┌─────────────────┐
  │ GPIO2 ────┼─[1k]─▶ Tip ┐                        │  Licht-Pico     │
  │ GND ──────┼──────▶ Sleeve│ 3,5 mm               │                 │
  └───────────┘        Ring ┘ offen!                │  GP5  ◀── SBUS ─┼── Empfänger
        │                    │                      │  GND  ◀─────────┼── Empfänger GND
       USB                   ▼                      │  Pin39 ◀── 5V ──┼── UBEC
        │              ┌──────────┐                 │                 │
        ▼              │  Sender  │ ))) RF (((      │  USB ───────────┼──▶ Laptop
     Laptop            │ Trainer  │ ──────────────▶ └─────────────────┘
                       └──────────┘   Empfänger
```

Beide Picos am Laptop, dann:

```bash
cd host && ./.venv/bin/python -m lightshow --sweep eule --plane-port /dev/ttyACM1
```

Die Bridge fährt 32 Cue-Stufen und danach den Kanalhub in 10-µs-Schritten ab,
je Wert eine Sekunde. Gleichzeitig schreibt sie die Konsole des Modells mit —
**auf derselben Uhr**, sonst ließen sich die beiden Aufzeichnungen nicht
übereinanderlegen. Am Ende steht die Auswertung direkt da.

Zwei Dinge, die sonst Rauschen statt Messwerten ergeben: **gemeinsame Masse**
zwischen Bodenstation und Sender, und zwischen Empfänger und Pico.

## Was herauskommt

```
Frames am Modell:      44.8/s
Systematischer Versatz: +6.0 us (konstant, herausrechenbar)
Schlimmste Abweichung:  19.0 us

=> sicher sind 5 Bit je Kanal (32 Stufen)
```

Vier Zahlen, vier Aussagen:

| Zahl | bedeutet |
|---|---|
| Frames am Modell | wie oft wirklich etwas ankommt; deutlich unter 45/s heißt Aussetzer |
| Punkte ohne Empfang | echte Löcher — die Ursache suchen, bevor der Rest gilt |
| Systematischer Versatz | konstante Verschiebung, lässt sich herausrechnen |
| Schlimmste Abweichung | **die eigentliche Zahl** — daraus folgt das Bitbudget |

Eine Stufe überlebt, solange der Wert in ihrer eigenen halben Bandbreite bleibt.
Der systematische Anteil wird vorher abgezogen, weil ein fester Versatz
korrigierbar ist; was bleibt, ist das Rauschen, das es nicht ist.

| Ergebnis | Folge |
|---|---|
| 6 Bit oder mehr | die Funkstrecke trägt mehr als angenommen |
| 5 Bit | genau die heutige Annahme, alles bleibt wie gerechnet |
| 4 Bit oder weniger | erst die Ursache suchen: Masse, Pegel, `polarity` |

Aufzeichnungen später erneut auswerten:

```bash
./.venv/bin/python -m lightshow --analyse sweep.csv meas.csv
```

## Durchlauf C — PWM und SBUS gleichzeitig

Der Test für ein Modell, das auch geflogen wird. Servos an die PWM-Ausgänge des
Empfängers, SBUS an den Licht-Pico.

**Motor abklemmen, mindestens den Propeller ab.**

1. **Nur Knüppel**, Bridge aus → Servos folgen sauber.
2. **Bridge dazu**, Lichtkanäle ab Kanal 9 → der Pico sieht die Lichtwerte, und
   die Servos bewegen sich **nicht**. Das ist der sicherheitsrelevante Punkt:
   ein Trainer-Kanal, der versehentlich auf Gas oder Ruder gemischt ist, fällt
   genau hier auf.
3. **Bridge abrupt beenden** → Servos bleiben stehen, das Modell geht nach
   500 ms in den bernsteinfarbenen Failsafe-Puls.

Manche Empfänger schalten einen Port zwischen SBUS und Servoausgang um; das
steht im Handbuch. Ob Deiner beides gleichzeitig liefert, beantwortet Schritt 2.

## Ablaufprotokoll zum Abhaken

Der Nachmittag, an dem die Picos ankommen — in der Reihenfolge, in der jede
Stufe die vorherige voraussetzt.

```
[x] 0  Toolchain
       export PICO_SDK_PATH=$HOME/pico-sdk      (gehört in die ~/.bashrc)
       cd host && ./.venv/bin/python -m lightshow --check

[x] 1  Bodenstation flashen
       cmake -S firmware/pico -B build/pico -DCMAKE_BUILD_TYPE=Release
       cmake --build build/pico -j4
       BOOTSEL halten, anstecken, build/pico/lightshow_tx.uf2 kopieren
       -> Status-LED leuchtet dauerhaft, TUI zeigt "link: ... ok"
       -> STAT-Zeile: crc_err=0, bad=0, cfg=1

[x] 2  Referenzlauf ohne Funk           Ergebnis:   0   us Eigenfehler
       Drahtbrücke GPIO2 -> GPIO10
       ./.venv/bin/python -m lightshow --sweep eule
       -> SELFTEST meldet idle, mark, frame passend zur Konfiguration
       gemessen: idle=low (normal) mark=400us frame=22500us nch=8
       88 von 90 Stichproben exakt; die zwei Ausreißer (-5/-6 us) sind ein
       Artefakt des Messeingangs -- dort steht auch mark=394/395us statt 400,
       der ganze Rahmen liest kurz, nicht der Kanal.

       ACHTUNG: --sweep gibt die SELFTEST-Zeilen nicht aus. run_sweep in
       host/lightshow/__main__.py sammelt sie in link.status_lines ein und
       verwirft sie. Diese Zahl stammt aus einem eigenen Skript.

[x] 3  Messfirmware flashen
       ./.venv/bin/python -m lightshow --generate eule
       cmake -S firmware/plane -B build/plane-measure -DMEASURE=ON \
             -DPLANE_CONFIG=generated/eule.h
       cmake --build build/plane-measure -j4
       -> beim Start: "MEASURE build: eine MEAS-Zeile je RC-Frame"

[x] 4  Funkstrecke aufbauen
       Klinke an den Trainer-Eingang, Ring offen, Masse gemeinsam
       Sender: Trainer-Kanäle auf die Lichtkanäle mischen, NICHT auf Gas/Ruder
       Empfänger SBUS -> Pico GP5, Masse gemeinsam, 5 V an Pin 39

       Der Modell-Pico hing am USB; ein UBEC war nicht nötig, weil die
       Messfirmware ohnehin USB-Stdio einschaltet. Der Empfänger hatte eine
       eigene Versorgung, Masse lag über die SBUS-Leitung gemeinsam.
       Zwei Kanalnummerierungen nicht verwechseln: die Bodenstation speist
       Trainer-EINGANGSkanäle, der Empfänger gibt Sende-AUSGANGSkanäle aus.
       Was dazwischen liegt, macht der Mischer im Sender.

[x] 5  Messlauf über die Luft                          gemessen 17.08.2026
       ./.venv/bin/python -m lightshow --sweep eule --plane-port /dev/ttyACM1

       Frames am Modell .........  39,4 /s      (16-Kanal-PPM, 35,5 ms Rahmen)
       Punkte ohne Empfang ......     0
       Systematischer Versatz ...  -0,3 us      (konstanter Anteil allein)
       Schlimmste Abweichung ....  13,1 us      -> 5 Bit, so gerechnet
       => sichere Bits ..........     7          nach Abzug der Verstärkung

       Aufbau: FrSky Tandem X14 RS, Trainer per Kabel, Schülerkanäle 9-16
       auf Sendekanäle 9-16 durchgereicht. Licht liegt auf 9-16 (2 Zonen).

[ ] 6  Koexistenz PWM + SBUS            (Propeller ab!)
       [ ] nur Knüppel: Servos folgen sauber
       [ ] Bridge dazu: Licht bewegt sich, Servos NICHT
       [ ] Bridge beenden: Servos stehen, Modell pulst bernstein

[ ] 7  Reichweite (optional, aber die interessante Zahl)
       Messlauf auf 50 m / 150 m / 300 m wiederholen
       -> ab welcher Entfernung fallen Frames aus?
```

## Was die Messung vom 17.08.2026 ergeben hat

Die entscheidende Beobachtung steht in der Spalte *Streuung*: der Fehler ist
keine Wolke, sondern eine **Gerade**. +12 µs am unteren Ende, null bei etwa
1490 µs, −12 µs am oberen. Von Messung zu Messung schwankt dagegen fast nichts.

Legt man statt eines konstanten Versatzes eine Gerade durch die 3690
Einzelmessungen, trennen sich die beiden Anteile sauber:

| | schlimmster Rest | sichere Bits | Stufen |
|---|---|---|---|
| nur Versatz — so rechnet `--analyse` heute | 13,1 µs | 5 | 32 |
| Versatz **und** Verstärkung | 2,1 µs | 7 | 128 |

```
Verstaerkung a = 0,97622   (-2,38 %)   ->  aus 1000 us Hub werden 976 us
Versatz     b = +35,3 us
Standardabweichung um die Gerade: 0,47 us
```

Die −2,38 % sind eine Konstante der Codierungskette, nicht Rauschen: SBUS
überträgt ganze Zahlen, und die Rückrechnung in Mikrosekunden trifft den Maßstab
um 2,4 % daneben. Ein fester Faktor ist genauso herausrechenbar wie ein fester
Offset — die heutige Auswertung zieht aber nur den Offset ab und verbucht den
Faktor als Abweichung. **Deshalb sagt das Werkzeug 5 Bit, wo 7 drin sind.**

Zwei Einschränkungen, damit daraus keine zu große Zahl wird:

- Gemessen wurde **einmal, auf dem Tisch, mit einem Empfänger**. Dass der Faktor
  über Temperatur, Zeit und andere Empfänger konstant bleibt, ist plausibel
  (er folgt aus der Codierung), aber nicht nachgewiesen.
- Wer die Verstärkung herausrechnet, muss sie auch **kalibrieren** — sonst gilt
  weiter die 5-Bit-Zahl. Solange das nicht passiert, bleibt es bei 32 Stufen.

Offen: `--analyse` sollte eine Gerade anlegen statt nur den Mittelwert
abzuziehen, und beide Zahlen ausweisen — mit und ohne Verstärkungskorrektur.

**Was danach entschieden ist:** Steht in Zeile 5 eine 6 oder mehr, trägt die
Funkstrecke den Bus-Modus mit voller Breite (8 Zonen statt 4, Cue-Takt
unverändert 22 ms). Steht dort eine 5, rechnet sich der Bus wie vorgerechnet.
Steht dort 4 oder weniger, erst die Ursache suchen, bevor irgendetwas gebaut
wird.

Die Zahlen bitte hier eintragen und die Datei committen — dann steht später
nachvollziehbar da, worauf der Entwurf beruht.

## Der Sender reicht den Trainer nicht immer durch

Am Abend des 17.08.2026, beim Hardwaretest des Bus-Modus, tauchte etwas auf, das
der Messlauf am Nachmittag noch nicht zeigte: **rund 15 % der Rahmen kamen nicht
von der Bodenstation, sondern vom Sender selbst.** Die FrSky Tandem X14 RS
wendete den Trainer-Eingang zeitweise nicht an und legte ihre eigenen
Kanalwerte auf die Leitung. Sie meldete es auch selbst, als „LS-System ohne
Funktion".

Woran man es erkennt:

- Werte **unterhalb von `min_us`** — die kann die Bodenstation nicht senden,
  `ports_set_channels()` klemmt jeden Wert in den konfigurierten Hub
- **alle acht Kanäle gleichzeitig** falsch, nicht einzelne
- die Werte **wandern mit den Knüppeln** des Senders

Ausgeschlossen wurde: Klinkenkabel und Steckkontakt, der 1-kΩ-Widerstand in der
Signalleitung (ohne ihn dasselbe Bild), die Rahmenlänge (27000 bis 50000 µs,
überall dieselbe Quote) und das Sendermodell (ein neu angelegtes verhielt sich
gleich). Der Nachmittagslauf über 5263 Rahmen hatte **0,02 %** — es ist also
nichts, was der Aufbau von sich aus mitbringt.

Zwei Nebenbefunde aus derselben Messreihe:

| Rahmenlänge | Ergebnis |
|---|---|
| bis ~35,5 ms | Daten kommen sauber an |
| ab ~42 ms | **88 % Müll** — der Trainer-Eingang der X14 steigt aus |

Und: die Prüfregel `nchan * max_us + sync_us + 3000` ist konservativer als
nötig. Sie nimmt alle Kanäle auf Maximum an; stehen die ungenutzten Kanäle 1–8
fest auf `min_us`, reicht auch ein deutlich kürzerer Rahmen. Bei 27000 µs statt
35400 kamen die Daten fehlerfrei an.

## Wenn nichts ankommt

| Symptom | zuerst prüfen |
|---|---|
| keine MEAS-Zeilen | Messfirmware geflasht? Richtiger `/dev/ttyACM*`? |
| `src=0` | keine gültigen SBUS-Frames — Verkabelung, gemeinsame Masse |
| Werte stehen fest | Sender mischt den Trainer-Eingang nicht auf die Kanäle |
| Frames weit unter 45/s | Reichweite, Antenne, oder der Sender sendet langsamer |
| Werte unter `min_us` | der Sender wendet den Trainer-Eingang nicht an, siehe oben |
