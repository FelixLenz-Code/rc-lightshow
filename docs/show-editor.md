# Show-Editor

Die Show wird im Browser gebaut: oben die Audiospuren, darunter je Modell eine
Lichtspur. Eine externe DAW gibt es nicht mehr — die Bridge spielt die Musik
selbst und ist damit die Uhr, aus der die Lichtwerte abgeleitet werden.

```
./Lightshow-x86_64.AppImage                   # oder aus dem Anwendungsmenü
cd host && ./.venv/bin/python -m lightshow    # aus dem Quellbaum
# web interface: http://127.0.0.1:8765/   → Tab „Show"
```

Projekte liegen unter dem AppImage in `~/.local/share/lightshow/projects/`, aus
dem Quellbaum heraus in `projects/` neben dem Repository.

## Der Reiter *Projekte*

Alle Shows auf einen Blick: Name, für welche Flugzeuge sie sind, wie viele
Spuren sie haben, in welchem Ordner sie liegen. **Öffnen** holt eine in den
Reiter *Show*, die geöffnete ist als solche gekennzeichnet.

### Anlegen

**＋ Neues Projekt** öffnet einen Dialog in zwei Schritten. Zwei Fragen hätten
auch in ein Formular gepasst; er trägt trotzdem die Aufmachung des
Modell-Wizards — dieselben Schrittmarken, dieselbe Ein-Satz-Beschwerde unten.
Ein Modell anlegen und eine Show anlegen sind dieselbe Art von Handlung, und die
zweite soll sich nicht wie ein anderes Programm anfühlen.

1. **Name** — wird zum Ordnernamen unter `projects/`. Ob es den schon gibt,
   sagt der Dialog selbst; die Regel dafür ist zeichengenau dieselbe wie
   `safe_name()` in `project.py`, sonst würde er einen Namen freigeben, den die
   Bridge danach ablehnt.
2. **Modelle** — welche Flugzeuge dabei fliegen. Vorgewählt sind alle;
   abwählen ist weniger Arbeit als auswählen. Jede Karte sagt, wie viele Spuren
   sie beisteuert, darunter steht die Summe.

Eingerichtet werden die Modelle **vorher** im Reiter *Modelle* — hier werden
sie nur ausgewählt. Ein Ort für eine Sache.

**Eines je Sender.** Mehrere Modelle dürfen auf derselben Sender-Buchse liegen,
solange sich ihre Kanalblöcke nicht überschneiden — das ist ein normaler Aufbau,
und der Wizard rückt beim Buchsenwechsel selbst auf den nächsten freien Block.
In ein *Projekt* kommt davon aber nur eines: sie hängen an einem Sender, und
eine Timeline, die beide treibt, würde zwei Flugzeuge von einem Knüppelpaar aus
fliegen. Im Dialog sind solche Karten gestrichelt und blass; sie anzuklicken
tauscht das andere ab, statt nichts zu tun. Geprüft wird es auch in der Bridge,
denn eine Regel, die nur in einem Dialog steht, hält eine von Hand bearbeitete
`project.json` nicht ein.

### Mitnehmen

**Exportieren** an einer Karte gibt das Projekt als Zip: `project.json` und die
Audiodateien daneben, also den ganzen Ordner. Ein Projekt *ist* ein Ordner — die
Musik wird beim Import hineinkopiert und nicht verlinkt —, deshalb ist es
mitzunehmen dasselbe wie es zu packen, und am anderen Ende muss nichts wieder
zusammengesucht werden.

**Importieren …** liest so ein Zip wieder ein. Geöffnet wird dabei nichts:
Einsortieren ist keine Aufforderung, die Show vom Bildschirm zu nehmen. Gesagt
wird, was auffiel — ein schon belegter Ordnername (dann liegt es daneben) und
Modelle, die es hier nicht gibt (dann bleiben deren Spuren stumm, bis eines
dieses Namens eingerichtet ist).

Abgewiesen wird ein Archiv ohne `project.json` — und eines, dessen Einträge aus
ihrem Ordner hinauszeigen. Ein Zip darf `../../irgendwo` heißen, und wer es
blind auspackt, tut genau das; ein Test hält fest, dass dabei nichts entsteht.

### Bearbeiten

**Bearbeiten** an einer Karte macht denselben Dialog wieder auf, mit Namen und
Modellen, wie sie sind — an **jeder** Karte, nicht nur an der geöffneten. Eine
Show erst laden zu müssen, um sie umzubenennen, hieße sie versehentlich zu
spielen und die Stelle in der zu verlieren, die schon offen war.

*Übernehmen* steht dabei auf **jeder** Seite — bei Modellen wie bei Projekten.
Wer kommt, um eine Zahl zu ändern, soll nicht vier Schritte weiterblättern
müssen, um den Knopf zu finden. Bis zur letzten Seite ist *Weiter* der
gewöhnliche nächste Zug und bleibt hervorgehoben; zwei hervorgehobene Knöpfe
nebeneinander sagten keines von beidem. Beim **Anlegen** bleibt der Knopf auf
der letzten Seite, denn vorher ist nichts fertig.

