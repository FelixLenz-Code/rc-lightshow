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
- Bridge läuft, Editor und Ausgabe end-to-end geprüft
- Beide Firmwares kompilieren warnungsfrei (`-Wall -Wextra` auf den eigenen Targets)
- Web-UI mit Live-Status, Projekt- und Modelleditor, Anschlussübersicht sowie Bauen und
  Aufspielen der Firmware
- 405 Tests, darunter ein Abgleich der C- gegen die Python-Implementierung des
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
./Lightshow-x86_64.AppImage            # oder aus dem Anwendungsmenü
cd host && ./.venv/bin/python -m lightshow    # aus dem Quellbaum
# web interface: http://127.0.0.1:8765/
```

Das AppImage macht die Oberfläche selbst auf, und zwar in einem **eigenen
Fenster ohne Adresszeile und ohne fremde Tabs** — es sieht damit aus wie ein
Programm und hat einen eigenen Platz in der Fensterleiste. Das können alle
Browser der Chromium-Familie über `--app`; gesucht wird nach Brave, Chrome,
Chromium, Edge und Vivaldi, auch als Flatpak. Ist keiner davon da, wird es ein
gewöhnlicher Tab. `LIGHTSHOW_BROWSER` bestimmt den Browser von Hand,
`LIGHTSHOW_BROWSER=tab` erzwingt den Tab. Im Quellbaum steht die Adresse in der
ersten Zeile; `--open-browser` macht es auch dort auf.

**Fenster zu heißt Feierabend.** Hat die Bridge ein eigenes Fenster
aufgemacht, geht sie mit ihm: drei Sekunden nachdem die letzte Ansicht weg ist,
fährt sie herunter. Ein Neuladen zählt nicht — dafür sind die drei Sekunden da —
und ein Handy, das im selben WLAN noch zuschaut, hält sie ebenfalls am Leben.

**Ausschalten von Hand** geht unten links in der Leiste, am Ein/Aus-Zeichen. Das
braucht es, wenn kein Browser für ein eigenes Fenster da war und die Oberfläche
in einem Tab gelandet ist: einen Tab schließt man versehentlich, also folgt die
Bridge ihm nicht. Weil Ausschalten alle Modelle auf Failsafe fallen lässt und
fragt die Oberfläche zweimal — und im zweiten Schritt
liegt *Abbrechen* dort, wo eben noch *Weiter* war, damit zweimal Klicken an
derselben Stelle nicht ausschaltet. Aus dem WLAN heraus ist der Knopf gesperrt.

In beiden Fällen geht die Bridge denselben Weg wie bei Strg-C: Blackout,
Failsafe-Frames, Ports zu.

Sie braucht keine zusätzlichen Pakete — reine Python-Bordmittel. Mit
`--web-host 0.0.0.0` ist sie auch vom Handy im selben WLAN erreichbar,
`--no-web` schaltet sie ab.

**Exportieren fragt, wohin.** Modell und Projekt öffnen einen Speichern-Dialog,
statt in den Download-Ordner zu fallen — im eigenen Anwendungsfenster gibt es
keine Werkzeugleiste, an der eine Download-Meldung hängen könnte. Browser ohne
`showSaveFilePicker`, etwa Firefox, laden weiter wie bisher herunter.

**Blöcke lassen sich über Spuren hinweg ziehen.** Senkrecht gezogen wechselt
ein Effekt die Lichtspur — auch die eines anderen Modells; die Zielspur hebt
sich dabei hervor. Über die Art hinweg geht nichts: ein Relaisblock will eine
Relaisspur, ein Clip eine Audiospur, und ein Lichtblock hätte auf beiden nichts
zu sagen. Ist die gezogene Stelle in der Zielspur belegt, rutscht der Block auf
die erste Lücke dahinter — dieselbe Regel, nach der ein neuer Effekt einrastet.

**Rechtsklick** in der Zeitleiste öffnet ein Menü: Effekt, Relaisblock oder
Musik an der angeklickten Stelle einfügen, Duplizieren, Löschen, Abspielkopf
hierher, Raster an und aus, Spureinstellungen. Es geht auf einem Block, auf
freier Spurfläche, auf dem Spurkopf und auf dem Lineal.

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

**Show** — der Editor. Timeline mit Audiospuren, Lichtspuren und Relaisspuren,
Spurköpfe links, Inspektor rechts. Spurkopf und Inspektor nennen die
Leuchtmittel, die eine Lichtspur wirklich ansteuert (`flaeche_links +
flaeche_rechts · 60 Pixel`); eine Relaisspur nennt Bit, GPIO und
Control-Change. Ein Block auf einer Relaisspur heißt schlicht: hier ist es an.
Ausführlich unter [Show-Editor](#show-editor).

> **Vorschau ↗** öffnet ein eigenes Fenster: jede LED-Kette jedes Modells, mit
> echter Pixelzahl und den Abschnitten dort, wo sie wirklich sitzen. Gedacht für
> den zweiten Bildschirm neben der Timeline, damit sich eine Show ohne
> angeschlossenes Modell beurteilen lässt. Die Pixelabbildung ist dieselbe wie in
> `outputs_show()` der Bordfirmware — Offset, `reverse` und Positionslichter
> inbegriffen. Im Reiter **Modell** liegen dieselben Abschnitte auf einem
> Hochdecker in vier Ansichten, verschiebbar mit der Maus: ein Lauflicht wandert
> dort wirklich über die Fläche. Der Knopf **3D** zeigt dasselbe körperlich und
> drehbar — die vier Ansichten legen den Punkt im Raum fest, wie bei einer
> Dreiseitenansicht, also ist dort nichts zusätzlich einzugeben. Alle fünf
> Ansichten zeichnen mit WebGL denselben Körper; nur die Kamera unterscheidet
> sie, damit keine Ansicht ein anderes Flugzeug meint als die nächste. Welcher
> Körper das ist, sagt der Wizard im ersten Schritt: **Motorflugzeug,
> Segelflugzeug oder Quadrocopter** — das steuert allein die Vorschau, an Bord
> kommt es nie an. Beleuchtet ist der Körper wie im Nachtflug: schwacher Himmel
> von oben, und sonst nur das, was die Streifen selbst auf die Zelle werfen,
> in linearem Licht gerechnet und erst am Schluss für den Bildschirm kodiert.
> Der Regler **Nacht** hellt das Modell auf, wenn ein Streifen genau angesetzt
> werden soll.

**Bühne** — je Modell und Zone eine Karte: der laufende LED-Streifen, der Name
des Effekts, Farbton, Helligkeit und Tempo als Balken, darunter aufklappbar die
Rohwerte in Mikrosekunden. Modelle ohne Signal pulsen bernsteinfarben — genau
wie das echte Flugzeug im Failsafe. Darunter die Verbindung zur Bodenstation.

**Modelle** — eine Liste der Flugzeuge mit ihren Eckdaten: Sender-Buchse,
Kanalblock, Zonen, LED-Ausgänge, Relais, Positionslichter und die
Wartezeit je Zone. Doppelt vergebene GPIOs stehen als Warnung an der Karte.
Mehrere Modelle auf **einer** Sender-Buchse sind erlaubt, solange sich ihre
Kanalblöcke nicht überschneiden; in ein Projekt kommt davon dann nur eines.
Aufgeklappt zeigt jede Karte, wo im Rumpf was angeschlossen wird.

**Exportieren** legt ein Modell als Datei ab, **Importieren …** liest eine
wieder ein. Zwei Konfigurationen, die sich nie begegnet sind, stoßen dabei fast
überall zusammen — beide legen das Licht auf Buchse 1 ab Kanal 9. Das importierte Modell wird deshalb aus dem Weg gerückt
statt abgewiesen, und **jede** Verschiebung wird berichtet: ein still
umnummeriertes Flugzeug ist eines, das auf einem Kanal antwortet, den niemand
erwartet. Die Sendereinstellungen der Datei werden nur verglichen, nicht
übernommen — welche Buchse welche ist, entscheidet die Installation, in die
importiert wird.

Beim **Bearbeiten** steht *Übernehmen* auf jeder Seite des Wizards: ein Modell,
das schon fertig ist, muss zum Speichern nicht erst bis zum letzten Schritt
durchgeblättert werden. Ein neues schon, denn vorher ist es nicht fertig.

Anlegen, Ändern und Entfernen werden **sofort geschrieben und sofort
übernommen** — die Bridge baut ihre Kanalzuordnung neu und schickt der
Bodenstation die neue Port-Einstellung, ohne Neustart. Nur die Bordfirmware
muss danach noch neu generiert und geflasht werden. Läuft gerade eine Show, wird
das Speichern abgelehnt; dann steht ein Punkt am Knopf **Speichern**, und die
Änderung wartet, bis die Wiedergabe steht.

Eingestellt wird nicht hier, sondern im **Wizard** — **＋ Neues Modell** oder
**Bearbeiten** an einer Karte führen in denselben sechsschrittigen Weg
(Bauart, Fernsteuerung, Zonen, LED-Ausgänge, Relais, Positionslichter), dessen
Reiter anklickbar sind. Der erste Schritt fragt zweierlei: **was für ein Modell**
das ist — Motorflugzeug, Segelflugzeug oder Quadrocopter, was allein die Vorschau
betrifft — und **worauf der Pico sitzt**: eine
fertige Platine hat ihre Anschlüsse im Kupfer, also füllt der Wizard die GPIOs
ein, statt danach zu fragen, und legt die LED-Ausgänge gleich an. Wer frei
verdrahtet, wählt *Experte* — dann steht wie bisher jeder GPIO zur Wahl. Ein Ort statt zweier, die sich halb überschneiden und
auseinanderlaufen. Beim Speichern läuft dieselbe Prüfung wie beim Start, Fehler
kommen im Klartext zurück („GPIO 5 wird von SBUS und LED-Ausgang
'flaeche_links' benutzt"). Die Vorversion bleibt als `show.yaml.bak` liegen.

> Solange eine Show läuft, ist die Bearbeitung hier **gesperrt**. Das verhindert,
> dass sich die Zuordnung mitten in einer Show verschiebt.

**Flashen** — der Weg von der Konfiguration auf die Boards, und sonst nichts.
Für die Bordfirmware drei nummerierte Schritte je Modell: `config.h` nach
`firmware/plane/generated/<modell>.h` schreiben, bauen, aufspielen. Darunter die
Bodenstation, die von Modellen nichts weiß. Dazu die Kommandozeile, die dasselbe
tut, und die erzeugte `config.h` zum Nachsehen.

Wo im Rumpf was angeschlossen wird — Tabelle mit **physischer Pinnummer** und
dem geschätzten LED-Strom — steht bei dem Modell, zu dem es gehört: aufklappbar
an dessen Karte im Reiter *Modelle*. Das ist eine Eigenschaft des Flugzeugs, die
sich durch Bauen nicht ändert.

**Firmware bauen und aufspielen** — ohne Terminal. Die UI prüft
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

In der UI wählt die Modellauswahl im Flashen-Tab, was gebaut und aufgespielt
wird. Auf der Kommandozeile derselbe Weg mit `--generate <modell>` und
`-DPLANE_CONFIG=generated/<modell>.h`.

> **Wichtig:** Die Modelle unterscheiden sich nicht nur in den Lichtern, sondern
> auch in der **Pinbelegung**. Ein falsch aufgespieltes Image lässt ein Relais
> etwas anderes schalten, als auf diesem Rumpf angeschlossen ist. Deshalb heißt
> jedes Image nach seinem Modell, und die Bordfirmware meldet beim Start auf der
> Debug-Konsole, für welches Modell sie gebaut wurde:
>
> ```
> lightshow plane: model=eule zones=4 outputs=2 segments=2 relays=3
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

