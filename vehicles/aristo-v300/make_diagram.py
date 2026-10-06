#!/usr/bin/env python3
"""Generate a verified 2JZ-GTE VVTi wasted-spark ignition diagram (engine-bay layout).

Physical layout: inline-6 with cylinders 1-6, coil packs on the valve cover in
physical order 1-3-2 (front to back), igniter as the bay-mounted module.

Findings verified 2026-10-06 against: Haltech 1JZ/2JZ igniter tech doc,
2jzgarage (IS300 workshop manual / Japanese wiring diagrams), Wiring
Specialties JZA80 VVTi pinout, wilbo666 JZS161 Aristo wiring page.
Applies identically to JZS161 Aristo and JZA80 Supra.

Igniter bay location NOT verified -- drawn schematically, confirm on car.
Outputs: DH61_igniter_verified.svg and DH61_igniter_verified.png
"""
import shutil
import subprocess

W, H = 1400, 1080
RED = "#d62728"      # +B
BLK = "#1a1a1a"      # coil triggers
ORG = "#e67e22"      # ECU IGT outputs
BLU = "#2471a3"      # IGF / TAC
HT = "#999999"       # HT leads
INK = "#1a1a1a"
GREY = "#6e6e6e"

s = []
A = s.append
A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
A('<rect x="0" y="0" width="1400" height="1080" fill="#ffffff"/>')

def txt(x, y, t, size=14, color=INK, anchor="middle", bold=False, italic=False):
    w = " font-weight='bold'" if bold else ""
    st = " font-style='italic'" if italic else ""
    A(f"<text x='{x}' y='{y}' text-anchor='{anchor}' font-family='sans-serif' font-size='{size}' fill='{color}'{w}{st}>{t}</text>")

