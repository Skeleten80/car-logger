#!/usr/bin/env python3
"""Generate a verified 2JZ-GTE VVTi wasted-spark coil + igniter wiring diagram.

Findings verified 2026-10-06 against: Haltech 1JZ/2JZ igniter tech doc,
2jzgarage (IS300 workshop manual / Japanese wiring diagrams), Wiring
Specialties JZA80 VVTi pinout, wilbo666 JZS161 Aristo wiring page.
Applies identically to JZS161 Aristo and JZA80 Supra.
Outputs: DH61_igniter_verified.svg and DH61_igniter_verified.png
"""
import shutil
import subprocess

W, H = 1120, 920
RED = "#d62728"      # +B
BLK = "#1a1a1a"      # coil triggers / ground
ORG = "#e67e22"      # ECU IGT outputs
BLU = "#2471a3"      # IGF / TAC
INK = "#1a1a1a"
GREY = "#6e6e6e"

svg = []
A = svg.append
A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
A('<rect x="0" y="0" width="1120" height="920" fill="#ffffff"/>')
A('<defs><marker id="dot" markerWidth="8" markerHeight="8" refX="4" refY="4">'
  '<circle cx="4" cy="4" r="3.2" fill="#d62728"/></marker></defs>')

# ---- title ----
A('<text x="560" y="34" text-anchor="middle" font-family="sans-serif" font-size="22" font-weight="bold" fill="#1a1a1a">'
  '2JZ-GTE VVTi — wasted-spark coil &amp; igniter wiring</text>')
A('<text x="560" y="58" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#6e6e6e">'
  'JZS161 Aristo V300 · verified 2026-10-06 · also applies to JZA80 Supra</text>')

# ---- +B rail ----
rail_y = 92
A(f'<line x1="80" y1="{rail_y}" x2="1050" y2="{rail_y}" stroke="{RED}" stroke-width="3"/>')
A('<text x="80" y="{0}" font-family="sans-serif" font-size="12.5" fill="{1}">'
  'Switched +12V -- EFI relay -&gt; body-loom plug BF2 pin 6 (JZS161)</text>'.format(rail_y - 10, RED))
# splice dot
A(f'<circle cx="300" cy="{rail_y}" r="5" fill="{RED}"/>')
A(f'<text x="312" y="{rail_y + 4}" font-family="sans-serif" font-size="12" fill="{RED}">factory splice</text>')
# drop to igniter pin 9
A(f'<line x1="550" y1="{rail_y}" x2="550" y2="142" stroke="{RED}" stroke-width="3"/>')
# drop to coil +B rail on the right
A(f'<line x1="1050" y1="{rail_y}" x2="1050" y2="512" stroke="{RED}" stroke-width="3"/>')

def box(x, y, w, h, title, sub=None):
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
    A(f'<text x="{x + w/2}" y="{y + 24}" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="bold" fill="{INK}">{title}</text>')
    if sub:
        A(f'<text x="{x + w/2}" y="{y + 42}" text-anchor="middle" font-family="sans-serif" font-size="11.5" fill="{GREY}">{sub}</text>')

