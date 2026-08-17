# Bus-Modus

Normal trägt eine Zone vier eigene RC-Kanäle — Effekt, Farbe, Helligkeit, Tempo.
Acht Kanäle sind damit zwei Zonen, und mehr geht nicht.

Im Bus-Modus tragen dieselben acht Kanäle **einen codierten Rahmen**: eine
Zonenadresse, den Zustand dieser Zone, und ein Bit je direkt geschaltetem
Relais. Die Zonen kommen reihum dran, eine je RC-Rahmen. So bekommt ein Modell
mehr Zonen als es Kanäle hat — bezahlt wird in **Wartezeit**, nicht in Kanälen.

## Wann er sich lohnt

| | ohne Bus | mit Bus |
|---|---|---|
| Zonen bei 8 freien Kanälen | 2 | bis 8 |
| Aktualisierung je Zone | jeder Rahmen | jeder n-te Rahmen |
| Relais unabhängig schaltbar | nein | ja, je eins pro Bit |
| Fremde Rahmen erkannt | nein | ja, siehe unten |

Ein Relais, das ohnehin einem Effekt folgen soll (`pixel`, `brightness`, `cue`),
braucht den Bus **nicht** — es wird an Bord aus dem Zonenzustand abgeleitet und
kostet nichts über die Luft. Bits kostet nur, was unabhängig von der Zone
geschaltet werden soll.

## Wie der Rahmen aussieht

Acht Kanäle, je 5 Bit — genau die Quantisierung, die der Cue-Kanal ohnehin
benutzt. Ein Symbol *ist* eine Cue-Stufe, es muss also nichts Neues über die
Funkstrecke überleben, was nicht schon vorher darüber musste.

```
  Kanal   1     2     3     4     5     6     7     8
        [ Daten: 6 Symbole = 30 Bit    ][ Parität ]
                                          RS(8,6)
```

Die 30 Bit Nutzlast, von vorn:

| Feld | Bit | |
|---|---|---|
| Erkennungsmuster | 2 | fest, wird vor allem anderen geprüft |
| Relais | R | ein Bit je Bus-Relais, in **jedem** Rahmen |
| Zonenadresse | A | `ceil(log2(Zonen))`, bei einer Zone null |
| `cue` | 5 | 32 Stufen, wie die Cue-Liste |
| `hue` | 6 | 64 Farbtöne |
| `brightness` | 8 | volle 256, damit Fades glatt bleiben |
| `param` | 5 | 32 Stufen |
| Reserve | Rest | immer null |

Daraus folgt die Regel, die alles begrenzt: **R + A ≤ 4.**

Die Relaisbits liegen bewusst in jedem Rahmen und nicht bei der Zone. Ein Relais
ist ein Ereignis; acht Rahmen darauf zu warten wäre sichtbar.

## Warum Reed-Solomon — und warum es *nicht* korrigiert

Die Fehler dieser Funkstrecke sind keine verstreuten Bitfehler, sondern **ganze
Kanäle, die als Block eine Stufe danebenliegen** — so hat es die Messung vom
17.08.2026 gezeigt (`docs/funkstrecke-messen.md`). Ein symbolorientierter Code
passt darauf; GF(32) fasst 5-Bit-Symbole exakt.

Mit zwei Paritätssymbolen kann man **entweder einen Fehler korrigieren oder
zwei erkennen** — nicht beides. Welches davon richtig ist, hat der
Hardwaretest am selben Tag entschieden, und die Antwort war nicht die, die man
beim Entwurf am Schreibtisch wählt:

| | akzeptiert von allen möglichen Rahmen |
|---|---|
| korrigierend | **24 %** — alles im Abstand 1 zu einem Codewort, das sind 8·31+1 = 249 Wörter je Codewort |
| erkennend | **0,1 %** — nur Codewörter selbst, eines von 1024 |

Das zählt, weil auf dieser Leitung **fremde Rahmen unterwegs sind**: ein Sender,
der seinen Trainer-Eingang zeitweise nicht anwendet, legt stattdessen seine
eigenen Kanalwerte darauf. Der korrigierende Dekoder nahm sie an und
überschrieb damit eine Zone.

Was die Korrektur dagegen einbrachte: **ein einzelner Symbolfehler in 1233
Rahmen.** Ein Zehntel Prozent Durchsatz gegen Faktor 249 an Falschannahmen.
Deshalb ist die Erkennung die Vorgabe. `BUS_CORRECT` schaltet die Korrektur
wieder ein — für eine Strecke, auf der Symbolfehler das eigentliche Problem
sind und nichts Fremdes hinkommt.

