#!/usr/bin/env python3
"""Zeichnet die komplette Bordplatine, eingefaerbt nach noetiger Bahnbreite.

Anders als schaltplan.svg zeigt dieser Plan jede Verbindung so dick, wie sie im
Layout werden muss. Bezeichner sind die aus der EasyEDA-Zeichnung.

    python3 hardware/strompfade_mosfet.py

erzeugt hardware/strompfade-mosfet.svg.
"""

from __future__ import annotations

import pathlib

W, H = 1800, 1300

INK = "#15171a"
DIM = "#8a8377"
PAPER = "#faf8f4"
PANEL = "#ffffff"
EDGE = "#d9d4ca"
WIRE = "#3f3b35"     # 0,25 mm
MID = "#c07a1a"      # 2 mm
FAT = "#a8420f"      # 3 mm
WARN = "#a2431a"

WT, WM, WF = 2.4, 9, 15

out: list[str] = []
add = out.append


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, anchor="start", size=12, fill=INK, weight="400", mono=False):
    fam = ("ui-monospace, 'DejaVu Sans Mono', monospace" if mono
           else "system-ui, 'DejaVu Sans', sans-serif")
    add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
        f'font-family="{fam}" fill="{fill}" font-weight="{weight}">{esc(s)}</text>')


def wire(*pts, color=WIRE, width=WT):
    d = " ".join(("M" if i == 0 else "L") + f"{x} {y}" for i, (x, y) in enumerate(pts))
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>')


def dot(x, y, color=WIRE, r=5):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')


def part(x, y, w, h, ref, sub=None):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PANEL}" '
        f'stroke="{INK}" stroke-width="2"/>')
    cy = y + h / 2 + (-6 if sub else 5)
    txt(x + w / 2, cy, ref, anchor="middle", size=14, weight="700")
    if sub:
        txt(x + w / 2, cy + 19, sub, anchor="middle", size=11, fill=DIM)


def res(cx, cy, ref, val, horiz=True):
    if horiz:
        add(f'<rect x="{cx-38}" y="{cy-11}" width="76" height="22" fill="#fff" '
            f'stroke="{WIRE}" stroke-width="2" rx="2"/>')
        txt(cx, cy - 19, ref, anchor="middle", size=11, weight="700")
        txt(cx, cy + 28, val, anchor="middle", size=11, fill=DIM)
        wire((cx - 76, cy), (cx - 38, cy))
        wire((cx + 38, cy), (cx + 76, cy))
    else:
        add(f'<rect x="{cx-11}" y="{cy-38}" width="22" height="76" fill="#fff" '
            f'stroke="{WIRE}" stroke-width="2" rx="2"/>')
        txt(cx + 18, cy - 4, ref, size=11, weight="700")
        txt(cx + 18, cy + 12, val, size=11, fill=DIM)
        wire((cx, cy - 76), (cx, cy - 38))
        wire((cx, cy + 38), (cx, cy + 76))


def cap(cx, cy, ref, val):
    wire((cx, cy - 40), (cx, cy - 9))
    wire((cx, cy + 40), (cx, cy + 9))
    wire((cx - 20, cy - 9), (cx + 20, cy - 9), width=3)
    wire((cx - 20, cy + 9), (cx + 20, cy + 9), width=3)
    txt(cx + 28, cy - 3, ref, size=11, weight="700")
    txt(cx + 28, cy + 13, val, size=11, fill=DIM)


