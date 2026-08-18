#!/usr/bin/env python3
"""Variante A -- die Platine schaltet die Lasten selbst.

Zwei WS2812-Strips, zwei MOSFET-Kanaele an Bord. Braucht dickes Kupfer im
Lastpfad; die Alternative ohne das steht in schaltplan_signal.py.

    python3 hardware/schaltplan_mosfet.py
"""

from svgkit import *   # noqa: F403



begin(1700, 1860)

txt(40, 48, "Bordplatine · Steuerung für 2 WS2812-Strips und 2 MOSFET-Kanäle",
    size=26, weight="700", family="sans")
txt(40, 74, "Der Strom der Streifen läuft NICHT über diese Platine — sie bekommt nur "
    "ihre eigene Versorgung. Netzliste und Layout-Regeln in hardware/platine-mosfet.md",
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

txt(58, 1042, "Nicht bezeichnete Pins bleiben unbeschaltet · VBUS niemals mit dem UBEC verbinden",
    size=11, fill=WARN, family="sans")

# ------------------------------------------------------ Debug-Schnittstelle

panel(40, 1086, 620, 200, "Debug-UART   ·   3,3 V")

p = connector(330, 1120, 3, "J9", "Konsole", ["TX (GP0)", "RX (GP1)", "GND"], pitch=40)
netlabel(p[0][0], p[0][1], "UART_TX", side="left")
resistor(250, p[1][1], "R12", "1 k", horiz=True, lead=18)
wire((289, p[1][1]), (304, p[1][1]))
netlabel(211, p[1][1], "UART_RX", side="left")
wire(p[2], (262, p[2][1]))
gnd(262, p[2][1], "")
txt(58, 1276, "R12 schützt GP1 gegen einen 5-V-Adapter — TX braucht das nicht, "
    "der ist ein Ausgang.",
    size=11, fill=DIM, family="sans")

# ------------------------------------------------------------- Hinweise ---

panel(40, 1316, 620, 320, "Worauf es beim Layout ankommt")

NOTES = [
    ("Sternpunkt", "liegt am UBEC, nicht auf der Platine. Streifen, Last"),
    ("", "und Platine treffen sich dort, jeder mit eigener Ader."),
    ("5-V-Bahn", "trägt nur noch die Platine, rund 100 mA. 0,5 mm"),
    ("", "genügt — der LED-Strom läuft hier nicht mehr durch."),
    ("Datenleitung", "DIN und Signalmasse als Paar zum Streifen führen,"),
    ("", "nebeneinander. R1/R2 an die U2-Ausgänge, nicht an J2/J3."),
    ("Signalmasse", "dünn halten. Sie soll den Rückstrom der Flanken"),
    ("", "führen, nicht Ampere aus dem Streifen abzweigen."),
    ("Lastpfad", "J5.1 über Q1/Q2 nach J6/J7 und über J5.2 zurück —"),
    ("", "nach Laststrom bemessen, Sternpunkt an J5.2."),
    ("Pegelwandler", "U2 so dicht an den Pico wie möglich, die 5-V-Seite"),
    ("", "darf lang sein, die 3,3-V-Seite nicht."),
]
for i, (key, line) in enumerate(NOTES):
    y = 1358 + i * 22
    if key:
        txt(62, y, key, size=12, weight="700", family="sans")
    txt(178, y, line, size=12, fill=DIM if not key else INK, family="sans")

# ------------------------------------------------------- Pegelwandler -----

panel(700, 96, 960, 604, "Pegelwandler   ·   SN74AHCT125N")

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
RIGHT_PINS = [(14, "VCC", "#5V"), (13, "4OE", "GND"), (12, "4A", "GND"),
              (11, "4Y", "#NC"), (10, "3OE", "GND"), (9, "3A", "GND"),
              (8, "3Y", "#NC")]

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

txt(718, 650, "Enable ist aktiv low: Pin 1, 4, 10 und 13 an GND. Die ungenutzten "
    "Eingänge Pin 9 und 12 ebenfalls — offene CMOS-Eingänge schwingen.",
    size=11, fill=WARN, family="sans")
txt(718, 672, "Die Streifen holen ihre 5 V direkt am UBEC. Hierher kommen nur DIN und "
    "eine dünne Signalmasse — sie führt den Rückstrom der Flanken, nicht den LED-Strom.",
    size=11, fill=DIM, family="sans")

# ---------------------------------------------------- MOSFET-Ausgaenge ----

panel(700, 680, 960, 784, "Geschaltete Ausgänge   ·   Low-Side, N-Kanal")

p = connector(830, 810, 2, "J5", "Lastversorgung — extern", ["+VL", "Lastmasse"], pitch=40)
netlabel(p[0][0], p[0][1], "+VL", side="left", color=VL)
wire(p[1], (756, p[1][1]), (756, 900))
gnd(756, 900, "")
txt(790, 932, "Beide Pins immer anschließen — Pin 2 ist der Rückweg von Q1/Q2",
    size=11, fill=DIM, family="sans")

for idx, (yc, rg, rp, qref, dref, jref, net) in enumerate((
        (964, "R3", "R4", "Q1", "D1", "J6", "REL1"),
        (1284, "R5", "R6", "Q2", "D2", "J7", "REL2"))):
    netlabel(830, yc, net, side="left")
    wire((830, yc), (852, yc))
    resistor(895, yc, rg, "100 Ω", horiz=True, lead=22)
    wire((938, yc), (960, yc))
    dot(960, yc)
    g, d, s = mosfet(1022, yc, qref, "AO3400A")

    wire((960, yc), (960, yc + 23))
    resistor(960, yc + 62, rp, "100 k", horiz=False, lead=18)
    wire((960, yc + 101), (1038, yc + 101))
    wire(s, (1038, yc + 101))
    gnd(999, yc + 101, "")

    lane = yc - 70
    wire(d, (1038, lane), (1304, lane))
    # Freilaufdiode auf +VL, eigener Zweig neben der Lastleitung
    dot(1150, lane)
    wire((1150, lane), (1150, lane - 6))
    diode(1150, lane - 40, dref, "SS14")
    wire((1150, lane - 74), (1150, lane - 92))
    netlabel(1150, lane - 92, "+VL", side="left", color=VL)
    j = connector(1330, lane - 72, 2, jref, f"Last {idx+1}", ["+VL", "Schaltausgang"], pitch=56)
    netlabel(j[0][0], j[0][1], "+VL", side="left", color=VL)

txt(718, 1446, "D1/D2 nur bei induktiver Last bestücken — und nach Laststrom wählen: "
    "SS14 hält 1 A, darüber SS34. Es wird low-side geschaltet.",
    size=11, fill=DIM, family="sans")
txt(718, 1468, "Das Plus der Last MUSS aus J6.1/J7.1 kommen. Von woanders geholt, "
    "leitet D1/D2 die fremde Spannung ins +VL-Netz.",
    size=11, fill=WARN, family="sans")
txt(718, 1490, "+VL kommt ausschließlich von J5 — es gibt keinen Weg vom 5-V-Netz "
    "der Platine zu den Lasten und keinen zurück.",
    size=11, fill=DIM, family="sans")

# --------------------------------------------------------- RC-Eingaenge ---

panel(700, 1544, 960, 256, "Empfänger   ·   nur SBUS")

p = connector(1000, 1590, 3, "J4", "SBUS vom Empfänger", ["GND", "n.c.", "SIG"], pitch=40)
wire(p[0], (760, p[0][1]), (760, 1634))
gnd(760, 1634, "")
wire(p[1], (944, p[1][1]))
add(f'<path d="M938 {p[1][1]-8} L956 {p[1][1]+8} M938 {p[1][1]+8} L956 {p[1][1]-8}" '
    f'stroke="{WARN}" stroke-width="2.6" fill="none" stroke-linecap="round"/>')
resistor(904, p[2][1], "R7", "1 k", horiz=True, lead=18)
wire((943, p[2][1]), (974, p[2][1]))
netlabel(865, p[2][1], "SBUS", side="left")

txt(718, 1738, "R7 begrenzt den Strom, falls der Empfänger 5-V-Pegel ausgibt: "
    "die Pico-GPIOs sind nicht 5-V-fest.",
    size=11, fill=WARN, family="sans")
txt(718, 1760, "Nur Masse und Signal — der Empfänger versorgt sich selbst. "
    "Kein PWM-Rückfall: ohne SBUS-Frames läuft das Modell ins Failsafe.",
    size=11, fill=DIM, family="sans")
txt(718, 1782, "GPIO 10–13 bleiben dadurch frei — Platz für zwei weitere Strips "
    "oder Relais in einer späteren Version.",
    size=11, fill=DIM, family="sans")


render("schaltplan-mosfet.svg")
