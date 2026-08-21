# Cue-Liste

Der `cue`-Kanal wählt den Effekt, den die Bordfirmware erzeugt. 32 Stufen über
den Reglerweg; die Bridge legt jeden Wert in die Mitte seiner Stufe, damit ein
verrauschter Kanal nie auf einer Grenze sitzt.

## CC-Wert je Stufe

Bei 32 Stufen gilt `Stufe = CC-Wert / 4`. In der Automationsspur also den
mittleren Wert einer Vierergruppe zeichnen:

| Stufe | CC 20 zeichnen | Effekt          | `param` steuert       |
|-------|----------------|-----------------|-----------------------|
| 0     | 0–3            | aus             | —                     |
| 1     | 4–7            | Dauerlicht      | —                     |
| 2     | 8–11           | Atmen           | Periode               |
| 3     | 12–15          | Strobe          | Blitzrate             |
| 4     | 16–19          | Doppelstrobe    | Blitzrate             |
| 5     | 20–23          | Lauflicht       | Umlauf                |
| 6     | 24–27          | Komet           | Umlauf                |
| 7     | 28–31          | Funkeln         | Dichte                |
| 8     | 32–35          | Regenbogen      | Rotation              |
| 9     | 36–39          | Polizei         | Wechsel               |
| 10    | 40–43          | Theater-Chase   | Umlauf                |
| 11–31 | 44–127         | Dauerlicht      | — (Reserve)           |

Stufen 11–31 sind bewusst als Dauerlicht definiert statt als „nichts", damit ein
Tippfehler in der Automation nicht zu einem dunklen Modell führt. Sie sind der
Platz für eigene Effekte in `firmware/plane/src/effects.c`.

> **Stufe 31 nicht belegen.** Auf der Leitung bedeutet sie „alles aus, alle
> Zonen" — so wirkt ein einzelner Failsafe-Rahmen auf das ganze Modell und nicht
> nur auf die eine Zone, die er adressiert. Das gilt für jedes Modell, denn jedes
> fährt über den [Bus](bus-modus.md).

## Die anderen Kanäle

| Kanal        | Wirkung                                                        |
|--------------|----------------------------------------------------------------|
| `hue`        | Farbton über den vollen Farbkreis. Bei Regenbogen und Polizei ohne Wirkung. |
| `brightness` | Master-Dimmer. 0 schaltet dunkel, unabhängig vom Cue.          |
| `param`      | Tempo: 0 ≈ 2 s Periode, 255 ≈ 100 ms.                          |

Helligkeit ist gammakorrigiert (2,2), ein linearer Fade im Editor sieht also
auch linear aus.

## Relais

Relais hängen **nicht** an der Effekt-Engine. Sie werden über den Bus
geschaltet: ein Bit im Rahmen, ein eigener Control-Change, ab 64 an. Siehe die
Tabelle `RELAYS` in `firmware/plane/src/config.h` — dort steht nur noch, an
welchem Pin ein Relais hängt und wie schnell es schalten darf. Welches Relais es
ist, sagt seine Position: die ist zugleich sein Bit auf der Leitung.

Cue 0 hat auf Relais deshalb keinen Einfluss mehr. Was sie abschaltet, ist der
Rahmen, der „alles aus" sagt — [Cue-Stufe 31 auf der Leitung](bus-modus.md) —
sowie Funkausfall und Blackout. Bei Funkausfall fallen sie sofort ab, ohne
Rücksicht auf Mindestschaltzeiten: ein Rauchsystem soll nicht noch 200 ms
weiterlaufen.

Mechanische Relais brauchen `min_on_ms`/`min_off_ms` von etwa 200. Details zur
Treiberschaltung in [`../hardware/README.md`](../hardware/README.md).

## Was immer läuft

- **Positionslichter** (rot links, grün rechts, weiß Heck) werden nach jedem
  Effekt darübergelegt und lassen sich weder dimmen noch abschalten. Der Pilot
  braucht sie zur Lageerkennung. Position je Strip und Pixel in der Tabelle
  `NAV_LIGHTS`.
- **Failsafe**: kommen 500 ms lang keine gültigen RC-Daten, pulst das Modell
  langsam bernsteinfarben. Diese Farbe kommt in keinem Cue vor — man sieht also
  sofort, welches Modell die Verbindung verloren hat.
- **MAX_BRIGHTNESS** in `firmware/plane/src/config.h` deckelt alles. Begrenzt
  den Spitzenstrom und verhindert, dass der Pilot geblendet wird.

## Eigene Effekte

In `effects.c` einen `case` in `effects_render()` ergänzen und `EFFECT_COUNT`
erhöhen. Zur Verfügung stehen:

- `base` — die aktuelle Farbe aus `hue`
- `ph` — Position im Zyklus, 0–255, Tempo kommt aus `param`
- `count` — Anzahl LEDs

Helligkeit, Gamma und die Obergrenze setzt `finish()` am Ende auf jeden Effekt
an; das muss der eigene Code nicht berücksichtigen.
