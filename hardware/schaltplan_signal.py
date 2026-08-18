#!/usr/bin/env python3
"""Variante B -- die Platine gibt nur Signale aus.

Zwei WS2812-Strips und zwei Schaltausgaenge. Was geschaltet wird -- Relaismodul,
MOSFET-Platinchen, Halbleiterrelais -- haengt extern daran. Damit fuehrt die
Platine nirgends Ampere und bleibt klein.

    python3 hardware/schaltplan_signal.py
"""

from svgkit import *   # noqa: F403



begin(1700, 1700)

txt(40, 48, "Bordplatine · Steuerung für 2 WS2812-Strips und 2 Schaltausgänge",
    size=26, weight="700", family="sans")
txt(40, 74, "Über diese Platine läuft nirgends Laststrom — weder der Streifen noch der "
    "geschalteten Verbraucher. Netzliste in hardware/platine-signal.md",
    size=13, fill=DIM, family="sans")

# ------------------------------------------------------- Stromversorgung ---

panel(40, 96, 620, 270, "Stromversorgung")

p = connector(170, 206, 2, "J1", "UBEC — nur die Platine", ["+5V", "GND"], pitch=40)
wire(p[0], (120, 222), (120, 150))
wire(p[1], (100, 262), (100, 296))
gnd(100, 296, "")

wire((120, 150), (300, 150))
dot(250, 150)
supply(250, 150, "+5V")
dot(300, 150)
wire((300, 150), (300, 180))
cap(300, 217, "C1", "10 µF")
wire((300, 247), (300, 265))
gnd(300, 265, "")
txt(300, 316, "MLCC — damit erübrigt sich ein zweiter, kleinerer Kondensator",
    anchor="middle", size=10, fill=DIM, family="sans")

txt(140, 334, "Zwei Adern vom UBEC, rund 100 mA. Hier hängt nichts von den "
    "geschalteten Lasten — die haben ihre eigene Versorgung an J5.",
    size=11, fill=DIM, family="sans")
txt(140, 354, "Der Elko der Streifen gehört ans UBEC, nicht hierher.",
    size=11, fill=DIM, family="sans")

# --------------------------------------------------------------- Pico -----

panel(40, 376, 620, 680, "Controller")

PX0, PX1, PY0 = 250, 470, 402
add(f'<rect x="{PX0}" y="{PY0}" width="{PX1-PX0}" height="620" rx="6" fill="#fff" '
    f'stroke="{INK}" stroke-width="2.2"/>')
txt((PX0 + PX1) / 2, PY0 + 26, "U1", anchor="middle", size=14, weight="700")
txt((PX0 + PX1) / 2, PY0 + 45, "Raspberry Pi Pico", anchor="middle", size=12)
txt((PX0 + PX1) / 2, PY0 + 62, "auf Buchsenleisten", anchor="middle", size=11, fill=DIM)

LEFT = {
    1: ("GP0", "UART_TX"), 2: ("GP1", "UART_RX"), 3: ("GND", "#GND"),
    4: ("GP2", "DATA1"), 5: ("GP3", "DATA2"), 6: ("GP4", None),
    7: ("GP5", "SBUS"), 8: ("GND", "#GND"), 9: ("GP6", "REL1"),
    10: ("GP7", "REL2"), 11: ("GP8", None), 12: ("GP9", None),
    13: ("GND", "#GND"), 14: ("GP10", None), 15: ("GP11", None),
    16: ("GP12", None), 17: ("GP13", None), 18: ("GND", "#GND"),
    19: ("GP14", None), 20: ("GP15", None),
}
RIGHT = {
    40: ("VBUS", "#NC"), 39: ("VSYS", "#5V"), 38: ("GND", "#GND"),
    37: ("3V3_EN", None), 36: ("3V3_OUT", None), 35: ("ADC_VREF", None),
    34: ("GP28", None), 33: ("AGND", None), 32: ("GP27", None),
    31: ("GP26", None), 30: ("RUN", None), 29: ("GP22", None),
    28: ("GND", None), 27: ("GP21", None), 26: ("GP20", None),
    25: ("GP19", None), 24: ("GP18", None), 23: ("GND", None),
    22: ("GP17", None), 21: ("GP16", None),
}