def pin_label(x, y, text, anchor="start", color=INK, size=12):
    A(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="sans-serif" font-size="{size}" fill="{color}">{text}</text>')

def wire(x1, y1, x2, y2, color, width=2.5, label=None, lx=None, ly=None):
    A(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')
    if label:
        A(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-family="sans-serif" font-size="11.5" fill="{color}">{label}</text>')

# ---- ECU ----
box(30, 170, 200, 380, "ECU", "plug B1 (JZS161)")
ecu_pins = [("IGT1 -&gt;", 232, ORG), ("IGT2 -&gt;", 282, ORG), ("IGT3 -&gt;", 332, ORG),
            ("IGF &lt;-", 402, BLU), ("TAC &lt;-", 452, BLU)]
for name, y, color in ecu_pins:
    pin_label(200, y + 4, name, anchor="end", color=color)

# ---- igniter ----
box(420, 130, 260, 500, "DH61 / DS62 igniter", "Toyota 89621-30020")
ign_left = [("pin 7 · T1", 232, ORG), ("pin 6 · T2", 282, ORG), ("pin 5 · T3", 332, ORG),
            ("pin 4 · IGF", 402, BLU), ("pin 8 · TAC", 452, BLU)]
for name, y, color in ign_left:
    pin_label(430, y + 4, name, color=color)
ign_right = [("pin 10 · COIL 1+6", 202, BLK), ("pin 1 · COIL 2+5", 322, BLK), ("pin 2 · COIL 3+4", 442, BLK)]
for name, y, color in ign_right:
    pin_label(670, y + 4, name, anchor="end", color=color)
pin_label(560, 126, "pin 9 · +B", anchor="middle", color=RED)
pin_label(560, 646, "pin 3 · GND", anchor="middle", color=BLK)

# ---- coil packs ----
coils = [("Coil pack -- cyl 1+6", 140, 202, 232),
         ("Coil pack -- cyl 2+5", 280, 342, 372),
         ("Coil pack -- cyl 3+4", 420, 482, 512)]
for title, y, ty, py in coils:
    box(850, y, 200, 120, title, "90919-02216 - 2-pin")
    pin_label(860, ty + 4, "trigger (-ve)", color=BLK)
    pin_label(1040, py + 4, "+B - blk/wht", anchor="end", color=RED)

# ---- wires: ECU <-> igniter ----
wire(230, 232, 420, 232, ORG); wire(230, 282, 420, 282, ORG); wire(230, 332, 420, 332, ORG)
A('<text x="325" y="222" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#e67e22">IGT1</text>')
A('<text x="325" y="272" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#e67e22">IGT2</text>')
A('<text x="325" y="322" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#e67e22">IGT3</text>')
wire(230, 402, 420, 402, BLU)
wire(230, 452, 420, 452, BLU)
A('<text x="325" y="392" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#2471a3">IGF</text>')
A('<text x="325" y="442" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#2471a3">TAC</text>')

# ---- wires: igniter -> coil triggers ----
wire(680, 202, 850, 202, BLK)
wire(680, 322, 850, 342, BLK)
wire(680, 442, 850, 482, BLK)

# ---- ground ----
A('<line x1="550" y1="630" x2="550" y2="686" stroke="#1a1a1a" stroke-width="2.5"/>')
for i, (gw, gy) in enumerate([(44, 686), (28, 694), (12, 702)]):
    A(f'<line x1="{550 - gw/2}" y1="{gy}" x2="{550 + gw/2}" y2="{gy}" stroke="#1a1a1a" stroke-width="2.5"/>')
A('<text x="550" y="722" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#1a1a1a">GND -&gt; cylinder head</text>')

# ---- notes ----
notes = [
    "T1/T2/T3 are the igniter-body labels for the ECU's IGT1/IGT2/IGT3. Coils fire on the falling edge (+5V -&gt; 0V), constant charge.",
    "The 2-pin coil connectors carry +B and the switched -ve only -- there is no chassis-ground wire on the coil.",
    "Factory +B is a common splice at the body-loom plug (BF2 pin 6), not a daisy-chain out of the igniter -- the splice is the single starvation point for all three packs.",
    "Coil connector cavity orientation (+B vs trigger) is undocumented: identify +B by the black/white wire and a key-ON 12V check.",
    "DH61 (Lexus) and DS62 (Toyota) igniters are interchangeable. Sources: Haltech 1JZ/2JZ tech doc, 2jzgarage, Wiring Specialties, wilbo666 JZS161 page.",
]
ny = 762
A(f'<line x1="30" y1="{ny - 18}" x2="1090" y2="{ny - 18}" stroke="#cccccc" stroke-width="1"/>')
for n in notes:
    A(f'<text x="40" y="{ny}" font-family="sans-serif" font-size="12.5" fill="#333333">• {n}</text>')
    ny += 26

A('</svg>')

outdir = "/home/hatch/workspace/car-logger/vehicles/aristo-v300"
svg_path = f"{outdir}/DH61_igniter_verified.svg"
png_path = f"{outdir}/DH61_igniter_verified.png"
with open(svg_path, "w") as f:
    f.write("\n".join(svg))
print("wrote", svg_path)

# convert to PNG if a converter exists
for tool, args in [("rsvg-convert", ["rsvg-convert", "-w", "1680", "-h", "1380", "-o", png_path, svg_path]),
                   ("inkscape", ["inkscape", svg_path, "--export-type=png", f"--export-filename={png_path}", "-w", "1680"]),
                   ("convert", ["convert", "-density", "150", "-background", "white", svg_path, png_path])]:
    if shutil.which(tool):
        subprocess.run(args, check=True)
        print("converted with", tool, "->", png_path)
        break
else:
    print("NO_SVG_CONVERTER")