Ein **Raspberry Pi Pico**. Acht Ausgänge auf GPIO2–GPIO9 (Buchse 1–8), einer je
Sender, Status-LED onboard. Sonst nichts — der Selbsttest-Eingang auf GPIO10 ist
entfallen, nachdem er seine Messung geliefert hatte.

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

`firmware/plane/src/config.h` beschreibt die Ausgangsstufe als vier Tabellen:
bis zu **8 WS2812-Ketten**, die **Abschnitte**, in die sie zerfallen, bis zu
**8 Relais** und die Positionslichter. Nur diese Datei wird je Modell angefasst,
und erzeugt wird sie aus `show.yaml`.

```c
/* Die physischen Ketten: pin, Pixel, Beginn im gemeinsamen Bildpuffer. */
#define OUTPUT_COUNT 2
#define OUTPUTS { \
    {2, 30,  0},  /* flaeche_links  */ \
    {3, 30, 30},  /* flaeche_rechts */ \
}

/* Wie die Ketten unter den Zonen aufgeteilt sind. */
#define SEGMENT_COUNT 3
#define SEGMENTS { \
    /* output, ab Pixel, Länge, zone, offset, reverse */ \
    {0,  0, 15, 0, 0, false},  /* linke Fläche außen  -> Zone 1 */ \
    {0, 15, 15, 1, 0, false},  /* linke Fläche innen  -> Zone 2 */ \
    {1,  0, 30, 0, 0, true},   /* rechte Fläche, gespiegelt      */ \
}

#define RELAY_COUNT 2
#define RELAYS { \
    /* pin, zone, source, arg, threshold, active_low, min_on, min_off */ \
    /* pin, active_low, min_on_ms, min_off_ms -- Position ist das Bit */ \
    /* Bit 0: Rauch, Relaismodul  */ {7,  true, 200, 200}, \
    /* Bit 1: Blitz, MOSFET       */ {8, false,   0,   0}, \
}
```

