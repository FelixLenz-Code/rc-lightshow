#!/usr/bin/env python3
"""Zeichnet den Schaltplan der Bordplatine als SVG.

Die Platine ist die kleine Variante: zwei WS2812-Strips, zwei MOSFET-
Kanaele, Pico gesockelt. Die Netznamen hier sind dieselben, die in
hardware/platine.md als Netzliste stehen -- wer eines aendert, aendert
beides.

    python3 hardware/schaltplan.py

erzeugt hardware/schaltplan.svg.
"""

from __future__ import annotations

import pathlib

W, H = 1700, 1680

INK = "#15171a"        # Leitungen und Symbole
DIM = "#8a8377"        # Anmerkungen
PANEL = "#ffffff"
PANEL_EDGE = "#d9d4ca"
PAPER = "#faf8f4"
NET_BG = "#e9eff6"
NET_EDGE = "#5d7794"
NET_INK = "#26384b"
V5 = "#b8341f"         # 5-V-Netz
VL = "#8a6100"         # Lastspannung
WARN = "#a2431a"

out: list[str] = []


def add(s: str) -> None:
    out.append(s)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, anchor="start", size=13, fill=INK, weight="400", style="normal", family="mono"):
    fam = ("ui-monospace, 'DejaVu Sans Mono', monospace" if family == "mono"
           else "system-ui, 'DejaVu Sans', sans-serif")
    add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
        f'font-family="{fam}" fill="{fill}" font-weight="{weight}" '
        f'font-style="{style}">{esc(s)}</text>')


def wire(*pts, color=INK, width=2):
    d = " ".join(("M" if i == 0 else "L") + f"{x} {y}" for i, (x, y) in enumerate(pts))
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>')


def dot(x, y, color=INK):
    add(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def panel(x, y, w, h, title):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{PANEL}" '
        f'stroke="{PANEL_EDGE}" stroke-width="1.5"/>')
    txt(x + 18, y + 28, title, size=16, weight="700", family="sans")


def netlabel(x, y, name, side="right", color=NET_INK):
    """Netzname als Fahne. side=right: Fahne zeigt nach rechts weg."""
    w = 11 * len(name) + 22
    if side == "right":
        wire((x, y), (x + 14, y))
        bx = x + 14
        pts = f"{bx},{y} {bx+12},{y-13} {bx+w},{y-13} {bx+w},{y+13} {bx+12},{y+13}"
        tx, anchor = bx + 20, "start"
    else:
        wire((x, y), (x - 14, y))
        bx = x - 14
        pts = f"{bx},{y} {bx-12},{y-13} {bx-w},{y-13} {bx-w},{y+13} {bx-12},{y+13}"
        tx, anchor = bx - 20, "end"
    add(f'<polygon points="{pts}" fill="{NET_BG}" stroke="{NET_EDGE}" stroke-width="1.4"/>')
    txt(tx, y + 5, name, anchor=anchor, size=13, fill=color, weight="700")


def gnd(x, y, label="GND"):
    wire((x, y), (x, y + 16))
    for i, half in enumerate((14, 9, 4)):
        yy = y + 16 + i * 6
        wire((x - half, yy), (x + half, yy), width=2.2)
    if label:
        txt(x, y + 52, label, anchor="middle", size=11, fill=DIM)


def supply(x, y, name, color=V5):
    """Versorgungssymbol, Pfeil nach oben."""
    wire((x, y), (x, y - 16), color=color)
    add(f'<polygon points="{x},{y-26} {x-9},{y-14} {x+9},{y-14}" fill="{color}"/>')
    txt(x, y - 34, name, anchor="middle", size=12, fill=color, weight="700")


def resistor(x, y, ref, val=None, horiz=True, lead=22):
    """Widerstand, (x,y) ist die Mitte."""
    if horiz:
        wire((x - lead - 21, y), (x - 21, y))
        wire((x + 21, y), (x + lead + 21, y))
        add(f'<rect x="{x-21}" y="{y-9}" width="42" height="18" fill="#fff" '
            f'stroke="{INK}" stroke-width="2" rx="2"/>')
        txt(x, y - 17, ref, anchor="middle", size=12, weight="700")
        if val:
            txt(x, y + 30, val, anchor="middle", size=12, fill=DIM)
    else:
        wire((x, y - lead - 21), (x, y - 21))
        wire((x, y + 21), (x, y + lead + 21))
        add(f'<rect x="{x-9}" y="{y-21}" width="18" height="42" fill="#fff" '
            f'stroke="{INK}" stroke-width="2" rx="2"/>')
        txt(x + 16, y - 3, ref, size=12, weight="700")
        if val:
            txt(x + 16, y + 13, val, size=12, fill=DIM)