Der Unterschied liegt nur im Weg: das offene Projekt geht durch dieselbe
Speicherroutine wie jede Timeline-Änderung, damit die Bridge es sofort hört; ein
geschlossenes wird gelesen, geändert und in seinen Ordner zurückgeschrieben,
ohne dass die Session etwas davon merkt. Der Dialog sagt oben, welcher Fall
gerade vorliegt, und die Antwort für ein geschlossenes Projekt trägt bewusst
**keine** Projektdaten — die Oberfläche soll nichts zeichnen, was niemand
geöffnet hat.

Ein Modell dazunehmen legt seine Spuren an. Eines herausnehmen **löscht seine
Spuren samt allem, was darauf liegt** — das steht im Dialog rot da, bevor
geklickt wird, und danach noch einmal als Rückfrage. Was bleibt, behält seine
Blöcke; die Spuren werden anschließend wieder in Konfigurationsreihenfolge
sortiert, damit ein später zugenommenes Modell nicht für immer unten hängt.

Der Name ist nur die Beschriftung: der Ordner bleibt, wo er ist. Ihn
mitzuverschieben würde jeden Pfad brechen, der hineinzeigt, der Ordentlichkeit
zuliebe.

Das Projekt entsteht als Verzeichnis:

```
projects/nachtflug/
    project.json
    audio/musik.mp3
```

Es bringt zwei Audiospuren („Musik", „Effekte") und **je gewähltem Modell und
Zone eine Lichtspur** mit, dazu je Bus-Relais eine Relaisspur — benannt nach dem
Modell aus `show.yaml`. Dadurch steht in der Spurbeschriftung, welches Flugzeug
gemeint ist, statt einer CC-Nummer.

Dass die Auswahl eine Frage ist und keine Annahme, hat einen Grund: ein Platz
mit vier eingerichteten Modellen fliegt selten alle vier in einer Show, und eine
Timeline, die mit Spuren für jede Zone jedes Flugzeugs aufgeht, ist eine, die
erst einmal ausgeräumt werden muss.

Welche Modelle es sind, steht als `models` in der `project.json`. Ein Projekt
von vorher hat das Feld nicht — dann wird es aus den vorhandenen Spuren
gelesen, einmal, beim Laden.

### Die Audiodateien

Beim Import wird **in das Projekt kopiert**, nicht verlinkt: die Datei landet in
`projects/<projekt>/audio/`, und in der `project.json` steht ein relativer Pfad
darauf. Ein Projektordner lässt sich damit auf einen anderen Rechner kopieren
und läuft dort weiter — genau deshalb ist der Export ein Zip des ganzen Ordners.
Der Dateiname wird entschärft (alles außer `A–Z a–z 0–9 _ . -` wird `_`) und nie
überschrieben; gibt es ihn schon, hängt eine `_1` an. Absolute Pfade und `..`
weist das Format beim Laden ab. Gelesen werden WAV, FLAC, OGG und MP3, bis
200 MB je Datei; geprüft wird direkt nach dem Schreiben, und was sich nicht
öffnen lässt, wird sofort wieder gelöscht.

Gemischt wird beim Laden des Projekts, einmal, im Speicher — auf 48 kHz oder die
häufigste Abtastrate der beteiligten Clips, Mono verdoppelt, mehr als zwei
Kanäle auf zwei beschnitten. `offset_s` und `duration_s` schneiden schon beim
Lesen. An der Datei selbst wird nie etwas geändert.

**Aufgeräumt wird beim Speichern.** Fliegt der letzte Clip, der auf eine Datei
zeigt, aus der Timeline, wird die Datei mitgelöscht und das Fenster sagt es —
sonst wüchse ein Projekt um vierzig Megabyte, sooft ein Stück gegen ein anderes
getauscht wird. Zeigen noch andere Clips darauf, bleibt sie.

Verglichen wird dabei mit dem, was **auf der Platte** steht, nicht mit dem
Projekt in der Hand: eine Änderung erreicht die Bridge eine gute halbe Sekunde
vor der Datei, der Clip ist zur Speicherzeit also längst aus dem Speicher
verschwunden, und beide Mengen wären gleich. Ein Test hält genau diese
Reihenfolge fest.