Ein Rahmen, der abgewiesen wird, ändert gar nichts: die Bordfirmware behält den
letzten guten Zustand. Den zu halten ist immer besser, als auf eine Vermutung
hin zu handeln.

## Warum zusätzlich ein Erkennungsmuster

Weil die Prüfsumme allein nicht reichte. Der Ersatzrahmen, den die FrSky X14 auf
die Leitung legte, war ein **echtes gültiges Codewort** — Syndrome exakt null.
Ein Zufall von 1:1024, der aber nichts nützt, wenn die Quelle sich wiederholt:
ein wiederkehrender Fremdrahmen kommt entweder immer durch oder nie. Dieser kam
immer durch.

Zwei feste Bits am Anfang jedes Rahmens weisen drei von vier fremden Rahmen
zusätzlich ab. Sie kosten einen Relais-Steckplatz in den engeren
Konfigurationen. Sicher machen sie die Leitung nicht — gegen einen hartnäckigen
Zufall hilft nichts —, aber sie verschieben ihn von „jeder siebte Rahmen" auf
„alle paar tausend".

**Die eigentliche Lösung bleibt, dass der Sender den Trainer-Eingang
durchreicht.** Unsere Seite kann nur dafür sorgen, dass ein Fremdrahmen keinen
Schaden anrichtet.

## Cue 31 ist reserviert

Ein Rahmen adressiert eine Zone. Bliebe es dabei, könnte ein festgehaltener
Failsafe-Rahmen — den die Bodenstation sendet, wenn der Host ausfällt — immer
nur *eine* Zone dunkel machen, und der Rest des Modells stünde hell da.

Deshalb gibt es ein **„alles aus, alle Zonen"** auf der Leitung. Es braucht
aber *drei* Felder gleichzeitig: Cue-Stufe 31 **und** Farbton auf Maximum
**und** Tempo auf Maximum.

Der erste Entwurf hing nur an der Cue-Stufe, und das ging auf dem Tisch prompt
schief: der Fremdrahmen des Senders trug lauter Null-Bits mit Cue 31 — genau
das, worauf Müll am ehesten fällt — und schaltete das Modell in 15 % der Rahmen
komplett dunkel. Sechzehn bestimmte Bits sind ungleich schwerer zufällig zu
treffen, und kollidieren kann nichts: Cue 31 ist auf der Leitung ohnehin
reserviert.

`docs/cues.md` hält die Stufen 11–31 als Reserve frei, das kostet also nichts.
Blackout und Failsafe senden genau diesen Rahmen und wirken sofort, statt eine
ganze Runde zu brauchen.

## Zwei Kanalnummerierungen

Nicht verwechseln — das ist die häufigste Verwirrung an dieser Stelle:

```
Bodenstation ──PPM──▶ Trainer-EINGANG ──Mischer──▶ Sende-AUSGANG ──RF──▶ Empfänger ──SBUS──▶ Pico
                      TR1..TR16                    CH1..CH16
```

`tx_offset` bestimmt **beides zugleich**. Das geht nur auf, solange der Sender
1:1 durchreicht — bei Felix' FrSky Tandem X14 RS sind die Schülerkanäle 9–16 auf
die Sendekanäle 9–16 gelegt, und genau darauf beruht die Konfiguration.

## Einrichten

In der Web-Oberfläche unter **Modelle**: der Abschnitt *Bus-Modus* zeigt eine
Matrix mit Zonen nach unten und Bus-Relais nach rechts, in den Feldern die
Wartezeit je Zone. Blass heißt: langsamer als `bus_latency_limit_ms` (Vorgabe
150 ms). Verboten ist nichts — die Entscheidung bleibt beim Menschen.

Für ein neues Modell führt der Wizard (**＋ Neues Modell**) durch Fernsteuerung,
Zonen, LED-Ausgänge und Relais und legt dieselbe Matrix im zweiten Schritt vor.

In `show.yaml` sieht es so aus:

```yaml
  - name: eule
    tx_offset: 8
    bus:
      enabled: true
      relays:
        - {name: rauch, cc: 100}
        - {name: blitz, cc: 101}
    channels:
      # vier je Zone, so viele Gruppen wie Zonen
    plane:
      relays:
        # `arg` ist der Steckplatz in bus.relays, nicht ein Pixel oder Cue
        - {name: rauch, pin: 7, source: bus, arg: 0, active_low: true}
```