def line(x1, y1, x2, y2, color, w=2.5):
    A(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' stroke-width='{w}'/>")

def poly(pts, color, w=2.5):
    A(f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='{w}'/>")

def box(x, y, w, h, title, subs=(), tsize=18, dashed=False):
    dash = " stroke-dasharray='10 6'" if dashed else ""
    A(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='#ffffff' stroke='#333333' stroke-width='2.5'{dash}/>")
    txt(x + w / 2, y + 36, title, size=tsize, bold=True)
    yy = y + 58
    for sub, sz, col in subs:
        txt(x + w / 2, yy, sub, size=sz, color=col)
        yy += 22

# ---- title ----
txt(700, 44, "2JZ-GTE VVTi — wasted-spark ignition (engine-bay layout)", size=26, bold=True)
txt(700, 72, "JZS161 Aristo V300 · physical layout · verified 2026-10-06 · also applies to JZA80 Supra",
    size=14, color=GREY)

# ---- BF2 plug (bottom-left; feed runs up the left side to the rail) ----
box(60, 710, 240, 110, "Body loom plug BF2",
    [("front, passenger side of bay", 12.5, GREY), ("pin 6: power to coils + igniter", 14, RED)], tsize=16)
line(180, 710, 180, 688, RED, 4)

# ---- +B rail ----
line(40, 120, 1000, 120, RED, 4)
txt(300, 108, "Switched +12V (ignition RUN/CRANK)", size=14, color=RED, anchor="start")
A("<circle cx='650' cy='120' r='6' fill='#d62728'/>")
txt(664, 143, "factory splice", size=13, color=RED, anchor="start")
line(40, 120, 40, 688, RED, 4)
line(40, 688, 478, 688, RED, 4)
for cx in (225, 525, 825):
    line(cx, 120, cx, 170, RED, 4)

# ---- valve cover + block ----
A("<rect x='150' y='240' width='900' height='80' fill='#f5f5f5' stroke='#1a1a1a' stroke-width='2'/>")
txt(162, 266, "valve cover", size=13, color=GREY, anchor="start")
A("<rect x='150' y='320' width='900' height='170' fill='#ffffff' stroke='#1a1a1a' stroke-width='2'/>")
for dx in (300, 450, 600, 750, 900):
    line(dx, 320, dx, 490, "#bbbbbb", 1.5)
for i, cx in enumerate((225, 375, 525, 675, 825, 975)):
    txt(cx, 418, str(i + 1), size=32, color="#999999", bold=True)
txt(150, 514, "FRONT (timing belt)", size=13, color=GREY, anchor="start")
txt(1050, 514, "REAR", size=13, color=GREY, anchor="end")

# ---- coil packs (physical order 1, 3, 2 front to back) ----
# trigger take-off at the pack's right edge so the wire drops through the
# gap between cylinders instead of through the cylinder numbers
packs = [(225, "1", "1 + 6", "10", 300), (525, "3", "3 + 4", "2", 600), (825, "2", "2 + 5", "1", 900)]
for cx, num, pair, pin, tx in packs:
    A(f"<rect x='{cx - 85}' y='170' width='170' height='95' rx='8' fill='#ffffff' stroke='#1a1a1a' stroke-width='2'/>")
    txt(cx, 196, f"PACK {num}", size=16, bold=True)
    txt(cx, 216, f"fires {pair}", size=13, color=GREY)
    txt(cx, 236, "+B: blk/wht", size=12.5, color=RED)
    txt(cx, 254, f"trig -ve (pin {pin})", size=12.5)
    A(f"<circle cx='{cx}' cy='170' r='4.5' fill='{RED}'/>")
    A(f"<circle cx='{tx}' cy='265' r='4.5' fill='{BLK}'/>")

# ---- HT leads ----
line(225, 265, 225, 320, HT, 2)
poly("310,280 975,280 975,320", HT, 2)
line(525, 265, 525, 320, HT, 2)
poly("610,280 675,280 675,320", HT, 2)
line(825, 265, 825, 320, HT, 2)
poly("740,292 375,292 375,320", HT, 2)

# ---- trigger wires (igniter -> packs), dropped through inter-cylinder gaps ----
poly("300,265 300,545 660,545 660,620", BLK, 3)
poly("600,265 600,565 740,565 740,620", BLK, 3)
poly("900,265 900,585 820,585 820,620", BLK, 3)

# ---- igniter: drawn like the real DH61 (black box, sticker, embossed pin names) ----
# owner's photo: strut-tower mounted; embossed top->bottom: C1,+B,TAC,T1,T2,T3,IGF,GND,C3,C2
A("<rect x='520' y='620' width='420' height='260' rx='12' fill='#1a1a1a'/>")
# connector block on the left edge, 10 pins
A("<rect x='478' y='648' width='52' height='204' rx='6' fill='#2e2e2e' stroke='#000000' stroke-width='2'/>")
for i in range(10):
    A(f"<circle cx='504' cy='{664 + i*19}' r='4' fill='#777777'/>")
# embossed pin names, as on the unit (kept clear of the +B wire entry)
for i, nm in enumerate(["C1", "+B", "TAC", "T1", "T2", "T3", "IGF", "GND", "C3", "C2"]):
    txt(585, 669 + i * 19, nm, size=14, color="#e8e8e8", anchor="start")
# DH61 sticker (red/white, like the unit label)
A("<rect x='690' y='688' width='210' height='104' rx='4' fill='#ffffff'/>")
A("<rect x='690' y='688' width='210' height='42' rx='4' fill='#d62728'/>")
A("<rect x='690' y='706' width='210' height='24' fill='#d62728'/>")
txt(795, 716, "DH61 IGNITER", size=20, color="#ffffff", bold=True)
txt(795, 752, "TOYOTA", size=17, color="#d62728", bold=True)
txt(795, 772, "89621-30020", size=13, color="#333333")
txt(795, 788, "12V   JAPAN", size=11, color="#777777")
# top-edge trigger entries, tagged with embossed names (inside the box, clear of the wires)
txt(660, 644, "C1", size=12, color="#ffffff")
txt(740, 644, "C3", size=12, color="#ffffff")
txt(820, 644, "C2", size=12, color="#ffffff")
# igniter ground
line(850, 880, 850, 928, BLK, 3)
for gw, gy in ((46, 928), (30, 937), (14, 946)):
    line(850 - gw / 2, gy, 850 + gw / 2, gy, BLK, 3)
txt(850, 968, "GND -&gt; body ground", size=13, anchor="middle")
txt(520, 905, "mounted on strut tower (your photo)", size=13, color=GREY, anchor="start")

# ---- ECU ----
box(990, 620, 250, 260, "ECU", [("plug B1 (JZS161)", 12.5, GREY)], tsize=18)
for y, name, col in [(734, "IGT1", ORG), (762, "IGT2", ORG), (790, "IGT3", ORG),
                     (818, "IGF", BLU), (846, "TAC", BLU)]:
    line(940, y, 990, y, col, 3)
    txt(1000, y + 5, name, size=14, color=col, anchor="start")

# ---- legend ----
A("<rect x='1070' y='150' width='290' height='175' rx='10' fill='#ffffff' stroke='#333333' stroke-width='2'/>")
txt(1215, 180, "Wire colors", size=16, bold=True)
for y, col, label in [(208, RED, "+B (12V switched)"), (234, BLK, "coil trigger (-ve)"),
                      (260, ORG, "ECU IGT1 / 2 / 3"), (286, BLU, "IGF / TAC"), (312, HT, "HT leads")]:
    line(1088, y - 4, 1128, y - 4, col, 4)
    txt(1138, y, label, size=14, anchor="start")

# ---- notes ----
A("<line x1='40' y1='956' x2='1360' y2='956' stroke='#cccccc' stroke-width='1'/>")
notes = [
    "Packs sit on the valve cover in physical order 1 - 3 - 2, front to back (per 2jzgarage / IS300 manual). Each fires its wasted-spark pair.",
    "Factory +B splices at body-loom plug BF2 pin 6 -- the single starvation point for all three packs. T1/T2/T3 = igniter-body labels for ECU IGT1/2/3; coils fire on the falling edge (+5V -&gt; 0V).",
    "2-pin coil connectors carry +B and the switched -ve only -- no chassis-ground wire. Cavity orientation is undocumented: use the black/white wire + key-ON 12V check.",
    "DH61 (Lexus) and DS62 (Toyota) igniters are interchangeable. Pin order as embossed on your unit, top to bottom: C1, +B, TAC, T1, T2, T3, IGF, GND, C3, C2 = pins 10 down to 1.",
]
yy = 982
for n in notes:
    txt(40, yy, "•  " + n, size=15, color="#333333", anchor="start")
    yy += 24

A("</svg>")

outdir = "/home/hatch/workspace/car-logger/vehicles/aristo-v300"
svg_path = f"{outdir}/DH61_igniter_verified.svg"
png_path = f"{outdir}/DH61_igniter_verified.png"
with open(svg_path, "w") as f:
    f.write("\n".join(s))
print("wrote", svg_path)

import cairosvg
cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=1960, output_height=1512)
print("wrote", png_path)