PIN_Y0, PIN_DY, GNDBUS = 492, 27, 110
gnd_ys = []

for i in range(20):
    y = PIN_Y0 + i * PIN_DY
    name, net = LEFT[i + 1]
    add(f'<rect x="{PX0}" y="{y-7}" width="14" height="14" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
    txt(PX0 + 22, y + 5, str(i + 1), size=11, fill=DIM)
    txt(PX0 + 44, y + 5, name, size=12, fill=INK if net else DIM,
        weight="700" if net else "400")
    if net == "#GND":
        wire((PX0, y), (GNDBUS, y))
        gnd_ys.append(y)
    elif net:
        netlabel(PX0, y, net, side="left")

    rpin = 40 - i
    rname, rnet = RIGHT[rpin]
    add(f'<rect x="{PX1-14}" y="{y-7}" width="14" height="14" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
    txt(PX1 - 22, y + 5, str(rpin), anchor="end", size=11, fill=DIM)
    txt(PX1 - 44, y + 5, rname, anchor="end", size=12, fill=INK if rnet else DIM,
        weight="700" if rnet else "400")
    if rnet == "#5V":
        wire((PX1, y), (530, y))
        supply(530, y, "+5V")
    elif rnet == "#GND":
        wire((PX1, y), (570, y), (570, 620))
        gnd(570, 620, "")
    elif rnet == "#NC":
        wire((PX1, y), (494, y))
        add(f'<path d="M{488} {y-8} L{506} {y+8} M{488} {y+8} L{506} {y-8}" '
            f'stroke="{WARN}" stroke-width="2.6" fill="none" stroke-linecap="round"/>')

wire((GNDBUS, min(gnd_ys)), (GNDBUS, max(gnd_ys)))
for y in gnd_ys:
    dot(GNDBUS, y)
gnd(GNDBUS, max(gnd_ys), "")

txt(58, 1042, "GPIO 10–13 sind frei · VBUS niemals mit dem UBEC verbinden",
    size=11, fill=WARN, family="sans")

# ------------------------------------------------------ Debug-Schnittstelle

panel(40, 1086, 620, 200, "Debug-UART   ·   3,3 V")

p = connector(330, 1120, 3, "J7", "Konsole", ["TX (GP0)", "RX (GP1)", "GND"], pitch=40)
netlabel(p[0][0], p[0][1], "UART_TX", side="left")
resistor(250, p[1][1], "R8", "1 k", horiz=True, lead=18)
wire((289, p[1][1]), (304, p[1][1]))
netlabel(211, p[1][1], "UART_RX", side="left")
wire(p[2], (262, p[2][1]))
gnd(262, p[2][1], "")
txt(58, 1276, "R8 schützt GP1 gegen einen 5-V-Adapter — TX braucht das nicht, "
    "der ist ein Ausgang.",
    size=11, fill=DIM, family="sans")

# ------------------------------------------------------------- Hinweise ---

panel(40, 1316, 620, 320, "Worauf es beim Layout ankommt")

NOTES = [
    ("Sternpunkt", "liegt am UBEC. Streifen, Schaltmodule und Platine"),
    ("", "treffen sich dort, jedes mit eigener Ader."),
    ("5-V-Bahn", "trägt Platine und die Logikseite der Module."),
    ("", "Relaismodule ziehen je rund 80 mA — mit einrechnen."),
    ("Datenleitung", "DIN und Signalmasse als Paar zum Streifen führen,"),
    ("", "nebeneinander. R1/R2 an die U2-Ausgänge, nicht an J2/J3."),
    ("Signalmasse", "dünn halten. Sie soll den Rückstrom der Flanken"),
    ("", "führen, nicht Ampere aus dem Streifen abzweigen."),
    ("Alle Bahnen", "0,25 mm. Es gibt auf dieser Platine keinen Pfad,"),
    ("", "der mehr als etwa 250 mA führt."),
    ("Pegelwandler", "U2 so dicht an den Pico wie möglich, die 5-V-Seite"),
    ("", "darf lang sein, die 3,3-V-Seite nicht."),
]
for i, (key, line) in enumerate(NOTES):
    y = 1358 + i * 22
    if key:
        txt(62, y, key, size=12, weight="700", family="sans")
    txt(178, y, line, size=12, fill=DIM if not key else INK, family="sans")

# ------------------------------------------------------- Pegelwandler -----

panel(700, 96, 960, 604, "Pegelwandler   ·   SN74AHCT125N, alle vier Treiber benutzt")

# U2 als echtes DIP-14-Gehaeuse: alle vierzehn Pins mit Nummer, auch die beiden
# ungenutzten Treiber. Die Verbindung zu R1/R2 laeuft ueber Netznamen -- 1Y und
# 2Y liegen auf Pin 3 und 6, also auf derselben Seite wie die Eingaenge.
BX0, BX1, BY0, BY1 = 900, 1070, 175, 429
ROW0, DROW = 200, 34

txt(985, 146, "U2", anchor="middle", size=15, weight="700")
txt(985, 164, "SN74AHCT125N · DIP-14", anchor="middle", size=11, fill=DIM, family="sans")
add(f'<rect x="{BX0}" y="{BY0}" width="{BX1-BX0}" height="{BY1-BY0}" rx="6" '
    f'fill="#fff" stroke="{INK}" stroke-width="2.2"/>')

LEFT_PINS = [(1, "1OE", "GND"), (2, "1A", "DATA1"), (3, "1Y", "DATA1_5V"),
             (4, "2OE", "GND"), (5, "2A", "DATA2"), (6, "2Y", "DATA2_5V"),
             (7, "GND", "GND")]
RIGHT_PINS = [(14, "VCC", "#5V"), (13, "4OE", "GND"), (12, "4A", "REL2"),
              (11, "4Y", "OUT2"), (10, "3OE", "GND"), (9, "3A", "REL1"),
              (8, "3Y", "OUT1")]

for i, ((lp, lname, lnet), (rp, rname, rnet)) in enumerate(zip(LEFT_PINS, RIGHT_PINS)):
    y = ROW0 + i * DROW
    add(f'<rect x="{BX0-7}" y="{y-7}" width="14" height="14" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
    txt(BX0 - 18, y - 6, str(lp), anchor="end", size=10, fill=DIM)
    txt(BX0 + 16, y + 5, lname, size=12, weight="700")
    wire((BX0 - 7, y), (870, y))
    netlabel(870, y, lnet, side="left")

    add(f'<rect x="{BX1-7}" y="{y-7}" width="14" height="14" fill="#fff" stroke="{INK}" stroke-width="1.5"/>')
    txt(BX1 + 18, y - 6, str(rp), size=10, fill=DIM)
    txt(BX1 - 16, y + 5, rname, anchor="end", size=12, weight="700")
    if rnet == "#5V":
        wire((BX1 + 7, y), (1120, y))
        supply(1120, y, "+5V")
    elif rnet == "#NC":
        wire((BX1 + 7, y), (1108, y))
        add(f'<path d="M1102 {y-8} L1120 {y+8} M1102 {y+8} L1120 {y-8}" '
            f'stroke="{WARN}" stroke-width="2.6" fill="none" stroke-linecap="round"/>')
        txt(1132, y + 5, "offen", size=11, fill=WARN, family="sans")
    else:
        wire((BX1 + 7, y), (1100, y))
        netlabel(1100, y, rnet, side="right")

# C2 puffert genau die beiden Versorgungspins oben.
supply(985, 485, "+5V")
wire((985, 485), (985, 495))
cap(985, 525, "C2", "100 nF")
wire((985, 555), (985, 570))
gnd(985, 570, "")
txt(985, 632, "Abblockung von U2 — im Layout so dicht wie möglich an Pin 14 und 7",
    anchor="middle", size=11, fill=DIM, family="sans")

# Datenausgaenge zu den Streifen
for idx, (yc, net, rref, jref) in enumerate(((200, "DATA1_5V", "R1", "J2"),
                                             (320, "DATA2_5V", "R2", "J3"))):
    netlabel(1330, yc, net, side="left")
    wire((1330, yc), (1377, yc))
    resistor(1420, yc, rref, "330 Ω", horiz=True, lead=22)
    wire((1463, yc), (1484, yc))
    q = connector(1510, yc - 16, 2, jref, f"Strip {idx+1} — nur Daten", ["DIN", "GND"])
    wire(q[1], (1450, q[1][1]))
    gnd(1450, q[1][1], "")

txt(718, 650, "Enable ist aktiv low: Pin 1, 4, 10 und 13 an GND. Kanal 3 und 4 heben "
    "die Schaltsignale von 3,3 V auf 5 V — damit nimmt sie jedes Modul an.",
    size=11, fill=DIM, family="sans")
txt(718, 672, "Die Streifen holen ihre 5 V direkt am UBEC. Hierher kommen nur DIN und "
    "eine dünne Signalmasse — sie führt den Rückstrom der Flanken, nicht den LED-Strom.",
    size=11, fill=DIM, family="sans")

# ------------------------------------------------------ Schaltausgaenge ---

panel(700, 730, 960, 380, "Schaltausgänge   ·   5-V-Logik, was geschaltet wird hängt extern dran")

for idx, (yc, net, onet, rp, rs, jref) in enumerate((
        (850, "REL1", "OUT1", "R3", "R5", "J5"),
        (1010, "REL2", "OUT2", "R4", "R6", "J6"))):
    # Pulldown am Treibereingang: haelt den Ausgang aus, solange der GPIO nach
    # dem Einschalten noch hochohmig ist.
    netlabel(820, yc, net, side="left")
    wire((820, yc), (842, yc))
    resistor(885, yc, rp, "100 k", horiz=True, lead=22)
    wire((928, yc), (950, yc))
    netlabel(950, yc, "GND", side="right")

    # Ausgangsseite
    netlabel(1130, yc, onet, side="left")
    wire((1130, yc), (1153, yc))
    resistor(1215, yc, rs, "100 Ω", horiz=True, lead=22)
    wire((1277, yc), (1304, yc))
    j = connector(1330, yc - 76, 3, jref, f"Schaltausgang {idx+1}",
                  ["GND", "+5V", "SIG"], pitch=30)
    netlabel(j[0][0], j[0][1], "GND", side="left")
    netlabel(j[1][0], j[1][1], "+5V", side="left")

txt(718, 1070, "R3/R4 ziehen den Treibereingang auf Masse, solange der GPIO nach dem "
    "Einschalten hochohmig ist — sonst zieht ein Modul zufällig an.",
    size=11, fill=WARN, family="sans")
txt(718, 1092, "R5/R6 begrenzen den Strom bei Kurzschluss und dämpfen die Flanke auf der "
    "Zuleitung. Der Treiber liefert höchstens 8 mA je Ausgang.",
    size=11, fill=DIM, family="sans")

# --------------------------------------------------------- RC-Eingaenge ---

panel(700, 1140, 960, 256, "Empfänger   ·   nur SBUS")

p = connector(1000, 1186, 3, "J4", "SBUS vom Empfänger", ["GND", "n.c.", "SIG"], pitch=40)
wire(p[0], (760, p[0][1]), (760, 1230))
gnd(760, 1230, "")
wire(p[1], (944, p[1][1]))
add(f'<path d="M938 {p[1][1]-8} L956 {p[1][1]+8} M938 {p[1][1]+8} L956 {p[1][1]-8}" '
    f'stroke="{WARN}" stroke-width="2.6" fill="none" stroke-linecap="round"/>')
resistor(904, p[2][1], "R7", "1 k", horiz=True, lead=18)
wire((943, p[2][1]), (974, p[2][1]))
netlabel(865, p[2][1], "SBUS", side="left")

txt(718, 1334, "R7 begrenzt den Strom, falls der Empfänger 5-V-Pegel ausgibt: "
    "die Pico-GPIOs sind nicht 5-V-fest.",
    size=11, fill=WARN, family="sans")
txt(718, 1356, "Nur Masse und Signal — der Empfänger versorgt sich selbst. "
    "Kein PWM-Rückfall: ohne SBUS-Frames läuft das Modell ins Failsafe.",
    size=11, fill=DIM, family="sans")
txt(718, 1378, "GPIO 10–13 bleiben dadurch frei — Platz für zwei weitere Strips "
    "oder Relais in einer späteren Version.",
    size=11, fill=DIM, family="sans")



render("schaltplan-signal.svg")