**Ausgang und Zone sind getrennt.** Ein Ausgang ist ein GPIO, eine
PIO-Zustandsmaschine und eine Länge — das, was gelötet wird. Ein Abschnitt ist
ein Stück davon und gehört zu genau einer Zone. Damit kann ein einziger 60er
Streifen vorn Rumpf und hinten Leitwerk sein, ohne zweimal angeschlossen zu
werden. Vorher war beides dieselbe Tabelle, und eine Lötentscheidung bestimmte
eine Lichtentscheidung mit.

**Zonen** bündeln Abschnitte, die denselben Effekt zeigen. Kanäle kosten sie
nicht: acht codierte Kanäle tragen bis zu acht Zonen, siehe
[`docs/bus-modus.md`](docs/bus-modus.md). Was mehr Zonen kosten, ist Wartezeit.

**`offset`** bestimmt, wie Abschnitte zusammenspielen: gleicher Offset spiegelt
sie, fortlaufende Offsets machen aus mehreren eine lange virtuelle Kette, über
die ein Lauflicht durchläuft. **`reverse`** dreht einen verkehrt herum
eingebauten Abschnitt um, damit ein Lauflicht auf beiden Flächen wirklich nach
außen läuft.

**Ein Relais wird über den Bus geschaltet und sonst gar nicht.** Es bekommt ein
eigenes Bit im Rahmen, das in *jedem* Rahmen mitfährt, und einen eigenen
Control-Change: ab 64 an, darunter aus. Es hängt an keiner Zone und folgt keinem
Effekt.