def cap(x, y, ref, val, polarized=False):
    """Kondensator, senkrecht; (x,y) ist die Mitte."""
    wire((x, y - 30), (x, y - 7))
    wire((x, y + 30), (x, y + 7))
    wire((x - 17, y - 7), (x + 17, y - 7), width=2.4)
    if polarized:
        add(f'<path d="M{x-17} {y+7} A 17 12 0 0 0 {x+17} {y+7}" fill="none" '
            f'stroke="{INK}" stroke-width="2.4"/>')
        txt(x - 24, y - 12, "+", anchor="middle", size=15, weight="700")
    else:
        wire((x - 17, y + 7), (x + 17, y + 7), width=2.4)
    txt(x + 24, y - 4, ref, size=12, weight="700")
    txt(x + 24, y + 12, val, size=12, fill=DIM)


def buffer_gate(x, y, ref, pin_in, pin_out, pin_oe):
    """Ein Treiber des 74AHCT125: Dreieck mit invertiertem Enable oben."""
    add(f'<polygon points="{x},{y-34} {x},{y+34} {x+58},{y}" fill="#fff" '
        f'stroke="{INK}" stroke-width="2.2" stroke-linejoin="round"/>')
    txt(x + 16, y + 5, ref, size=13, weight="700")
    # Eingang
    wire((x - 26, y), (x, y))
    txt(x - 6, y - 9, str(pin_in), anchor="end", size=11, fill=DIM)
    # Ausgang
    wire((x + 58, y), (x + 84, y))
    txt(x + 64, y - 9, str(pin_out), size=11, fill=DIM)
    # Enable, active low
    add(f'<circle cx="{x+21}" cy="{y-28}" r="6" fill="#fff" stroke="{INK}" stroke-width="2"/>')
    wire((x + 21, y - 34), (x + 21, y - 60))
    txt(x + 27, y - 44, str(pin_oe), size=11, fill=DIM)
    return (x + 21, y - 60)   # oberes Ende der Enable-Leitung


def mosfet(x, y, ref, val):
    """N-Kanal-MOSFET, Anreicherungstyp. (x,y) = Mitte des Kanals.
    Gibt (Gate, Drain, Source) als Anschlusspunkte zurueck."""
    # Gate-Zuleitung und Gate-Platte
    wire((x - 62, y), (x - 30, y))
    wire((x - 30, y - 24), (x - 30, y + 24), width=2.4)
    # Kanal, drei Segmente
    for y0, y1 in ((y - 24, y - 10), (y - 7, y + 7), (y + 10, y + 24)):
        wire((x - 18, y0), (x - 18, y1), width=2.4)
    # Drain oben, Source unten
    wire((x - 18, y - 17), (x + 16, y - 17), (x + 16, y - 56))
    wire((x - 18, y + 17), (x + 16, y + 17), (x + 16, y + 56))
    # Bulk-Verbindung mit Pfeil zum Kanal
    wire((x + 16, y), (x - 18, y))
    add(f'<polygon points="{x-18},{y} {x-6},{y-6} {x-6},{y+6}" fill="{INK}"/>')
    txt(x + 30, y - 6, ref, size=13, weight="700")
    txt(x + 30, y + 10, val, size=12, fill=DIM)
    return (x - 62, y), (x + 16, y - 56), (x + 16, y + 56)


def diode(x, y, ref, val):
    """Diode senkrecht, Kathode oben. (x,y) = Mitte."""
    wire((x, y - 34), (x, y - 12))
    wire((x, y + 34), (x, y + 12))
    add(f'<polygon points="{x-14},{y+12} {x+14},{y+12} {x},{y-12}" fill="#fff" '
        f'stroke="{INK}" stroke-width="2.2" stroke-linejoin="round"/>')
    wire((x - 15, y - 12), (x + 15, y - 12), width=2.6)
    txt(x + 22, y - 4, ref, size=12, weight="700")
    txt(x + 22, y + 12, val, size=12, fill=DIM)


def connector(x, y, pins, ref, caption, names, pitch=34):
    """Steckverbinder, Pins nach links. Gibt die Anschlusspunkte zurueck."""
    h = pitch * pins + 16
    add(f'<rect x="{x}" y="{y}" width="96" height="{h}" rx="4" fill="#fff" '
        f'stroke="{INK}" stroke-width="2"/>')
    txt(x + 48, y - 26, ref, anchor="middle", size=13, weight="700")
    txt(x + 48, y - 10, caption, anchor="middle", size=11, fill=DIM)
    pts = []
    for i, name in enumerate(names):
        py = y + 16 + i * pitch
        add(f'<rect x="{x+8}" y="{py-8}" width="16" height="16" fill="#fff" '
            f'stroke="{INK}" stroke-width="1.6"/>')
        txt(x + 32, py + 5, f"{i+1} {name}", size=12)
        wire((x, py), (x - 26, py))
        pts.append((x - 26, py))
    return pts


