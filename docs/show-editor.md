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
| Doppelklick oder `Entf` | löschen |
| Klick aufs Lineal | Abspielposition setzen |
| Leertaste | Wiedergabe starten und anhalten |
| Zoom-Regler | Auflösung der Zeitachse |

Der Block trägt die Farbe, die er sendet — Farbton aus `hue`, Helligkeit aus
`brightness`. Die dunklen Keile an den Kanten sind Ein- und Ausblendung.

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

Wo kein Block liegt, gehen die Kanäle auf ihre Failsafe-Werte, also aus.

## Wiedergabe

Die Bridge mischt beim Laden das ganze Projekt einmal zusammen und spielt es
über die Soundkarte. Die Abspielposition ist die Zeitreferenz für die Lichter:
Ton und Licht kommen aus demselben Prozess und derselben Uhr und können nicht
auseinanderlaufen.

Zwischen den Audio-Callbacks wird die Position interpoliert und die
Ausgabelatenz abgezogen, damit sie zu dem passt, was tatsächlich zu hören ist.

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