Was **nie** in Gebrauch war, bleibt liegen: von Hand hineinkopierte Dateien, und
was aus der Zeit vor dieser Regel stammt. Ein automatischer Speichervorgang läuft
eine Sekunde nach jeder Änderung — das ist kein Moment, um Dateien zu löschen,
nach denen niemand gefragt hat. Der Reiter *Projekte* zählt sie an der Karte auf
(„3 Audiodateien, auf die kein Clip zeigt") und bietet **Aufräumen** an; gelöscht
wird erst auf Nachfrage.

## Gespeichert wird von selbst

Im Reiter *Show* gibt es keine Projektknöpfe mehr — kein *Öffnen*, kein *Neu*,
kein *Speichern*. Stehen geblieben ist die eine Sache, die diese Leiste besser
beantworten konnte als alles andere: **welche Show gerade auf dem Schirm ist**,
und ob die Platte dem Bildschirm hinterherkommt.

Jede Änderung läuft über zwei Uhren:

* nach **300 ms** geht sie an die Bridge (`/api/project/apply`) — das ist, was
  einen verschobenen Clip an seiner neuen Stelle klingen lässt;
* nach **900 ms** wird geschrieben. Länger auf Absicht: Schreiben ist, was eine
  Änderung überleben lässt, und kann warten, bis die Hand von der Maus ist. Ein
  Block über eine Minute Timeline gezogen ist **ein** Schreibvorgang, nicht
  neunzig.

Die geschriebene Antwort wird bewusst **nicht** zurück in den Editor gelesen:
sie ist dasselbe, was hingeschickt wurde, und sie erneut anzuwenden würde jedes
Spurelement neu bauen — mitten in dem Zug, der das Speichern ausgelöst hat. Die
einzige Ausnahme ist der Audio-Import, dessen Antwort die Wellenform trägt.

<kbd>Strg</kbd>+<kbd>S</kbd> gibt es weiterhin, für die Finger.

### Schließen

**Schließen** neben dem Namen legt die Show aus der Hand, ohne eine andere
aufzunehmen: die Bridge gibt das Audiogerät zurück und fällt in den
Ruhezustand — alle Zonen dunkel, jedes Relais auf seinem Failsafe. Was in den
letzten 900 ms noch nicht geschrieben war, wird vorher geschrieben.

Erreichbar ist der Knopf nur vom Rechner selbst, nicht über das Netz. Er
schreibt zwar nichts auf die Platte, nimmt aber allen die Show weg — das ist
nichts, was ein Telefon auf dem Platz können muss.

## Arbeiten in der Zeitachse

| Aktion | Wirkung |
|---|---|
| Datei auf eine Audiospur ziehen | Clip an der Fallstelle einfügen |
| Block oder Clip ziehen | verschieben — auch senkrecht auf eine andere Spur |
| an der Kante ziehen | Anfang bzw. Ende ändern |
| anklicken | auswählen, Details erscheinen unten |
| Rechtsklick | Menü: einfügen, duplizieren, löschen, Abspielkopf hierher |
| `Entf` | Auswahl löschen |
| Klick oder Ziehen im Lineal | Abspielposition setzen |
| Klick auf einen Spurkopf | Spureinstellungen: Name, Lautstärke, stumm, Zone |
| `+A` / `+L` über den Spurköpfen | Audio- bzw. Lichtspur anlegen |
| Leertaste | Wiedergabe starten und anhalten |
| `Pos1` | Stopp, zurück an den Anfang |
| `E` | Effektblock am Abspielkopf einfügen |
| `←` `→` | Abspielkopf um 1 s, mit `Umschalt` um 5 s |
| `Strg`+`S` | Projekt speichern |
| Zoom-Regler, `+` / `−`, `Strg`+Mausrad | Auflösung der Zeitachse |
| `Alt` beim Ziehen | ohne Raster |

Der Block **spielt seinen eigenen Effekt ab**: die Bordfirmware ist nach
JavaScript portiert, das Muster im Block ist also dasselbe, das später am Modell
läuft. Die dunklen Keile an den Kanten sind Ein- und Ausblendung, die
gestrichelte Linie markiert das Ende der Show.

Kanten rasten am Raster ein; wie fein es ist, ergibt sich aus dem Zoom (bei
starker Vergrößerung 0,05 s, bei weiter Übersicht 5 s). `Alt` beim Ziehen
schaltet es ab.

**Über Spuren hinweg.** Senkrecht gezogen wechselt ein Block die Spur; die
Zielspur hebt sich hervor, solange der Zeiger über ihr steht. Ein Effekt darf
auf jede Lichtspur, auch auf die eines anderen Modells — er trägt Cue, Farbton,
Helligkeit und Tempo, und damit kann jede Lichtspur etwas anfangen. Ein
Relaisblock will eine Relaisspur und ein Clip eine Audiospur: über diese Grenze
gibt es nichts zu übertragen, und eine Spur, die nicht in Frage kommt, hebt sich
gar nicht erst hervor.

Ist die Stelle in der Zielspur schon belegt, rutscht der Block auf die erste
Lücke dahinter — dieselbe Regel, nach der ein neu eingefügter Effekt einrastet.
Zwei Blöcke, die sich überlappen, ließen sich nicht speichern.

## Effekt-Blöcke

Ein Block auf einer Lichtspur ist **ein Effekt für eine Zone**, mit diesen
Feldern:

| Feld | Bedeutung |
|---|---|
| Effekt | die Cue-Nummer, siehe [`cues.md`](cues.md) |
| Beschriftung | freier Text, steht im Block |
| Farbe | 0–255 über den Farbkreis |
| Helligkeit | 0–255, vor den Blenden |
| Tempo | 0–255, Geschwindigkeit des Effekts |
| Ein-/Ausblenden | Sekunden; skaliert die Helligkeit |

**Blöcke auf einer Spur dürfen sich nicht überlappen.** Das ist keine
Bequemlichkeitsgrenze: eine Zone zeigt immer genau einen Effekt, weil `cue` ein
einzelner Kanal ist. Zwei gleichzeitige Blöcke wären nicht mischbar, sondern
mehrdeutig — deshalb lehnt das Speichern sie ab. Für einen weichen Übergang den
einen aus- und den nächsten einblenden lassen.

Der Editor lässt es gar nicht erst so weit kommen: Ein Block stößt beim Ziehen
an seinen Nachbarn an, statt sich darüberzulegen, und auch von Hand eingetippte
Werte werden in die Lücke zurückgeholt. Ebenso werden Blenden, die länger sind
als der Block, auf dessen Länge zurückskaliert. Was sich im Editor bauen lässt,
lässt sich damit auch speichern.

Wo kein Block liegt, gehen die Kanäle auf ihre Failsafe-Werte, also aus.

## Welche Lampen ein Block ansteuert

Eine Lichtspur steuert **eine Zone eines Modells**. Welche Leuchtmittel das sind,
steht in der Bordkonfiguration: jeder Strip trägt dort eine Zone. Der Editor
zeigt es an beiden Stellen, damit „Zone 1" keine bloße Zahl bleibt:

- im **Spurkopf** die Namen der Strips, z. B. `flaeche_links + flaeche_rechts`
- im **Inspektor** darüber hinaus die Pixelzahl, und die Vorschau ist genau so
  lang wie die echte Kette — ein Lauflicht sieht damit aus wie am Modell

Ein Modell mit zwei Zonen bekommt zwei Lichtspuren und kann Flächen und Rumpf
unabhängig steuern. Das kostet vier weitere RC-Kanäle.

## Relais

Ein Relais wird über den Bus geschaltet: eigenes Bit, eigener Control-Change,
ab 64 an. Es folgt keinem Effekt und hängt an keiner Zone — eingerichtet wird es
im Wizard unter **Modelle**, Schritt *Relais*.

Gefahren wird es über eine **Relaisspur**: eine Spur je Relais, **+R** legt eine
an, und ein neues Projekt bringt für jedes Relais jedes Modells schon eine mit.
Ein Block auf dieser Spur bedeutet **an**, eine Lücke **aus** — mehr gibt es
nicht zu sagen. Kein Effekt, keine Farbe, keine Blenden: ein Schalter hat davon
nichts.

| Was              | Wo                                                        |
|------------------|-----------------------------------------------------------|
| Spur anlegen     | **+R** oben links, oder je Relais eine im neuen Projekt    |
| Block anlegen    | **＋ Effekt** bei ausgewählter Relaisspur                   |
| Beschriftung     | im Inspektor; ohne sie steht „an" auf dem Block            |

Zwei überlappende Blöcke werden abgewiesen: „an" und noch einmal „an" sagt
dasselbe zweimal, und nur die Lücke dazwischen hätte Bedeutung.

Ein Relais, das keine Spur hat, bleibt während der ganzen Show aus — der
Encoder wird in jedem Rahmen zurückgesetzt, damit ein Rauchsystem nicht
weiterläuft, weil das vorige Projekt sein Bit gesetzt hatte.

Ein **träges Relais** (`min_on_ms`/`min_off_ms`) dehnt kurze Blöcke an Bord auf
seine Mindestzeit. Der Inspektor sagt das dazu, wenn es zutrifft.

## Vorschau ohne Modell

**Vorschau ↗** in der Transportleiste öffnet ein eigenes Fenster mit jeder
LED-Kette jedes Modells: echte Pixelzahl, die Abschnitte dort, wo sie wirklich
sitzen, Positionslichter inbegriffen. Gedacht für den zweiten Bildschirm neben
der Timeline.

Der Unterschied zur **Bühne**: dort steht ein Streifen je *Zone*, in einer
Stellvertreterlänge. Hier steht ein Streifen je *Kette* — also das, was am
Flugzeug tatsächlich angelötet ist. Eine Kette, die vorn Zone 1 und hinten
Zone 2 zeigt, sieht man nur hier.

Die Pixelabbildung ist `outputs_show()` aus der Bordfirmware, Zeile für Zeile
nachgebaut: ein Abschnitt liest die virtuelle Kette seiner Zone ab `offset`, bei
`reverse` rückwärts, und was über deren Ende hinausreicht, bleibt dunkel. Läuft
das auseinander, lügt das Fenster — deshalb steht der Hinweis auch im Quelltext.

### Reiter *Modell* — die Abschnitte auf dem Flugzeug

Derselbe Zustand, nur nicht als Streifenreihe, sondern dort, wo die Streifen am
Flugzeug sitzen. Ein Hochdecker in vier Ansichten: **von oben, von unten, von
links, von rechts**.

Links die Abschnitte des Modells, rechts das Flugzeug. Einen Abschnitt anklicken
legt ihn quer über die gerade gezeigte Ansicht; danach ziehen: **die Enden
zielen, die Mitte verschiebt, der Griff daneben dreht**. Die Pixel liegen der
Reihe nach auf der Linie und leuchten so, wie die Show gerade läuft — ein
Lauflicht wandert also wirklich über die Fläche.

Der Drehgriff sitzt neben der Mitte, an einem kurzen Stiel und hohl gezeichnet,
damit er nicht als drittes Ende gelesen wird — auf der Linie selbst wäre kein
Platz, dort bedeuten die Enden schon „zielen" und die Mitte schon „schieben".
Gedreht wird um die eigene Mitte, die Länge bleibt. **Waagerecht und senkrecht
rasten von selbst** — innerhalb von etwa 4° schnappt der Streifen ein, weil fast
jeder das eine oder das andere sein soll und eine Maus das von Hand nicht auf
Zehntelgrad trifft. Mit <kbd>Umschalt</kbd> rastet es in 15°-Schritten, für
alles dazwischen: längs einer Rippe, quer zum Holm, schräg über die Fläche. Gerechnet wird in den Einheiten des
Bildes, nicht in den gespeicherten 0..1 — das Fenster ist breiter als hoch, und
eine Vierteldrehung in Platzierungskoordinaten käme als Quetschung heraus. Eine
Drehung, die ein Ende aus dem Bild schöbe, wird gar nicht erst angewandt: ein
Ende zu begrenzen und das andere nicht würde den Streifen stillschweigend
kürzen, und die Pixelzahl sagte dann etwas anderes als die Zeichnung.

**Aus der Hand legen**: ein Klick ins Leere oder <kbd>Esc</kbd>. Nötig, weil die
Überlagerung den Zeiger überall durchlässt außer auf einem Griff — sonst käme
das Ziehen im 3D-Bild nie an der Zeichenfläche an. Der Klick, der einen
Abschnitt ablegt, landet deshalb dort und nicht bei der Überlagerung.

Eine Platzierung ist eine Linie: Ansicht plus zwei Punkte, gespeichert als
`place` unter dem Abschnitt in `show.yaml`:

```yaml
segments:
  - {name: aussen, start: 0, count: 30, zone: 0,
     place: {view: top, x1: 0.09, y1: 0.355, x2: 0.44, y2: 0.355}}
```

Die Koordinaten sind 0..1 über die jeweilige Ansicht, laufen also mit der
Fenstergröße mit. **Nichts davon erreicht das Flugzeug**: der Generator sieht es
nicht, die Firmware kennt es nicht, über die Leitung geht es nie. Es ist eine
Zeichnung, damit sich eine Show ohne angeschlossenes Modell beurteilen lässt —
ein Test hält fest, dass kein Wort davon in der `config.h` landet.

Geschrieben wird über `/api/placement`, das genau einen Abschnitt anfasst. Die
Modellansicht im anderen Fenster kann ungespeicherte Änderungen offen haben; ein
ganzes Dokument von hier würde sie stillschweigend zurücknehmen. Aus demselben
Grund bleibt dieser Schreibzugriff während einer laufenden Show erlaubt — es sind
Koordinaten auf einer Zeichnung, keine Kanäle.

### Der Knopf *3D*

Dasselbe Flugzeug körperlich, mit der Maus drehbar, Mausrad zoomt. Gedacht für
die Frage, die eine flache Ansicht nicht beantwortet: **wie liest sich die Show
von da unten**, wo der Pilot steht.

Hier wird nicht platziert, hier wird nur gezeigt. Die vier flachen Ansichten
legen bereits jeden Punkt im Raum fest — genau wie eine Dreiseitenansicht:

| gezeichnet auf | daraus wird |
|---|---|
| von oben   | Spannweite und Station, auf der Oberseite |
| von unten  | Spannweite und Station, auf der Unterseite |
| von links  | Station und Höhe, an der linken Rumpfseite |
| von rechts | Station und Höhe, an der rechten Rumpfseite |

Deshalb gibt es hier nichts einzugeben: das 3D-Bild **liest** die vier Ansichten,
statt dieselbe Angabe ein zweites Mal zu verlangen. Und deshalb lässt sich darin
auch nicht ziehen — eine Linie auf einem gedrehten Körper ist beim Anfassen
mehrdeutig, und Raten würde Streifen dorthin legen, wo sie niemand hingelegt hat.

### Gespeichert wird sofort, übernommen auch

Ein Modell ist kein Entwurf, wie es eine Timeline ist. Es gibt ein Flugzeug, es
hat drei Zonen oder vier, und eine Liste, die vier zeigt, während die Datei drei
sagt, ist genau der Zustand, in dem jemand eine `config.h` erzeugt und sich
wundert. Deshalb schreibt der Reiter **Modelle** bei jedem Anlegen, Ändern und
Entfernen selbst.

Und das Geschriebene gilt dann auch. Vorher hieß Speichern „beim nächsten Start
macht die Bridge das“ — eine seltsame Auskunft für ein Instrument, das gerade
läuft: die Liste zeigte schon die neuen Zonen, auf dem Draht lagen noch die
alten, und nichts auf dem Bildschirm sagte, welches von beidem stimmt. Jetzt
passiert beim Speichern dreierlei, in dieser Reihenfolge:

1. **Die Konfiguration übernimmt den neuen Inhalt an Ort und Stelle.** Mapper,
   Session, Monitor und Webserver halten alle dasselbe Objekt und behalten es,
   solange sie laufen. Es auszutauschen hieße, alle vier mit dem alten
   sitzenzulassen. Es gibt genau eine Konfiguration im Prozess, vorher wie
   nachher.
2. **Der Mapper baut neu**, was er daraus abgeleitet hatte: Slots und
   Bus-Encoder. Ganz neu, nicht geflickt — dann kann kein alter Slot überleben
   und weiter einen Kanal treiben, der ihm nicht mehr gehört. Blackout und
   Nachrichtenzähler bleiben, die gehören zur Sitzung, nicht zur Datei.
3. **Die Bodenstation bekommt die Port-Einstellung noch einmal.** Sie wird
   einmal beim Verbinden geschickt; ohne das Nachreichen baut das Board weiter
   Rahmen in der alten Form. Ein geänderter Gerätepfad ist ein anderes Board,
   also wird dann geschlossen und neu gesucht.

Ist ein Projekt offen, wird zusätzlich seine Licht-Timeline neu gebaut — welche
Zone eine Spur treibt, wird in der Konfiguration nachgeschlagen.

Abgelehnt wird das Ganze, solange eine **Show läuft**. Dann wird die
Änderung **verworfen** und die Liste auf
den Stand der Datei zurückgeholt — es gibt keinen Speichern-Knopf mehr, mit dem
sich das nachholen ließe, und ein Browser, der als einziger die Änderung hält,
wäre dieselbe Falle einen Bildschirm weiter. Was gesagt wird, steht in der
Meldung: warum nicht gespeichert wurde, und dass die Liste wieder die Datei
zeigt.

### Drei Bauarten

Im Wizard steht als erstes, **was für ein Modell** das ist: Motorflugzeug,
Segelflugzeug oder Quadrocopter. Das Wort landet als `airframe` unter `plane:`
in der `show.yaml`:

```yaml
plane:
  board: pico
  airframe: segler
```

Es entscheidet allein über die Vorschau — welcher Körper gezeichnet wird, wie
die vier flachen Fenster geschnitten sind, worauf ein Streifen kleben kann und
wie weit die drehbare Kamera absteht. **An Bord kommt es nie an**: der Generator
liest es nicht, in der `config.h` steht es nicht, über die Funkstrecke geht es
nicht. Ein Test hält das fest, so wie für die Platzierungen.

| Bauart | woran man sie erkennt | wohin die Streifen typischerweise gehen |
|---|---|---|
| `motor` | Hochdecker, Propellerkreis, festes Fahrwerk | Fläche, Rumpfseite, Leitwerk |
| `segler` | sehr lange schmale Fläche, schlanker Leitwerksträger, T-Leitwerk | Fläche, Haubenrahmen |
| `quad` | vier Arme in die Ecken, vier Motoren, Rotorkreise | die Arme |

Der Rumpf entsteht bei allen dreien aus derselben Querschnittstabelle, die
Flächen aus demselben Profilschnitt, die Arme und Beine des Quadrocopters aus
demselben Rohr. Wer eine vierte Bauart will, schreibt eine Funktion, die Flächen
und vier Fensterausschnitte zurückgibt — und trägt den Namen in `AIRFRAMES` ein,
hier wie in `config.py`. Ein unbekanntes Wort wird beim Laden abgewiesen, statt
stillschweigend als Flugzeug gezeichnet zu werden.

Die Fensterausschnitte gehören zur Bauart. Eine Platzierung ist 0..1 über ihr
Fenster, also wandert sie mit, wenn sich am Fenster nichts ändert — und ein
Modell von Flugzeug auf Quadrocopter umzustellen legt die Streifen sinngemäß neu
statt sie auf absolute Millimeter zu setzen, die dann nichts mehr bedeuten.

### Ein Flugzeug, fünf Kameras

Alle fünf Ansichten zeigen **denselben Körper**: vier orthografische Kameras und
eine perspektivische auf einer Umlaufbahn. Nur die Kamera unterscheidet sie.

Das ist der Punkt an dieser Bauweise. Vorher waren die flachen Ansichten von
Hand gezeichnete Umrisse und die 3D-Sicht ein eigenes Gitter — dass beide
dasselbe Flugzeug meinten, war ein Versprechen. Jetzt liegt eine Fläche an einer
Stelle, und jede Ansicht ist eine Aufnahme davon. Wer den Rumpf ändert, ändert
ihn überall, ohne daran zu denken.

Der Rumpf entsteht aus Querschnitten (`BODY_SECTIONS` in `airframe3d.js`), die
Tragflächen aus einem Profilschnitt, der von der Wurzel zur Spitze läuft. Jede
Fläche bekommt eine Normale, und die entscheidet über die Helligkeit — das ist
der Unterschied zwischen „neun graue Rechtecke" und etwas, das rund aussieht.
Dünne Teile wie die Fahrwerksbeine sind ausdrücklich beidseitig, sonst
verschwänden sie bei der Hälfte der Blickwinkel.

Gezeichnet wird mit **WebGL** (`mockgl.js`, Matrizen und Shader-Hilfen in
`glkit.js`): rund 575 Flächen als Dreiecke, flach schattiert, dazu die LEDs als
Billboard-Quads mit additiver Mischung — ein Lämpchen bleibt aus jedem Winkel
eine runde Scheibe mit Hof, statt zur Ellipse zu werden und von der Kante her zu
verschwinden. Kein Loader, keine Abhängigkeit, kein Build-Schritt; die
Matrizenrechnung sind dreißig Zeilen. Fehlt WebGL im Browser, sagt der Reiter
das und bleibt gesperrt — die Streifenansicht läuft weiter.

Ein fertiges Modell aus dem Netz wäre der andere Weg gewesen. Es müsste aber
ohnehin auf die Stationen oben eingepasst werden — die sind es, die alle fünf
Ansichten in Übereinstimmung halten — und brächte einen Loader und eine
Lizenzfrage mit, für ein Flugzeug, das absichtlich kein bestimmtes ist.

Angefasst wird nicht im Bild: Griffe und Ziehlinien liegen als SVG **über** dem
Canvas und werden durch dieselbe Kamera gerechnet. Zwei Kreise im Shader zu
treffen wäre viel Maschinerie für wenig.

### Die Pixel liegen auf der Haut

Eine Platzierung ist eine Linie in einer *flachen* Ansicht — zwei Koordinaten.
Die dritte holt sich das Bild aus dem Flugzeug: für jeden Pixel wird gesucht,
wo die Außenhaut unter diesem Punkt liegt, und der Pixel kommt 13 mm darüber zu
liegen.

Vorher stand dort eine feste Höhe für die ganze Ansicht, und das ging schief,
sobald eine Fläche nicht flach ist: Diese hat V-Form und ein Profil, liegt an
der Wurzel also **unter** und an der Spitze **über** jeder festen Ebene. Von
oben verschwand deshalb das äußere Drittel jedes Flächenstreifens im Tiefenpuffer
— das Flugzeug verschluckte seine eigenen Lichter. Jetzt folgen die Pixel der
V-Form, auch wenn das Modell gedreht wird.

**Jeder** Pixel sucht dabei seine eigene Haut. Nur die beiden Enden zu heben und
dazwischen gerade zu ziehen reicht auf einer Fläche — die ist längs der
Spannweite fast eben. Am Rumpf nicht: eine Flanke ist ein Rohr, unter der Fläche
am dicksten und zum Heck hin schlanker, und die Sehne zwischen zwei Punkten
darauf geht mitten hindurch. Von einem Streifen längs der Rumpfseite steckte so
die Hälfte im Rumpf — gemessen 15 von 30 Pixeln. Genau das war das
„Streifen verschwinden an der Seite des Flugzeugs".

Was ein Klebeband tut, tut das Profil jetzt auch: es liegt auf, worauf es
kommt, überspannt, was es nicht erreicht, und läuft über eine Kante hinaus
geradeaus weiter. Das Überspannen ist ein Maximum-Durchlauf von beiden Enden,
der nur heben kann — so wird kein Pixel unter die Haut gedrückt, auf die er
gerade gelegt wurde.

Welche Teile als Haut zählen, hängt an der Ansicht: von oben sind Fläche und
Höhenleitwerk Haut, von der Seite nur Rumpf, Haube und Seitenleitwerk. Sonst
zöge es einen Rumpfstreifen zur Flächenspitze hinaus, denn von links ist die
linke Flächenspitze das Äußerste. Fahrwerk und Propellerkreis zählen nie.

Die Suche ist billig, weil jede Ansichtsachse eine Koordinatenachse ist: zwei
Koordinaten stehen fest, gesucht ist die dritte. Keine Strahl-Dreieck-Rechnung,
nur eine baryzentrische Probe über die Dreiecke, die den Punkt überdecken. Rund
1 ms für einen 30-Pixel-Streifen, und das auch nur, während gezogen wird —
danach steht das Ergebnis im Zwischenspeicher (1,5 µs).

### Wenn dort kein Streifen sitzen kann

Nicht jede gezeichnete Linie kann ein Band tragen. An der Rumpfseite auf Höhe
der Flächenwurzel gibt es keine Rumpfhaut: die Fläche nimmt dort die ganze Höhe
ein und geht glatt durch. Dasselbe an der Höhenleitwerkswurzel. Am echten
Flugzeug ginge das Band da auch nicht hin.

Deshalb verbiegt das Bild nichts, sondern **zählt und sagt es**: unter der
Bühne steht dann, wie viele Pixel welches Abschnitts in der Zelle statt darauf
liegen. Der Anlass ist, dass es sonst genau falsch herum auffällt — die flachen
Ansichten zeichnen ihre Streifen ohne Tiefentest, dort sieht so ein Pixel
tadellos aus, und erst im 3D-Bild fehlt er.

Der Test braucht keine neue Maschinerie: ein Punkt steckt drin, wenn die
höchste Haut über ihm höher und die tiefste unter ihm tiefer liegt — beides
dieselbe Suche wie oben, einmal von oben und einmal von unten angesetzt.
Gerechnet wird das nur, wenn sich eine Platzierung ändert.

Eine Rasterprobe über alle vier Ansichten — 84 Streifen quer, längs und
diagonal über jede Fläche, 2520 Pixel — findet mit dieser Hebung noch 11
steckende Pixel, alle in diesen beiden Wurzelbändern. Vorher waren es ganze
Streifenhälften.

### Nachtflug

Eine Show wird im Dunkeln geflogen, und genau das zeigt das Fenster. Ausgeleuchtet
wie ein Prospektfoto ersäuft ein weißes Modell seine eigenen Streifen: gegen eine
Fläche, die schon bei 80 % Weiß steht, kommt eine LED nicht an, und jeder Cue sah
aus wie blasse Punkte auf einem hellen Flugzeug.

Deshalb gibt es im Bild nur noch drei Lichtquellen: ein schwacher Himmel von
oben, eine dünne Kante, damit der Umriss lesbar bleibt — und **die Streifen
selbst**. Die leuchten nicht nur, sie werfen auch zurück: eine rote
Flächenspitze legt Rot auf die Fläche, ein Blitz erhellt für den Moment die
ganze Flanke. Das ist die Hälfte, die den Unterschied macht zwischen Lämpchen,
die aufgeklebt wirken, und einem Flugzeug, das sein eigenes Licht fliegt.

Gerechnet wird das im Shader der Zelle: die Pixel eines Abschnitts werden zu
einer Handvoll Punktlichter zusammengefasst (wie vielen, sagt der Treiber über
`MAX_FRAGMENT_UNIFORM_VECTORS`) und **summiert**, nicht gemittelt — zehn LEDs
werfen doppelt so viel wie fünf. Gemittelt hinge die Helligkeit daran, wie das
Budget gerade aufgeteilt wurde, und dasselbe Flugzeug würde dunkler, sobald ein
zweiter Streifen dazukommt.

#### In linearem Licht gerechnet

Alles davon wird in **linearem Licht** addiert und erst ganz am Schluss für den
Bildschirm kodiert. Das ist keine Pedanterie:

* Zwei Lampen nebeneinander sind doppelt so viel Licht, eine Lampe in doppelter
  Entfernung ein Viertel davon. In sRGB — der Kurve, die ein Bildschirm
  erwartet — stimmt beides nicht. Entlang der Kurve addiert werden zwei schwache
  Lampen zu hell und eine ferne viel zu sichtbar; der Lichtwurf las sich als
  flächiger Farbstich statt als Licht mit Abfall.
* Das Byte, das eine WS2812 bekommt, **ist** ihr Tastverhältnis — also
  proportional zum abgestrahlten Licht, eine lineare Größe. Direkt als
  Bildschirmwert gezeigt wurde ein halb heller Streifen als viertelhell
  dargestellt. Beide Reiter kodieren jetzt gleich, die Streifenansicht über eine
  256er-Tabelle, das Modellbild im Shader.
* Der Abfall ist eine echte Quadratabnahme mit weichem Kern, keine Kurve nach
  Gefühl.

Und ein Streifen strahlt nur **von seiner Haut weg**. Vorher war er ein nackter
Punkt im Raum, und ein Bauchstreifen beleuchtete die Flächenoberseite quer durch
das Flugzeug hindurch, das ihn trägt. Geprüft wird das als vorzeichenbehafteter
Abstand zur Hautebene der Lampe, nicht als Winkel — ein Winkel würde
ausgerechnet die eine Fläche abschneiden, die eine Lampe sicher beleuchtet:
die, auf der sie klebt, 13 mm hinter ihr und damit bei vollen 180°.

Der Regler **Nacht** in der Leiste stellt alles außer den Streifen heller oder
dunkler. Ganz links bleibt vom Modell nur, was seine eigenen Lichter zeigen —
das ist der Blick vom Boden. Nach rechts wird es zur Werkbank, auf der sich ein
Streifen genau ansetzen lässt. Er ändert nur die Beleuchtung, nie eine
Platzierung.

## Wiedergabe

Die Bridge mischt beim Laden das ganze Projekt einmal zusammen und spielt es
über die Soundkarte. Die Abspielposition ist die Zeitreferenz für die Lichter:
Ton und Licht kommen aus demselben Prozess und derselben Uhr und können nicht
auseinanderlaufen.

Zwischen den Audio-Callbacks wird die Position interpoliert und die
Ausgabelatenz abgezogen, damit sie zu dem passt, was tatsächlich zu hören ist.

Änderungen wirken **sofort**, ohne Speichern: Ein verschobener Clip klingt an
seiner neuen Stelle, eine gedrehte Spurlautstärke ist gleich zu hören. Die
Bridge mischt dafür nur dann neu, wenn sich am Audio wirklich etwas geändert
hat — ein verschobener Lichtblock kostet keinen Remix. **Speichern** schreibt
die Änderung zusätzlich auf die Platte.

Der Abspielkopf bleibt bei **Pause** stehen und der Ton verstummt sofort; das
Gerät bleibt dabei geöffnet, damit der nächste Start ohne Verzögerung kommt.
Steht der Kopf am Ende, beginnt **Wiedergabe** wieder von vorn.

Kommt der Ton hörbar später als das Licht, steht die gemessene Ausgabelatenz in
der Transportzeile — die Position ist bereits um sie korrigiert. Bleibt ein
Versatz, hilft `global_offset_ms` in `show.yaml`, das das Licht nachzieht.

**Ohne Audiogerät läuft die Uhr trotzdem.** Die Lichter verhalten sich exakt wie
mit Ton — so lässt sich eine Show auch auf einem Rechner ohne Audio prüfen. Die
Oberfläche schreibt in dem Fall „kein Audiogerät — Uhr läuft trotzdem".

Ist die Summe aller Spuren zu laut, wird sie normalisiert und die Oberfläche
sagt es. Besser sind saubere Clip-Lautstärken.

## Während der Show

Solange der Transport läuft, ist die Modellkonfiguration im Tab **Modelle**
gesperrt, damit sich die Zuordnung nicht mitten in der Show ändert. Der Editor
selbst bleibt bedienbar; Speichern übernimmt die Änderung, ohne die Wiedergabe
zurückzusetzen.

Der Blackout-Knopf oben rechts schlägt jede Quelle: er setzt sofort alle Kanäle
auf Failsafe, egal ob die Werte aus der Timeline kommen oder aus dem
Ruhezustand.