Ein Bus-Relais wird über seinen eigenen Control-Change geschaltet: ab 64 an,
darunter aus.

## Was die Wartezeit wirklich ist

`Zonen × Rahmenlänge`. Bei 16-Kanal-PPM (35,5 ms) und vier Zonen also 142 ms.

Die Effekte selbst laufen an Bord autonom mit `RENDER_HZ`; es geht nur um den
Moment des **Umschaltens**. Bei 120 bpm liegt ein Beat 500 ms auseinander — 142
ms sitzen hörbar am Schlag, 284 ms nicht mehr sicher.

Liegt das Licht auf den Kanälen 1–8 statt 9–16, ist der Rahmen 22,5 ms lang und
sechs Zonen kommen auf 135 ms. Die Rahmenlänge ist der Hebel, nicht der Code.

## Der Ausweg, falls die Rahmenzeit einmal stört

Die 35,5 ms kommen nicht vom Bus, sondern davon, dass 16 PPM-Kanäle nun einmal
so lange brauchen. Sie sind der Grund, warum sechs oder acht Zonen über der
Latenzgrenze liegen — und sie sind auch der Grund, warum der Trainer-Eingang des
Senders so viel zu tun hat.

**SBUS statt PPM in den Sender** würde beides auflösen. Die Bodenstation kann es
bereits: `format: sbus` steht in `show.yaml` auskommentiert bereit, `ports.c`
hat den Sender dafür. Es wäre eine Konfigurationsänderung, kein Umbau.

| | PPM, 16 Kanäle | SBUS |
|---|---|---|
| Rahmenlänge | 35,5 ms | 7 ms |
| Latenz bei 4 Zonen | 142 ms | 28 ms |
| Latenz bei 8 Zonen | 284 ms | 56 ms |

Alle acht Zonen lägen damit innerhalb der 150-ms-Grenze, und die PPM-Dekodierung
im Sender — die derzeit rund 15 % der Rahmen verliert — entfiele ersatzlos.

Was dafür nötig wäre, Stand 17.08.2026, recherchiert in den FrSky-Quellen:

- **Nicht an der 3,5-mm-Trainerbuchse.** Die kann nur CPPM; der Wunsch nach SBUS
  dort ([Issue #784](https://github.com/FrSkyRC/ETHOS-Feedback-Community/issues/784))
  wurde anders umgesetzt.
- **Am S.Port-Stecker**, neu in EthOS **26.1.0**: *„SBUS Input support added on
  the S.Port connector"*
  ([Issue #5677](https://github.com/FrSkyRC/ETHOS-Feedback-Community/issues/5677)).
- **Mindestens RC6**, denn davor ließ EthOS im Trainer nur 8 statt 16 SBUS-Kanäle
  zu. 26.1.0 stand am 15.08.2026 bei RC8, X14-Builds sind dabei.
- Die 5-V-Versorgung am S.Port ist einzeln abschaltbar — sie gehört **aus**, der
  Pico versorgt sich selbst.
- Ungeprüft: S.Port ist invertiert und halbduplex bei 3,3 V. Die `polarity`-
  Einstellung deckt die Invertierung ab, der Rest gehört vor dem ersten Versuch
  ins Handbuch.

## Grenzen, die zu kennen sind

- **Nur SBUS.** Der Bus-Dekoder liest acht Kanäle; über die vier PWM-Drähte
  eines Empfängers ohne SBUS geht das nicht. Die Firmware prüft das.
- **Ein einziger kaputter Kanal** lässt den Rahmen durchfallen, solange
  `BUS_CORRECT` nicht gesetzt ist. Gemessen kostet das rund 5 % der Rahmen —
  bezahlt dafür, dass fremde Rahmen draußen bleiben.
- **Das Zerreiß-Fenster** in der Bodenstation ist geschlossen:
  `ports_set_channels()` sperrt den DMA-Interrupt, während es die acht Werte
  schreibt. Sonst könnte ein Rahmen halb alte und halb neue Symbole enthalten —
  zwei falsche Symbole, einer zu viel.
- **`RELAY_SRC_CHANNEL` ergibt im Bus-Modus keinen Sinn**: es gibt keine
  schlichten RC-Kanäle mehr, die acht sind Codewort. Die Prüfung lässt es
  stehen, aber der Wert wäre Unsinn.
