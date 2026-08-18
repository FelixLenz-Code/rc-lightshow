"""Gemeinsame Zeichenhelfer fuer die Plaene in diesem Ordner.

Kein eigenstaendiges Programm -- schaltplan_mosfet.py und schaltplan_signal.py
importieren hieraus, damit beide Varianten dieselbe Bildsprache behalten.
"""

from __future__ import annotations

import pathlib


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


def cap(x, y, ref, val, polarized=False, label_left=False):
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
    lx, anchor = (x - 24, "end") if label_left else (x + 24, "start")
    txt(lx, y - 4, ref, anchor=anchor, size=12, weight="700")
    txt(lx, y + 12, val, anchor=anchor, size=12, fill=DIM)


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




def begin(w: int, h: int) -> None:
    """Leert die Zeichenflaeche und legt Rahmen und Papier an."""
    out.clear()
    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">')
    add(f'<rect width="{w}" height="{h}" fill="{PAPER}"/>')


def render(name: str) -> pathlib.Path:
    add("</svg>")
    p = pathlib.Path(__file__).with_name(name)
    p.write_text("\n".join(out), encoding="utf-8")
    print(f"{p} geschrieben, {len(out)} Elemente")
    return p