def diode(cx, cy, color, width):
    """Waagerecht, Kathode rechts."""
    add(f'<polygon points="{cx-16},{cy-15} {cx-16},{cy+15} {cx+11},{cy}" fill="#fff" '
        f'stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
    wire((cx + 11, cy - 16), (cx + 11, cy + 16), color=color, width=width)


def gnd(x, y):
    wire((x, y), (x, y + 12))
    for i, hw in enumerate((13, 8, 4)):
        wire((x - hw, y + 12 + i * 5), (x + hw, y + 12 + i * 5), width=2.4)


# ------------------------------------------------------------------ Kopf ---

add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

txt(40, 46, "Bordplatine · vollständiger Plan mit Bahnbreiten", size=25, weight="700")
txt(40, 70, "Ausgelegt für +VL bis 17 V (4S) und 3 A je Kanal · 35 µm Kupfer · "
    "Bezeichner wie in der EasyEDA-Zeichnung", size=12, fill=DIM)

for i, (col, wd, lab) in enumerate(((WIRE, WT, "0,25 mm — Signale und Versorgung der Platine"),
                                    (MID, WM, "2 mm — je Lastzweig, bis 3 A"),
                                    (FAT, WF, "3 mm — Stämme zu U9, bis 5 A"))):
    x = 900 + i * 300
    wire((x, 58), (x + 34, 58), color=col, width=wd)
    txt(x + 44, 62, lab, size=11, fill=DIM)

# ======================================================== Steuerteil =======

add(f'<rect x="40" y="100" width="1720" height="600" rx="10" fill="{PANEL}" '
    f'stroke="{EDGE}" stroke-width="1.5"/>')
txt(60, 130, "Steuerteil", size=15, weight="700")
txt(150, 130, "— hier fließt nichts, was zählt: Pico und Pegelwandler zusammen "
    "unter 100 mA", size=12, fill=DIM)

RAIL5, RAILG = 160, 660
wire((300, RAIL5), (1420, RAIL5))
wire((250, RAILG), (1700, RAILG))
txt(310, RAIL5 - 10, "+5V", size=12, weight="700", fill=WARN)
txt(258, RAILG + 22, "GND (Signalmasse)", size=12, weight="700")

# --- Versorgung
part(80, 210, 160, 80, "U2", "UBEC 5 V")
txt(248, 240, "1  +5V", size=11)
txt(248, 275, "2  GND", size=11)
wire((240, 235), (300, 235), (300, RAIL5))
dot(300, RAIL5)
wire((240, 270), (272, 270), (272, RAILG))
dot(272, RAILG)
wire((370, RAIL5), (370, 260))
cap(370, 300, "C1", "10 µF")
wire((370, 340), (370, RAILG))
dot(370, RAIL5); dot(370, RAILG)

# --- Empfaenger
part(80, 390, 160, 90, "H2", "Empfänger")
txt(248, 425, "SIG", size=11)
txt(248, 460, "GND", size=11)
res(330, 420, "R2", "1 k")
wire((240, 420), (254, 420))
wire((406, 420), (590, 420))
wire((240, 455), (262, 455), (262, RAILG))
dot(262, RAILG)

# --- Konsole
part(80, 520, 160, 110, "H1", "Konsole")
txt(248, 550, "TX", size=11)
txt(248, 585, "RX", size=11)
txt(248, 620, "GND", size=11)
wire((240, 545), (430, 545), (430, 270), (590, 270))
res(330, 580, "R1", "1 k")
wire((240, 580), (254, 580))
wire((406, 580), (466, 580), (466, 305), (590, 305))
wire((240, 615), (252, 615), (252, RAILG))
dot(252, RAILG)

# --- Pico
part(640, 230, 240, 380, "Pico", "Raspberry Pi Pico W")
PICO_L = [(270, "1", "GP0"), (305, "2", "GP1"), (345, "4", "GP2"), (380, "5", "GP3"),
          (420, "7", "GP5"), (460, "9", "GP6"), (495, "10", "GP7")]
for y, pin, name in PICO_L:
    wire((640, y), (590, y))
    txt(636, y - 6, pin, anchor="end", size=10, fill=DIM)
    txt(652, y + 4, name, size=11, weight="700")
wire((640, 560), (560, 560), (560, RAILG))
dot(560, RAILG)
txt(652, 564, "GND 3·8·13·18", size=11, weight="700")
wire((880, 270), (990, 270), (990, RAIL5))
dot(990, RAIL5)
txt(876, 264, "39", anchor="end", size=10, fill=DIM)
txt(868, 274, "VSYS", anchor="end", size=11, weight="700")
wire((880, 310), (960, 310), (960, RAILG))
dot(960, RAILG)
txt(876, 304, "38", anchor="end", size=10, fill=DIM)
txt(868, 314, "GND", anchor="end", size=11, weight="700")

# --- Pegelwandler
part(1060, 230, 220, 380, "SN74AHCT125N", "Pegelwandler")
wire((590, 345), (540, 345), (540, 195), (1040, 195), (1040, 300), (1060, 300))
wire((590, 380), (520, 380), (520, 215), (1000, 215), (1000, 350), (1060, 350))
txt(1056, 294, "2", anchor="end", size=10, fill=DIM)
txt(1072, 304, "1A", size=11, weight="700")
txt(1056, 344, "5", anchor="end", size=10, fill=DIM)
txt(1072, 354, "2A", size=11, weight="700")
txt(1268, 304, "1Y", anchor="end", size=11, weight="700")
txt(1284, 294, "3", size=10, fill=DIM)
txt(1268, 354, "2Y", anchor="end", size=11, weight="700")
txt(1284, 344, "6", size=10, fill=DIM)
wire((1170, 230), (1170, RAIL5)); dot(1170, RAIL5)
txt(1178, 200, "14 VCC", size=11, weight="700")
wire((1170, 610), (1170, RAILG)); dot(1170, RAILG)
txt(1178, 636, "7 GND", size=11, weight="700")
wire((1060, 520), (1010, 520), (1010, RAILG)); dot(1010, RAILG)
txt(1072, 524, "1·4·10·13 OE", size=11, weight="700")
txt(1072, 540, "9·12 unbenutzt", size=10, fill=DIM)
wire((1340, RAIL5), (1340, 260))
cap(1340, 300, "C2", "100 nF")
wire((1340, 340), (1340, RAILG))
dot(1340, RAIL5); dot(1340, RAILG)
txt(1300, 214, "C2 gehört an Pin 14/7", size=10, fill=WARN)

# --- LED-Ausgaenge
for y, rref, jref, lab in ((300, "R3", "U3", "Strip 1"), (400, "R4", "U4", "Strip 2")):
    res(1500, y, rref, "330 Ω")
    wire((1280, y), (1424, y))
    part(1600, y - 30, 150, 60, jref, lab)
    wire((1576, y), (1600, y))
    txt(1608, y - 4, "1  DIN", size=11)
    txt(1608, y + 16, "2  GND", size=11)
    gx = 1570 if y < 350 else 1548
    wire((1600, y + 22), (gx, y + 22), (gx, RAILG))
    dot(gx, RAILG)
txt(1500, 470, "Signalmasse zu U3/U4 bewusst dünn lassen", anchor="middle",
    size=11, fill=WARN)

# ========================================================== Lastteil =======

add(f'<rect x="40" y="730" width="1720" height="530" rx="10" fill="{PANEL}" '
    f'stroke="{EDGE}" stroke-width="1.5"/>')
txt(60, 760, "Lastteil", size=15, weight="700", fill=FAT)
txt(140, 760, "— der einzige Pfad, auf dem Ampere fließen. Hin- und Rückweg "
    "gleich breit.", size=12, fill=DIM)

VL, RET = 812, 1172
CH = [(760, "U8", "Last 1", "D2", "U11", "R5", "R6"),
      (1200, "U7", "Last 2", "D1", "U10", "R7", "R8")]

part(80, 850, 170, 100, "U9", "Lastversorgung")
txt(258, 866, "1  +VL", size=11)
txt(258, 954, "2  Lastmasse", size=11)
wire((250, 880), (360, 880), (360, VL), color=FAT, width=WF)
wire((250, 920), (300, 920), (300, RET), color=FAT, width=WF)

wire((360, VL), (760, VL), color=FAT, width=WF)
wire((760, VL), (1375, VL), color=MID, width=WM)
wire((300, RET), (760, RET), color=FAT, width=WF)
wire((760, RET), (1200, RET), color=MID, width=WM)
txt(560, VL - 22, "3 mm", anchor="middle", size=14, weight="700", fill=FAT)
txt(1060, VL - 22, "2 mm", anchor="middle", size=14, weight="700", fill=MID)
txt(600, RET + 30, "3 mm", anchor="middle", size=14, weight="700", fill=FAT)
txt(980, RET + 30, "2 mm", anchor="middle", size=14, weight="700", fill=MID)

for cx, jref, last, dref, qref, rg, rp in CH:
    dot(cx, VL, MID, r=7); dot(cx, RET, MID, r=7)
    wire((cx, VL), (cx, 882), color=MID, width=WM)
    part(cx - 95, 882, 190, 76, jref, f"{last} — extern")
    wire((cx, 958), (cx, 1032), color=MID, width=WM)
    dot(cx, 996, MID, r=7)
    wire((cx, 996), (cx + 175, 996), (cx + 175, VL), color=MID, width=WM)
    diode(cx + 175, 996, MID, WM)
    dot(cx + 175, VL, MID, r=7)
    txt(cx + 196, 1002, dref, size=12, weight="700", fill=MID)

    part(cx - 80, 1032, 160, 100, qref, "AO3400A")
    txt(cx - 72, 1056, "D", size=11, weight="700", fill=DIM)
    txt(cx - 72, 1124, "S", size=11, weight="700", fill=DIM)
    txt(cx - 72, 1090, "G", size=11, weight="700", fill=DIM)
    wire((cx, 1132), (cx, RET), color=MID, width=WM)
    txt(cx + 22, 1158, "2 mm", size=12, weight="700", fill=MID)
    txt(cx + 22, 872, "2 mm", size=12, weight="700", fill=MID)

    # Gate -- duenn
    wire((cx - 80, 1082), (cx - 140, 1082))
    dot(cx - 140, 1082)
    res(cx - 225, 1082, rg, "100 Ω")
    px = cx - 140
    wire((px, 1082), (px, 1108))
    add(f'<rect x="{px-11}" y="1108" width="22" height="40" fill="#fff" '
        f'stroke="{WIRE}" stroke-width="2" rx="2"/>')
    txt(px + 18, 1124, rp, size=11, weight="700")
    txt(px + 18, 1140, "100 k", size=11, fill=DIM)
    wire((px, 1148), (px, RET))
    dot(px, RET)

wire((590, 460), (450, 460), (450, 1082), (535 - 76, 1082))
wire((590, 495), (490, 495), (490, 1226), (975 - 76, 1226), (975 - 76, 1082))

# Sternpunkt
dot(420, RET, FAT, r=9)
wire((420, RET), (420, RAILG))
dot(420, RAILG)
txt(420, RET - 26, "Sternpunkt", anchor="middle", size=12, weight="700", fill=FAT)
txt(420, 1246, "hier trifft die Signalmasse auf die Lastmasse", anchor="middle",
    size=11, fill=FAT)

add("</svg>")

p = pathlib.Path(__file__).with_name("strompfade-mosfet.svg")
p.write_text("\n".join(out), encoding="utf-8")
print(f"{p} geschrieben, {len(out)} Elemente")
