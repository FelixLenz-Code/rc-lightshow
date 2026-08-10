# Show-Editor

Die Show wird im Browser gebaut: oben die Audiospuren, darunter je Modell eine
Lichtspur. Eine externe DAW ist nicht mehr nötig — die Bridge spielt die Musik
selbst und ist damit die Uhr, aus der die Lichtwerte abgeleitet werden.

```
cd host && ./.venv/bin/python -m lightshow
# web interface: http://127.0.0.1:8765/   → Tab „Show"
```

## Projekt anlegen

Name eingeben, **Anlegen**. Das Projekt entsteht als Verzeichnis:

```
projects/nachtflug/
    project.json
    audio/musik.mp3
```

Es bringt gleich zwei Audiospuren („Musik", „Effekte") und **je Modell und Zone
eine Lichtspur** mit, benannt nach dem Modell aus `show.yaml`. Dadurch steht in
der Spurbeschriftung, welches Flugzeug gemeint ist, statt einer CC-Nummer.

Audiodateien werden beim Import **in das Projekt kopiert**, nicht verlinkt. Ein
Projektordner lässt sich damit auf einen anderen Rechner kopieren und läuft
dort weiter. Gelesen werden WAV, FLAC, OGG und MP3.

## Arbeiten in der Zeitachse

| Aktion | Wirkung |
|---|---|
| Datei auf eine Audiospur ziehen | Clip an der Fallstelle einfügen |
| Block oder Clip ziehen | verschieben |
| an der Kante ziehen | Anfang bzw. Ende ändern |
| anklicken | auswählen, Details erscheinen unten |
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

Relais haben **keine eigene Spur**, und das ist Absicht: drei der vier Quellen
werden aus der Effekt-Engine abgeleitet und kosten deshalb keinen RC-Kanal.
Welche Quelle ein Relais benutzt, steht im Tab **Modelle**; der Editor rechnet
sie mit und zeigt im Inspektor je Block, was passiert:

| Anzeige  | Bedeutung                                                   |
|----------|-------------------------------------------------------------|
| `an`     | schaltet mit diesem Block durchgehend ein                    |
| `blinkt` | folgt dem Muster, geht innerhalb eines Zyklus an und aus     |
| `aus`    | bleibt bei diesem Effekt aus                                 |

Effekt 0 schaltet immer alle Relais ab. Ein mechanisches Relais mit
`min_on_ms`/`min_off_ms` blinkt langsamer als die LEDs — der Inspektor weist mit
„träge" darauf hin. Nur `eigener RC-Kanal` braucht einen zusätzlichen Kanal und
lässt sich nicht aus dem Effekt ableiten.

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
auf Failsafe, egal ob die Werte aus der Timeline oder aus MIDI kommen.

## MIDI bleibt möglich

Der virtuelle MIDI-Port existiert weiterhin. Läuft kein Transport, kommen die
Werte von dort — praktisch, um im Hangar schnell einen Effekt auszuprobieren
oder eine bestehende Ardour-Session weiterzuverwenden
([`ardour-setup.md`](ardour-setup.md)). Sobald die Wiedergabe startet, übernimmt
die Timeline; nach dem Stoppen wieder MIDI. Einen Umschalter gibt es nicht.