Früher konnte ein Relais seinen Zustand stattdessen an Bord ableiten — aus einem
Pixel, dem Master-Dimmer, einer Cue-Nummer oder einem rohen RC-Kanal. Das kostete
keine Nutzbits, band aber jedes Relais an etwas anderes, das gerade lief, und
zwei Wege bedeuteten für jede Regel über Relais zwei Antworten. Ein Weg, eine
Antwort.

Was das kostet: Adressbits und Relaisbits teilen sich vier Bit. Vier Zonen
brauchen zwei Adressbits und lassen damit **zwei** Relais zu, fünf bis acht Zonen
nur noch eines. Ein Relais, das exakt im Takt eines Strobes blitzt, geht nicht
mehr — ein Bit ist ein Zustand, kein Muster.

`min_on_ms` / `min_off_ms` erlauben den Mischbetrieb: **0** für MOSFETs, **~200**
für mechanische Relais, die dann nur so oft schalten, wie sie es überleben. Bei
Funkausfall fallen alle Relais sofort ab, ohne Rücksicht auf diese Zeiten.

---

## Installation

### Bridge als AppImage

Der normale Weg. Eine Datei, kein Python, keine Pakete:

```bash
sudo apt install libfuse2t64                   # einmalig, Ubuntu 24.04 hat es nicht mehr
chmod +x Lightshow-x86_64.AppImage
./Lightshow-x86_64.AppImage                    # startet und öffnet den Browser
./Lightshow-x86_64.AppImage --install-desktop  # Eintrag im Anwendungsmenü
```