# ---------------------------------------------------------------- Rahmen ---

add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

txt(40, 48, "Bordplatine · 2 WS2812-Strips, 2 MOSFET-Kanäle, Pico gesockelt",
    size=26, weight="700", family="sans")
txt(40, 74, "Netznamen verbinden über Blöcke hinweg — gleicher Name ist dasselbe Netz. "
    "Netzliste, Stückliste und Layout-Regeln in hardware/platine.md",
    size=13, fill=DIM, family="sans")

# ------------------------------------------------------- Stromversorgung ---

panel(40, 96, 620, 270, "Stromversorgung")

p = connector(170, 206, 2, "J1", "UBEC 5 V / 3 A", ["+5V", "GND"], pitch=40)
wire(p[0], (120, 222), (120, 150))
wire(p[1], (100, 262), (100, 296))
gnd(100, 296, "")

wire((120, 150), (450, 150))
dot(250, 150)
supply(250, 150, "+5V")
for cx, ref, val, pol in ((300, "C1", "1000 µF", True), (400, "C3", "100 nF", False)):
    dot(cx, 150)
    wire((cx, 150), (cx, 180))
    cap(cx, 217, ref, val, polarized=pol)
    wire((cx, 247), (cx, 265))
    gnd(cx, 265, "")

add(f'<rect x="450" y="139" width="46" height="22" rx="4" fill="#fff" stroke="{INK}" stroke-width="2"/>')
wire((462, 150), (484, 150), width=3)
txt(473, 131, "JP1", anchor="middle", size=12, weight="700")
wire((496, 150), (530, 150))
netlabel(530, 150, "+5V_RC")
# JP2 legt die Lastversorgung wahlweise auf das UBEC
# JP2 waehlt die Quelle fuer +VL. Pin 2 ist der gemeinsame Anschluss, der
# Shunt kann nur auf 1-2 oder auf 2-3 stecken -- beides zugleich geht nicht.
p = connector(560, 200, 3, "JP2", "Quelle für +VL", ["+5V", "+VL", "VL_J5"])
supply(500, p[0][1], "+5V")
wire(p[0], (500, p[0][1]))
netlabel(p[1][0], p[1][1], "+VL", side="left", color=VL)
netlabel(p[2][0], p[2][1], "VL_J5", side="left", color=VL)

txt(140, 334, "JP2 auf 1–2: Lasten laufen aus dem UBEC, J5 bleibt leer. "
    "Auf 2–3: Lasten aus J5.",
    size=11, fill=WARN, family="sans")