**Keine Leerzeichen im Dateinamen.** AppImageLauncher schreibt den Pfad
unquotiert in das `TryExec` des Menüeintrags, den er anlegt; mit einem
Leerzeichen darin zeigt die Arbeitsfläche den Eintrag gar nicht erst an.

**Es kommt leer.** Keine Modelle, keine Projekte, acht freie Senderbuchsen —
die Beispielshow aus `host/config/show.yaml` bleibt im Quellbaum. Der erste
Weg führt also über *Modelle → ＋ Neues Modell*: der Assistent fragt Bauart,
Fernsteuerung, Zonen, LED-Ausgänge und Relais ab und schaltet dabei die
Senderbuchse an, die das Modell benutzt. Erst danach lässt sich ein Projekt
anlegen — ein Projekt ohne Modell hätte nichts zu steuern.

Ein AppImage bringt seinen Python mit, aber keine Sandbox — und genau das
braucht die Bridge: `/dev/ttyACM*` für die Bodenstation, die Soundkarte für
die Musik, den USB-Stick der Pico im BOOTSEL-Modus. Vom System kommt, wenn du
aus der UI heraus Firmware
bauen willst, die [Firmware-Toolchain](#firmware-toolchain) — eine halbe
Gigabyte Cross-Compiler reist in keinem Image mit. Der Flashen-Tab sagt dir,
was fehlt.

In der Gruppe `dialout` musst du sein, sonst bleibt der Port zu:

```bash
sudo usermod -aG dialout $USER     # danach einmal neu anmelden
```

Ist **AppImageLauncher** installiert, fragt der erste Start stattdessen, ob er
das Image ins System aufnehmen soll — dann macht er den Menüeintrag selbst und
`--install-desktop` erübrigt sich.

Falls der Doppelklick nichts tut, fehlt FUSE: `sudo apt install libfuse2t64`.

### Wo liegen meine Daten

Ein AppImage ist innen schreibgeschützt, die Bridge schreibt aber ständig:
Projekte, geänderte Konfiguration, gebaute Firmware. Beim ersten Start legt sie
deshalb einen Arbeitsbaum an, der genauso aussieht wie das Repository:

```
~/.local/share/lightshow/
  config/show.yaml   deine Konfiguration — beim ersten Start kopiert, danach deine
  projects/          deine Shows samt Audio
  firmware/          Quellen aus dem Image, bei einer neuen Version erneuert
  tools/             dito
  build/             gebaute Firmware
~/.local/state/lightshow/bridge.log      Ausgabe der Läufe, bei 5 MB als .1 weggerollt
```

Ein Update erneuert nur `firmware/` und `tools/`. `projects/`, `config/show.yaml`
und die generierten Header bleiben, wie sie sind. Zum Sichern reicht
`projects/` und `config/show.yaml`. Ein anderer Ort geht mit `LIGHTSHOW_ROOT`.

### Bridge aus dem Quellbaum

Zum Entwickeln. Ubuntu 24.04 ist PEP-668-verwaltet, deshalb zwingend ein venv:

```bash
cd host
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt pytest
```

So gestartet bleibt alles im Checkout — Konfiguration, `projects/`, `build/` —
genau wie bisher. Der Arbeitsbaum oben entsteht nur unter dem AppImage.

### AppImage selbst bauen

```bash
sudo apt install squashfs-tools
./packaging/appimage/build.sh          # -> dist/Lightshow-x86_64.AppImage
```

Das Skript lädt ein Python-Basisimage und die AppImage-Runtime, installiert
`host/` samt Abhängigkeiten hinein und legt `firmware/`, `tools/` und
`packaging/appimage/show.yaml` als Vorlage für den Arbeitsbaum dazu — die
leere Startkonfiguration, nicht die Beispielshow. Zum Schluss packt es das
fertige Image noch einmal aus und startet es mit eigenem `HOME`: läuft es nicht
oder bringt es Modelle mit, bricht der Bau ab.

**Bei jedem Release baut GitHub es selbst.** `.github/workflows/appimage.yml`
lässt erst die Testsuite laufen und hängt das Ergebnis dann an das
veröffentlichte Release. Der Workflow ruft dasselbe `build.sh` auf und
installiert nur, was Ubuntu dafür fehlt:

| Job | Pakete |
|---|---|
| Tests | `libasound2t64 build-essential nodejs` |
| AppImage | `squashfs-tools desktop-file-utils` |

`build-essential` ist keine Zier: ohne `make` überspringen die Kreuzprüfungen
126 Tests, ohne sich zu beschweren. Drei Tests bleiben auf einem Runner
übersprungen, weil er kein Audiogerät hat — `-rs` in der Testzeile macht das
sichtbar, damit eine vierte Übersprungene auffällt.

**An Runtime und Kompressor nichts drehen.** Beides ist mühsam erarbeitet, weil
auf Rechnern mit **AppImageLauncher** jeder Start über `binfmt_misc` durch ihn
hindurchgeht — und der ist auf Ubuntu 24.04 ein Paket von 2020:

| | liest | unter AppImageLauncher |
|---|---|---|
| Runtime aus `type2-runtime` | zlib, zstd | **nein** — `fuse: memory allocation failed` |
| Runtime aus `AppImageKit` | lzma, zlib | ja |
| libappimage 1.0.3 des Launchers | xz, zlib | — |
| `mksquashfs` in `appimagetool` | nur zstd | — |

Übrig bleibt genau eine Kombination: die **AppImageKit-Runtime** mit einem
**zlib**-Datenteil, gepackt vom `mksquashfs` des Systems. Ein zstd-Image bricht
schon vor dem Start mit *Fehler beim Registrieren des AppImages im System* ab,
ein xz-Image mountet nicht. Der Preis für die ältere Runtime ist `libfuse2t64`,
das sie per `dlopen` nachlädt; zlib ist obendrein das, was am schnellsten
mountet.

### Firmware-Toolchain

```bash
sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi \
                 libstdc++-arm-none-eabi-newlib
git clone --depth 1 --recurse-submodules \
    https://github.com/raspberrypi/pico-sdk ~/pico-sdk
```

Auf der Kommandozeile muss `PICO_SDK_PATH` gesetzt sein — entweder je Aufruf
oder dauerhaft in `~/.bashrc`:

```bash
export PICO_SDK_PATH=~/pico-sdk
```

Der Reiter **Flashen** braucht das nicht: er sucht das SDK selbst, zuerst unter
`PICO_SDK_PATH` und dann an den üblichen Stellen (`~/pico-sdk`,
`~/pico/pico-sdk`, `~/.pico-sdk/sdk/<Fassung>`, `/usr/share/pico-sdk`,
`/opt/pico-sdk`) und gibt den Fund an `cmake` weiter. Das ist kein Komfort,
sondern Notwendigkeit: aus dem Menü gestartet — der normale Weg beim AppImage —
erbt die Bridge die Umgebung der Sitzung und nicht die der Shell, und das
`export` aus der `~/.bashrc` ist dort schlicht nicht vorhanden. Welches SDK
genommen wurde, steht in der ersten Zeile des Build-Protokolls.

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
Gespeichert wird dort von selbst — jede Änderung steht binnen einer Sekunde auf
der Platte. Übrig sind der Projektname und **Schließen**, das die Show aus der
Hand legt und die Lichter in den Ruhezustand schickt. Geöffnet, angelegt und
bearbeitet werden Projekte im Tab **Projekte**; bearbeiten geht an jeder Karte,
auch an einer, die gerade nicht offen ist.
Ausführlich in [`docs/show-editor.md`](docs/show-editor.md).

1. Im Reiter **Projekte**: **＋ Neues Projekt** — Name, dann die Flugzeuge, die
   dabei fliegen. Es entsteht `projects/<name>/` mit zwei Audiospuren, je
   gewählter Zone einer Lichtspur und je Bus-Relais einer Relaisspur, benannt
   nach dem Modell und nicht nach CC-Nummern. Eingerichtet werden die Modelle
   vorher unter **Modelle**.
2. Musik auf eine Audiospur ziehen. Die Datei wird ins Projekt kopiert, damit
   der Ordner für sich allein lauffähig bleibt. WAV, FLAC, OGG und MP3.
3. **＋ Effekt** setzt einen Block am Abspielkopf auf die Lichtspur: Effekt,
   Farbton, Helligkeit, Tempo, Ein- und Ausblendung. Jeder Wert hat Regler und
   Zahlenfeld — Helligkeit in Prozent, Tempo in Sekunden je Umlauf, der Farbton
   auch als Hex oder R,G,B zum Einfügen. Ziehen verschiebt, an der Kante längen,
   <kbd>Entf</kbd> löscht. Kanten rasten am Raster ein, <kbd>Alt</kbd> beim
   Ziehen schaltet das ab.
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

*Damit belegt:* Editor, Zeitleiste, Quantisierung, Fades. Kostet nichts.

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

### Stufe 3 — Signal gegenprüfen

Dafür gab es einmal einen Selbsttest-Eingang auf GPIO10: ein Jumper von GPIO2
dorthin, und die Firmware maß ihr eigenes Ausgangssignal. Er hat am 17.08.2026
seine Zahl geliefert — **0 µs Eigenfehler** — und ist danach entfernt worden.
Ein Messeingang, der einmal gebraucht wird und dann nur noch Pin und Code
belegt, kostet mehr als er trägt.

Wer das Signal heute prüfen will, hängt einen Logikanalysator oder ein
Oszilloskop an GPIO2. Das Protokoll der damaligen Messung samt Ergebnissen steht
in [`docs/funkstrecke-messen.md`](docs/funkstrecke-messen.md).

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

*Erwartet:* Im Kanalmonitor des Senders bewegen sich die Trainer-Kanäle mit den
Blöcken der Zeitleiste.

Trainer-Kanäle jetzt **ausschließlich auf die Lichtkanäle** mischen.

### Stufe 5 — Modell

Bordfirmware flashen, `config.h` an das Modell anpassen: Zonen, Strips, Relais,
Positionslichter. Empfänger und LED-Streifen auf dem Tisch aufbauen, eigenes
UBEC für die LEDs.

**Relais zuerst ohne Last testen** — nur der Treiber, die geschaltete Leitung
noch nicht angeschlossen. Ein falsch gesetztes `active_low` schaltet sonst beim
Einschalten sofort durch, und bei einem Rauchsystem oder einem Scheinwerfer auf
der Werkbank ist das kein guter Moment, das zu merken.

*Erwartet:* Positionslichter leuchten sofort und dauerhaft. Ein Blockwechsel
auf der Zeitleiste ändert den Effekt, `brightness` dimmt weich. Relais schalten gemäß ihrer
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
| `test_mapping.py`      | Ruhezustand, Blackout, Kanalblöcke je Modell                  |
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
| Ausgabe stimmt          | `python -m lightshow --dry-run`                            |
| Konfiguration gültig    | `python -m lightshow --check`                              |
| UI erreichbar           | Bridge starten, `http://127.0.0.1:8765/` öffnen            |
| Bauen aus der UI        | Flashen-Tab → „2 · Bauen“, Log muss durchlaufen            |
| Failsafe Bodenstation   | USB im Betrieb abziehen → Ausgänge binnen 250 ms auf Failsafe |
| Failsafe Modell         | Sender ausschalten → nach 500 ms bernsteinfarbenes Pulsen, alle Relais fallen ab |
| Relais am Boden prüfen  | Cue auf 0 stellen → jedes Relais muss abfallen             |

---

## Fehlersuche

**`link: DOWN` in der TUI.** Gerätepfad prüfen (`ls /dev/ttyACM*`) und ob du in
der Gruppe `dialout` bist (`groups`) — fehlt die Gruppe, schreibt die Bridge das
inzwischen ausdrücklich hin statt nur `DOWN` zu zeigen. Sie verbindet sich
selbständig neu, sobald das Gerät wieder da ist.

**Das AppImage startet nicht.** Läuft es überhaupt, steht der Grund im Log:
`~/.local/state/lightshow/bridge.log`. Gibt es das Log gar nicht, ist es nie so
weit gekommen — dann von Hand starten, dort steht die Meldung:

```bash
./Lightshow-x86_64.AppImage --check
```

*Cannot mount AppImage* oder *fuse: memory allocation failed* heißt: `sudo apt
install libfuse2t64`, und falls selbst gebaut, die falsche Runtime — siehe
[AppImage selbst bauen](#appimage-selbst-bauen).

**Es öffnet sich ein Browser-Tab statt eines eigenen Fensters.** Dann ist kein
Browser der Chromium-Familie installiert. Einen nachrüsten (Brave, Chromium,
Chrome, Edge, Vivaldi — als Paket, Snap oder Flatpak) oder mit
`LIGHTSHOW_BROWSER=…` auf einen zeigen, den die Suche nicht kennt.

**Der Menüeintrag tut nichts.** Hat der Dateiname ein Leerzeichen? Dann steht
im `TryExec`, das AppImageLauncher schreibt, ein abgeschnittener Pfad. Image
ohne Leerzeichen benennen und neu integrieren.

**„Fehler beim Registrieren des AppImages im System".** Das kommt von
AppImageLauncher und heißt: seine libappimage kann den Datenteil nicht lesen.
Selbst gebaut? Dann steht der Kompressor auf zstd statt zlib — siehe
[AppImage selbst bauen](#appimage-selbst-bauen).

**`crc_err` zählt hoch.** Kabel oder USB-Port wechseln. Die Frames werden
verworfen, nicht falsch interpretiert.

**Im Sender bewegt sich nichts.** In dieser Reihenfolge:

1. Stufe 3 wiederholen — liegt am Ausgang überhaupt das erwartete Signal?
2. `polarity: inverted` setzen, Bridge neu starten
3. `sync_us: 300` probieren
4. 74HCT14 als 5-V-Puffer einschleifen
5. Masseverbindung prüfen — der häufigste Fehler

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
| `host/lightshow/` | Bridge: `config`, `timeline`, `mapping`, `link`, `monitor`, `webui`, `planegen`, `paths`, `appwindow` |
| `host/lightshow/web/` | Oberfläche: `index.html`, `app.css`, `app.js`, `effects.js` — ohne Bundler |
| `host/tests/`     | Testsuite, inklusive der Kreuzprüfungen gegen die Firmware  |
| `firmware/pico/`  | Bodenstation: PPM/SBUS über PIO und DMA, Selbsttest         |
| `firmware/plane/` | Bordcontroller: RC-Eingang, Effekt-Engine, Strips, Relais   |
| `tools/ctest/`    | Firmware-Logik nativ kompiliert, für die Tests              |
| `packaging/appimage/` | Startskript, Menüeintrag, Icon, leere Startkonfiguration und Bauskript des AppImage |
| `.github/workflows/` | Tests und AppImage-Bau bei jedem Release |
| `docs/`           | Show-Editor, Sender-Setup, Cue-Liste, Funkstreckenmessung    |
| `hardware/`       | Pinbelegung, Pegel, Stückliste, Strombudget                 |

Drei Header sind bewusst frei von SDK-Abhängigkeiten, damit ihre Rechnungen auf
dem PC prüfbar sind: `firmware/pico/src/ppm_frame.h` (Frame-Timing),
`firmware/plane/src/rc_decode.h` (Kanaldekodierung) und
`firmware/plane/src/relay_logic.h` (Relais-Entscheidung und Schaltzeiten). Genau
dort steckt die Logik, deren Fehler in der Luft am teuersten wären.

Das Wire-Protokoll ist an einer Stelle beschrieben:
`firmware/pico/src/protocol.h`. `host/lightshow/protocol.py` ist dessen
Spiegelbild — ändert sich eines, schlägt `test_cross_check.py` fehl.