txt(140, 354, "JP1 nur schließen, wenn der Empfänger vom selben UBEC leben soll",
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
    13: ("GND", "#GND"), 14: ("GP10", "PWM1"), 15: ("GP11", "PWM2"),
    16: ("GP12", "PWM3"), 17: ("GP13", "PWM4"), 18: ("GND", "#GND"),
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

panel(40, 1086, 620, 200, "Debug-UART   ·   3,3 V, kein 5-V-Adapter")

p = connector(330, 1130, 3, "J9", "Konsole", ["TX (GP0)", "RX (GP1)", "GND"], pitch=40)
netlabel(p[0][0], p[0][1], "UART_TX", side="left")
netlabel(p[1][0], p[1][1], "UART_RX", side="left")
wire(p[2], (262, p[2][1]))
gnd(262, p[2][1], "")

# ------------------------------------------------------------- Hinweise ---

panel(40, 1316, 620, 320, "Worauf es beim Layout ankommt")

NOTES = [
    ("Sternmasse", "Streifen-, Last- und Controllermasse treffen sich am"),
    ("", "UBEC-Anschluss J1/J5, nicht in Reihe durch den Pico."),
    ("5-V-Bahn", "mindestens 2 mm breit, kurz und direkt zu J2/J3."),
    ("", "60 LEDs auf Weiß ziehen 3,6 A."),
    ("C1", "gehört ans Ende der 5-V-Bahn, dicht an die"),
    ("", "Streifenanschlüsse — dort entsteht die Einschaltspitze."),
    ("Lastpfad", "J5 über Q1/Q2 nach J6/J7 getrennt von der Signalmasse"),
    ("", "führen, erst am Sternpunkt zusammen."),
    ("Datenleitung", "R1/R2 direkt an die U2-Ausgänge setzen, nicht an"),
    ("", "den Streifenstecker."),
    ("Pegelwandler", "U2 so dicht an den Pico wie möglich, die 5-V-Seite"),
    ("", "darf lang sein, die 3,3-V-Seite nicht."),
]
for i, (key, line) in enumerate(NOTES):
    y = 1358 + i * 22
    if key:
        txt(62, y, key, size=12, weight="700", family="sans")
    txt(178, y, line, size=12, fill=DIM if not key else INK, family="sans")

# ------------------------------------------------------- Pegelwandler -----

panel(700, 96, 960, 430, "Pegelwandler und LED-Ausgänge   ·   U2 = SN74AHCT125N, DIP-14")

supply(730, 215, "+5V")
wire((730, 215), (730, 247))
cap(730, 277, "C2", "100 nF")
wire((730, 307), (730, 340))
gnd(730, 340, "")
txt(746, 219, "14", size=12, weight="700")
txt(746, 344, "7", size=12, weight="700")
txt(770, 400, "Versorgung U2", anchor="middle", size=11, fill=DIM, family="sans")

for idx, (yc, ref, pins, data_net, rref, jref) in enumerate((
        (215, "U2A", (2, 3, 1), "DATA1", "R1", "J2"),
        (375, "U2B", (5, 6, 4), "DATA2", "R2", "J3"))):
    gx = 880
    netlabel(gx - 26, yc, data_net, side="left")
    oe = buffer_gate(gx, yc, ref, *pins)
    netlabel(oe[0], oe[1], "GND", side="right")
    resistor(1007, yc, rref, "330 Ω", horiz=True, lead=22)
    wire((1050, yc), (1284, yc))
    p = connector(1310, yc - 50, 3, jref, f"WS2812 Strip {idx+1}", ["+5V", "DIN", "GND"])
    wire(p[0], (1240, p[0][1]))
    supply(1240, p[0][1], "+5V")
    wire(p[2], (1250, p[2][1]))
    gnd(1250, p[2][1], "")

txt(718, 486, "Enable ist aktiv low: Pin 1, 4, 10 und 13 an GND. Unbenutzte Eingänge "
    "Pin 9 und 12 ebenfalls an GND — offene CMOS-Eingänge schwingen.",
    size=11, fill=WARN, family="sans")
txt(718, 508, "Ausgänge Pin 8 und 11 bleiben offen. C2 direkt an die Versorgungspins, "
    "nicht an den Platinenrand.",
    size=11, fill=DIM, family="sans")

# ---------------------------------------------------- MOSFET-Ausgaenge ----

panel(700, 556, 960, 760, "Geschaltete Ausgänge   ·   Low-Side, N-Kanal")

p = connector(830, 636, 2, "J5", "Lastversorgung", ["VL_J5", "GND"], pitch=40)
netlabel(p[0][0], p[0][1], "VL_J5", side="left", color=VL)
wire(p[1], (756, p[1][1]), (756, 726))
gnd(756, 726, "")
txt(800, 758, "+VL kommt über JP2 — aus J5 oder aus dem UBEC",
    size=11, fill=DIM, family="sans")

for idx, (yc, rg, rp, qref, dref, jref, net) in enumerate((
        (790, "R3", "R4", "Q1", "D1", "J6", "REL1"),
        (1110, "R5", "R6", "Q2", "D2", "J7", "REL2"))):
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

txt(718, 1272, "D1/D2 nur bei induktiver Last bestücken (Relaisspule, Motor, Schütz). "
    "Die Masse der Last muss die Platinenmasse sein — es wird low-side geschaltet.",
    size=11, fill=DIM, family="sans")
txt(718, 1294, "AO3400A hält 30 V. Hängt die Last an mehr als 4S, gehört ein FET mit "
    "höherer Sperrspannung hierhin.",
    size=11, fill=WARN, family="sans")

# --------------------------------------------------------- RC-Eingaenge ---

panel(700, 1346, 960, 290, "Empfänger")

p = connector(1000, 1406, 3, "J4", "SBUS", ["GND", "+5V_RC", "SIG"], pitch=44)
wire(p[0], (760, p[0][1]), (760, 1560))
gnd(760, 1560, "")
netlabel(p[1][0], p[1][1], "+5V_RC", side="left")
resistor(904, p[2][1], "R7", "1 k", horiz=True, lead=18)
wire((943, p[2][1]), (974, p[2][1]))
netlabel(865, p[2][1], "SBUS", side="left")

q = connector(1400, 1400, 4, "J8", "PWM 1–4", ["SIG1", "SIG2", "SIG3", "SIG4"], pitch=44)
for i, pt in enumerate(q):
    resistor(1304, pt[1], f"R{8+i}", horiz=True, lead=18)
    wire((1343, pt[1]), (1374, pt[1]))
    netlabel(1265, pt[1], f"PWM{i+1}", side="left")

txt(718, 1612, "R7–R11 je 1 k begrenzen den Strom, falls der Empfänger 5-V-Pegel ausgibt: "
    "die Pico-GPIOs sind nicht 5-V-fest. Masse des Empfängers an J4 Pin 1.",
    size=11, fill=WARN, family="sans")

add("</svg>")

path = pathlib.Path(__file__).with_name("schaltplan.svg")
path.write_text("\n".join(out), encoding="utf-8")
print(f"{path} geschrieben, {len(out)} Elemente")
