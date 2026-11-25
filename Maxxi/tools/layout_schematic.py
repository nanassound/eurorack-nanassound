#!/usr/bin/env python3
"""Re-layout Maxxi.kicad_sch into clean, grouped functional blocks.

Electrical content is preserved bit-for-bit: lib_symbols are copied verbatim from
the existing file and every component keeps its exact property set (value,
footprint, MPN, LCSC, description, DNP/BOM flags). Only geometry changes:
symbols are re-placed on the 1.27 mm grid, wired with real point-to-point
wires inside labeled group boxes, and inter-group connections use global
labels on the rails.

The script self-verifies before writing:
  * every wire endpoint / pin / label / junction sits on the 1.27 mm grid
  * resolved connectivity (union-find over wires, pins, junctions, labels,
    power symbols) reproduces the intended net map exactly
  * no dangling wires, no overlapping collinear segments, every junction
    joins >= 2 wires

Run:  python3 tools/layout_schematic.py [--dry]
"""
import re
import sys
import uuid
import pathlib
import math
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCH = ROOT / 'Maxxi.kicad_sch'
GRID = 1.27
ROOT_UUID = '88b3c921-84f7-4c3a-9d38-5128446295d1'

# --------------------------------------------------------------------------
# Intended net map (verified against kicad-cli netlist export of the old file)
# --------------------------------------------------------------------------
def _buck(b, refU, refL, refD, rb, cb, gndnet, outnet, fbtnet, cinnet):
    R, C = rb, cb
    return {
        (refU, '1'): 'BOOT' + b, (refU, '2'): '+VBUS', (refU, '3'): 'EN' + b,
        (refU, '4'): 'RT' + b, (refU, '5'): 'FB' + b, (refU, '6'): 'COMP' + b,
        (refU, '7'): gndnet, (refU, '8'): 'SW' + b, (refU, '9'): gndnet,
        ('R%d' % (R + 0), '1'): '+VBUS', ('R%d' % (R + 0), '2'): 'EN' + b,
        ('R%d' % (R + 1), '1'): 'EN' + b, ('R%d' % (R + 1), '2'): gndnet,
        ('R%d' % (R + 2), '1'): 'RT' + b, ('R%d' % (R + 2), '2'): gndnet,
        ('R%d' % (R + 3), '1'): 'COMP' + b, ('R%d' % (R + 3), '2'): 'COMP' + b + 'S',
        ('C%d' % (C + 0), '1'): 'COMP' + b + 'S', ('C%d' % (C + 0), '2'): gndnet,
        ('C%d' % (C + 1), '1'): 'COMP' + b, ('C%d' % (C + 1), '2'): gndnet,
        ('R%d' % (R + 4), '1'): fbtnet, ('R%d' % (R + 4), '2'): 'FB' + b,
        ('R%d' % (R + 5), '1'): 'FB' + b, ('R%d' % (R + 5), '2'): gndnet,
        ('C%d' % (C + 2), '1'): 'BOOT' + b, ('C%d' % (C + 2), '2'): 'SW' + b,
        (refL, '1'): 'SW' + b, (refL, '2'): outnet,
        (refD, '1'): 'SW' + b, (refD, '2'): gndnet,
        ('C%d' % (C + 3), '1'): '+VBUS', ('C%d' % (C + 3), '2'): cinnet,
    }

EURO = {'5': '+5V', '6': '+5V', '7': '+12V', '8': '+12V', '9': 'GND', '10': 'GND',
        '11': 'GND', '12': 'GND', '13': 'GND', '14': 'GND', '15': '-12V', '16': '-12V'}

NETMAP = {
    ('J1', 'A1B12'): 'GND', ('J1', 'B1A12'): 'GND',
    ('J1', 'A4B9'): 'VBUS_RAW', ('J1', 'B4A9'): 'VBUS_RAW',
    ('J1', 'A5'): 'CC1', ('J1', 'B5'): 'CC2',
    ('J1', '1'): 'GND', ('J1', '2'): 'GND', ('J1', '3'): 'GND', ('J1', '4'): 'GND',
    ('F1', '1'): 'VBUS_RAW', ('F1', '2'): '+VBUS',
    ('D1', '1'): '+VBUS', ('D1', '2'): 'GND',
    ('C1', '1'): '+VBUS', ('C1', '2'): 'GND',
    ('C2', '1'): '+VBUS', ('C2', '2'): 'GND',
    ('U1', '1'): 'VDD', ('U1', '4'): 'DPIO', ('U1', '5'): 'DPIO',
    ('U1', '6'): 'CC2', ('U1', '7'): 'CC1', ('U1', '8'): '+VBUS',
    ('U1', '9'): 'CFG1', ('U1', '10'): 'PG', ('U1', '11'): 'GND',
    ('R1', '1'): 'CFG1', ('R1', '2'): 'GND',
    ('R2', '1'): '+VBUS', ('R2', '2'): 'VDD',
    ('C3', '1'): 'VDD', ('C3', '2'): 'GND',
    ('R3', '1'): 'DPIO', ('R3', '2'): 'GND',
    ('R4', '1'): '+VBUS', ('R4', '2'): 'PG',
    ('U5', '1'): '+12V6', ('U5', '2'): '+12V6', ('U5', '3'): 'GND',
    ('U5', '4'): '+12V', ('U5', '5'): 'ADJ1',
    ('R50', '1'): '+12V', ('R50', '2'): 'ADJ1',
    ('R51', '1'): 'ADJ1', ('R51', '2'): 'GND',
    ('C50', '1'): '+12V6', ('C50', '2'): 'GND',
    ('C51', '1'): '+12V', ('C51', '2'): 'GND',
    ('C52', '1'): '+12V', ('C52', '2'): 'GND',
    ('U6', '1'): '-12V6', ('U6', '2'): '-12V6', ('U6', '3'): '-12V6',
    ('U6', '4'): 'GND', ('U6', '5'): 'GND', ('U6', '6'): 'ADJ2',
    ('U6', '7'): '-12V', ('U6', '8'): '-12V', ('U6', '9'): '-12V6',
    ('R52', '1'): '-12V', ('R52', '2'): 'ADJ2',
    ('R53', '1'): 'ADJ2', ('R53', '2'): 'GND',
    ('C53', '1'): '-12V6', ('C53', '2'): 'GND',
    ('C54', '1'): '-12V', ('C54', '2'): 'GND',
    ('C55', '1'): '-12V', ('C55', '2'): 'GND',
    ('D5', '1'): 'GND', ('D5', '2'): 'LD12',
    ('R60', '1'): 'LD12', ('R60', '2'): '+12V',
    ('D6', '1'): 'LN12', ('D6', '2'): 'GND',
    ('R61', '1'): 'LN12', ('R61', '2'): '-12V',
    ('D7', '1'): 'GND', ('D7', '2'): 'L5',
    ('R62', '1'): 'L5', ('R62', '2'): '+5V',
    ('J4', '1'): '+5V', ('J4', '2'): 'GND',
    ('C56', '1'): '+5V', ('C56', '2'): 'GND',
    ('C57', '1'): '+5V', ('C57', '2'): 'GND',
}
NETMAP.update(_buck('1', 'U2', 'L1', 'D2', 30, 30, 'GND', '+12V6', '+12V6', 'GND'))
NETMAP.update(_buck('2', 'U3', 'L2', 'D3', 36, 34, '-12V6', '-12V6', 'GND', '-12V6'))
NETMAP.update(_buck('3', 'U4', 'L3', 'D4', 42, 38, 'GND', '+5V', '+5V', 'GND'))
for _j in ('J2', 'J3'):
    for _p, _n in EURO.items():
        NETMAP[(_j, _p)] = _n

NC_PINS = {('J1', p) for p in ('A6', 'B6', 'A7', 'B7', 'A8', 'B8')} \
    | {('U1', '2'), ('U1', '3')} \
    | {(j, p) for j in ('J2', 'J3') for p in ('1', '2', '3', '4')}

# --------------------------------------------------------------------------
# Parse existing file
# --------------------------------------------------------------------------
src = SCH.read_text()

def balanced(s, i):
    d = 0
    for j in range(i, len(s)):
        if s[j] == '(':
            d += 1
        elif s[j] == ')':
            d -= 1
            if d == 0:
                return j + 1
    raise ValueError('unbalanced')

ls_i = src.index('(lib_symbols')
ls_j = balanced(src, ls_i)
libsec = src[ls_i:ls_j]

LIBDEF = {}
i = 0
while True:
    m = re.search(r'\(symbol "([^"]+)"', libsec[i:])
    if not m:
        break
    name = m.group(1)
    s = i + m.start()
    e = balanced(libsec, s)
    i = e
    if name.endswith('_0_1') or name.endswith('_1_1') or name.endswith('_2_1'):
        continue
    LIBDEF[name] = libsec[s:e]

PIN_RE = re.compile(
    r'\(pin (\w+) (\w+)\s*\(at ([-\d.]+) ([-\d.]+) ([\d.]+)\)\s*\(length ([\d.]+)\)'
    r'[\s\S]{0,400}?\(number "([^"]*)"')

def pins_of(block):
    out = {}
    for etype, gtype, x, y, ang, ln, num in PIN_RE.findall(block):
        out[num] = dict(x=float(x), y=float(y), ang=float(ang), ln=float(ln))
    return out

LIBPINS = {lid: pins_of(d) for lid, d in LIBDEF.items()}
LIBPINS['Regulator_Linear:LT1963AEQ'] = LIBPINS['Regulator_Linear:LT1963EQ']

def bbox_of(block):
    xs, ys = [], []
    for m in re.finditer(r'\(rectangle\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)', block):
        x1, y1, x2, y2 = map(float, m.groups())
        xs += [x1, x2]
        ys += [y1, y2]
    for m in re.finditer(r'\(xy ([-\d.]+) ([-\d.]+)\)', block):
        x, y = map(float, m.groups())
        xs.append(x)
        ys.append(y)
    if not xs:
        return (-2.54, -2.54, 2.54, 2.54)
    return (min(xs), min(ys), max(xs), max(ys))

LIBBBOX = {lid: bbox_of(d) for lid, d in LIBDEF.items()}
LIBBBOX['Regulator_Linear:LT1963AEQ'] = LIBBBOX['Regulator_Linear:LT1963EQ']

INST = {}
body = src[ls_j:]
i = 0
while True:
    m = re.search(r'\t\(symbol\n\t\t\(lib_id "([^"]+)"\)\n', body[i:])
    if not m:
        break
    s = i + m.start()
    e = balanced(body, s)
    block = body[s:e]
    i = e
    ref = re.search(r'\(property "Reference" "([^"]+)"', block).group(1)
    props = [(pm.group(1), pm.group(2))
             for pm in re.finditer(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', block)]
    INST[ref] = dict(
        lib=m.group(1), props=props,
        dnp='yes' if re.search(r'\(dnp yes\)', block) else 'no',
        in_bom='yes' if re.search(r'\(in_bom yes\)', block) else 'no',
        pins=sorted({p for (r, p) in NETMAP if r == ref} |
                    {p for (r, p) in NC_PINS if r == ref},
                    key=lambda s: (len(s), s)))

# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------
import math as _m

def tf(px, py, rot, my):
    # KiCad symbol pin transform (empirically verified against kicad-cli 10.0.1)
    a = _m.radians(rot)
    dx = px * _m.cos(a) - py * _m.sin(a)
    dy = -(px * _m.sin(a) + py * _m.cos(a))
    if my:
        dx = -dx
    return dx, dy

PLACE = {}

def P(ref, x, y, rot=0, my=False, rt=None, vt=None):
    PLACE[ref] = dict(x=x, y=y, rot=rot, my=my, rt=rt, vt=vt)

def pinpos(ref, num):
    pl = PLACE[ref]
    p = LIBPINS[INST[ref]['lib']][num]
    dx, dy = tf(p['x'], p['y'], pl['rot'], pl['my'])
    return round(pl['x'] + dx, 3), round(pl['y'] + dy, 3)

WIRES, JUNCS, LBL, NCS, GNDS, FLAGS = [], [], [], [], [], []

def W(x1, y1, x2, y2):
    WIRES.append((round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)))

def J(x, y):
    JUNCS.append((round(x, 3), round(y, 3)))

def L(name, x, y, ang):
    LBL.append((name, round(x, 3), round(y, 3), ang))

def NC(x, y):
    NCS.append((round(x, 3), round(y, 3)))

def G(x, y):
    GNDS.append((round(x, 3), round(y, 3)))

def FLAG(net, x, y):
    FLAGS.append((net, round(x, 3), round(y, 3)))

def gnd_at(x, y, gndnet, ang=270):
    if gndnet == 'GND':
        G(x, y)
    else:
        L(gndnet, x, y, ang)

# --------------------------------------------------------------------------
# Placements  (rt/vt = Reference/Value text offset (dx,dy) + justify)
# --------------------------------------------------------------------------
# USB-C input & protection
P('J1', 50.8, 57.15, my=True, rt=(0, -12.7, 'c'), vt=(0, -16.51, 'c'))
P('F1', 86.36, 57.15, 90, rt=(-2.54, -2.54, 'r'), vt=(0, 3.81, 'c'))
P('D1', 97.79, 60.96, 270, rt=(-2.54, -2.54, 'r'), vt=(0, 3.81, 'l'))
P('C1', 110.49, 60.96, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('C2', 123.19, 60.96, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
# PD sink controller
P('U1', 55.88, 154.94, rt=(0, -10.16, 'c'), vt=(0, 15.24, 'c'))
P('R2', 31.75, 143.51, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('C3', 39.37, 154.94, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
P('R1', 36.83, 156.21, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('R4', 33.02, 168.91, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('R3', 73.66, 168.91, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
# bucks
def buck_place(cx, cy, refU, refL, refD, rb, cb):
    P(refU, cx, cy, rt=(-10.16, -13.335, 'r'), vt=(-12.7, 15.875, 'l'))
    P('C%d' % (cb + 3), cx - 35.56, cy - 13.97, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P('R%d' % (rb + 0), cx - 30.48, cy - 1.27, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P('R%d' % (rb + 1), cx - 30.48, cy + 13.97, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P('R%d' % (rb + 2), cx - 25.4, cy - 1.27, rt=(0, -5.08, 'c'), vt=(0, 3.81, 'c'))
    P('C%d' % (cb + 2), cx + 26.67, cy - 1.27, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P(refD, cx + 26.67, cy + 12.7, 270, rt=(-2.54, 0, 'r'), vt=(2.54, 0, 'l'))
    P(refL, cx + 33.02, cy, 90, rt=(0, -6.35, 'c'), vt=(0, 6.35, 'c'))
    P('R%d' % (rb + 4), cx + 45.72, cy + 10.16, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P('R%d' % (rb + 5), cx + 45.72, cy + 25.4, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
    P('R%d' % (rb + 3), cx + 16.51, cy + 6.35, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
    P('C%d' % (cb + 0), cx + 19.05, cy + 12.7, 90, rt=(1.27, -2.54, 'l'), vt=(0, 2.54, 'c'))
    P('C%d' % (cb + 1), cx + 7.62, cy + 6.35, rt=(2.54, -1.27, 'l'), vt=(3.81, 1.27, 'l'))

buck_place(215.9, 50.8, 'U2', 'L1', 'D2', 30, 30)
buck_place(215.9, 114.3, 'U3', 'L2', 'D3', 36, 34)
buck_place(215.9, 177.8, 'U4', 'L3', 'D4', 42, 38)
# LDO +12
P('U5', 330.2, 60.96, rt=(-10.16, -6.35, 'r'), vt=(-12.7, 12.7, 'l'))
P('C50', 309.88, 62.23, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('R50', 346.71, 67.31, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
P('R51', 346.71, 78.74, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
P('C51', 355.6, 62.23, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('C52', 364.49, 62.23, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
# LDO -12
P('U6', 330.2, 140.97, rt=(0, -10.16, 'c'), vt=(0, 17.78, 'c'))
P('C53', 306.07, 139.7, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('R52', 351.79, 148.59, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('R53', 351.79, 163.83, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('C54', 355.6, 147.32, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
P('C55', 367.03, 147.32, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))
# indicators
P('D5', 307.34, 196.85, 90, rt=(-2.54, 0, 'r'), vt=(2.54, 2.54, 'l'))
P('R60', 311.15, 190.5, 90, rt=(0, -2.54, 'c'), vt=(0, 2.54, 'l'))
P('D6', 307.34, 214.63, 270, rt=(-2.54, 0, 'r'), vt=(2.54, 2.54, 'l'))
P('R61', 311.15, 210.82, 90, rt=(0, -2.54, 'c'), vt=(0, 2.54, 'l'))
P('D7', 307.34, 232.41, 90, rt=(-2.54, 0, 'r'), vt=(2.54, 2.54, 'l'))
P('R62', 311.15, 228.6, 90, rt=(0, -2.54, 'c'), vt=(0, 2.54, 'l'))
# outputs
P('J2', 368.3, 88.9, rt=(0, -12.7, 'c'), vt=(0, 19.05, 'l'))
P('J3', 368.3, 132.08, rt=(0, -12.7, 'c'), vt=(0, 19.05, 'l'))
P('J4', 377.19, 190.5, rt=(0, -8.89, 'c'), vt=(0, 8.89, 'l'))
P('C56', 359.41, 198.12, rt=(-2.54, -1.27, 'r'), vt=(-2.54, 1.27, 'r'))
P('C57', 363.22, 198.12, rt=(2.54, -1.27, 'l'), vt=(2.54, 1.27, 'l'))

# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------
# --- USB-C input ---
for p in ('A6', 'B6', 'A7', 'B7', 'A8', 'B8'):
    NC(*pinpos('J1', p))
for yy in (46.99, 52.07):                     # GND pins
    W(63.5, yy, 66.04, yy)
    G(66.04, yy)
W(63.5, 57.15, 82.55, 57.15)                  # VBUS_RAW -> fuse
W(63.5, 62.23, 73.66, 62.23)
W(73.66, 62.23, 73.66, 57.15)
J(73.66, 57.15)
L('VBUS_RAW', 66.04, 62.23, 0)
W(90.17, 57.15, 132.08, 57.15)                # +VBUS rail
L('+VBUS', 132.08, 57.15, 0)
for xx in (97.79, 110.49, 123.19):
    J(xx, 57.15)
    W(xx, 64.77, xx, 67.31)
    G(xx, 67.31)
W(63.5, 67.31, 68.58, 67.31)                  # CC lines
L('CC1', 68.58, 67.31, 0)
W(63.5, 72.39, 68.58, 72.39)
L('CC2', 68.58, 72.39, 0)
W(38.1, 77.47, 63.5, 77.47)                   # shields
for xx in (48.26, 50.8, 53.34):
    J(xx, 77.47)
W(50.8, 77.47, 50.8, 81.28)
G(50.8, 81.28)

# --- PD controller ---
NC(*pinpos('U1', '2'))
NC(*pinpos('U1', '3'))
L('+VBUS', 31.75, 139.7, 90)                  # R2 top
W(31.75, 147.32, 31.75, 149.86)
W(31.75, 149.86, 44.45, 149.86)               # VDD line to U1.1
L('VDD', 33.02, 149.86, 0)
W(39.37, 151.13, 39.37, 149.86)
J(39.37, 149.86)                              # C3 decoupling
W(39.37, 158.75, 39.37, 161.29)
G(39.37, 161.29)
W(44.45, 152.4, 36.83, 152.4)                 # CFG1 strap (R1 DNP)
L('CFG1', 40.64, 152.4, 0)
W(36.83, 160.02, 36.83, 163.83)
G(36.83, 163.83)
L('+VBUS', 33.02, 165.1, 90)                  # R4 top
W(33.02, 172.72, 38.1, 172.72)                # PG route
W(38.1, 172.72, 38.1, 160.02)
W(38.1, 160.02, 44.45, 160.02)
L('PG', 38.1, 166.37, 0)
W(67.31, 149.86, 71.12, 149.86)               # VBUS sense
L('+VBUS', 71.12, 149.86, 0)
W(67.31, 152.4, 71.12, 152.4)
L('CC1', 71.12, 152.4, 0)
W(67.31, 154.94, 71.12, 154.94)
L('CC2', 71.12, 154.94, 0)
W(67.31, 157.48, 73.66, 157.48)               # DP/DM pulldown
W(67.31, 160.02, 73.66, 160.02)
W(73.66, 157.48, 73.66, 165.1)
J(73.66, 160.02)
L('DPIO', 68.58, 157.48, 0)
W(73.66, 172.72, 73.66, 175.26)
G(73.66, 175.26)
W(55.88, 162.56, 55.88, 165.1)                # U1 ground
G(55.88, 165.1)

# --- bucks ---
def buck_route(cx, cy, b, gndnet, outnet, fbtnet):
    def w(x1, y1, x2, y2):
        W(cx + x1, cy + y1, cx + x2, cy + y2)
    def j(x, y):
        J(cx + x, cy + y)
    def lb(name, x, y, ang):
        L(name, cx + x, cy + y, ang)
    def ga(x, y, ang=270, stub=0.0, stubdir=(0, 1)):
        if stub:
            w(x, y, x + stubdir[0] * stub, y + stubdir[1] * stub)
            x += stubdir[0] * stub
            y += stubdir[1] * stub
        gnd_at(cx + x, cy + y, gndnet, ang)
    w(-43.18, -17.78, -10.16, -17.78)          # +VBUS rail
    w(-10.16, -17.78, -10.16, -5.08)
    lb('+VBUS', -43.18, -17.78, 180)
    j(-35.56, -17.78)
    w(-35.56, -10.16, -35.56, -7.62)           # Cin
    ga(-35.56, -7.62, 0) if gndnet != 'GND' else None
    if gndnet == 'GND':
        gnd_at(cx - 35.56, cy - 7.62, 'GND')
    w(-30.48, -5.08, -30.48, -17.78)           # EN divider
    j(-30.48, -17.78)
    w(-30.48, 2.54, -30.48, 10.16)
    w(-30.48, 7.62, -10.16, 7.62)
    j(-30.48, 7.62)
    lb('EN' + b, -21.59, 7.62, 0)
    ga(-30.48, 17.78)
    w(-10.16, 0, -20.32, 0)                    # RT
    w(-20.32, 0, -20.32, -5.08)
    w(-20.32, -5.08, -25.4, -5.08)
    lb('RT' + b, -16.51, 0, 0)
    ga(-25.4, 5.08, 0) if gndnet != 'GND' else None
    if gndnet == 'GND':
        gnd_at(cx - 25.4, cy + 2.54, 'GND')
    else:
        w(-25.4, 2.54, -25.4, 5.08)
    w(-2.54, 12.7, 2.54, 12.7)                 # GND/EP pins
    j(0, 12.7)
    w(2.54, 12.7, 2.54, 15.24)
    j(2.54, 12.7)
    ga(2.54, 15.24)
    w(10.16, -5.08, 26.67, -5.08)              # BOOT
    lb('BOOT' + b, 16.51, -5.08, 0)
    w(10.16, 0, 29.21, 0)                      # SW node
    j(26.67, 0)
    w(26.67, 0, 26.67, 8.89)
    j(26.67, 2.54)
    lb('SW' + b, 13.97, 0, 0)
    ga(26.67, 16.51, 0) if gndnet == 'GND' else ga(26.67, 16.51, 0, 2.54)
    w(36.83, 0, 58.42, 0)                      # output rail
    lb(outnet, 58.42, 0, 0)
    if fbtnet == outnet:                       # FB divider top
        j(45.72, 0)
        w(45.72, 0, 45.72, 6.35)
    else:
        lb('GND', 45.72, 6.35, 90)
    w(45.72, 13.97, 45.72, 21.59)              # FB divider node
    ga(45.72, 29.21)
    w(10.16, 7.62, 10.16, 21.59)               # FB route
    w(10.16, 21.59, 45.72, 21.59)
    j(45.72, 21.59)
    lb('FB' + b, 13.97, 21.59, 0)
    w(7.62, 2.54, 16.51, 2.54)                # COMP network
    j(7.62, 2.54)
    j(10.16, 2.54)
    lb('COMP' + b, 13.97, 2.54, 0)
    w(7.62, 10.16, 7.62, 12.7)
    ga(7.62, 12.7)
    w(16.51, 10.16, 16.51, 12.7)               # Rz bottom to Cz
    w(16.51, 12.7, 15.24, 12.7)
    lb('COMP' + b + 'S', 16.51, 10.16, 180)
    w(22.86, 12.7, 22.86, 13.97)
    ga(22.86, 13.97)

buck_route(215.9, 50.8, '1', 'GND', '+12V6', '+12V6')
buck_route(215.9, 114.3, '2', '-12V6', '-12V6', 'GND')
buck_route(215.9, 177.8, '3', 'GND', '+5V', '+5V')

# --- LDO +12 ---
W(309.88, 58.42, 320.04, 58.42)               # +12V6 input
L('+12V6', 309.88, 58.42, 180)
W(320.04, 60.96, 314.96, 60.96)               # SHDN tie
W(314.96, 60.96, 314.96, 58.42)
J(314.96, 58.42)
W(309.88, 66.04, 309.88, 68.58)               # C50 ground
G(309.88, 68.58)
W(330.2, 68.58, 330.2, 71.12)                 # U5 ground
G(330.2, 71.12)
W(340.36, 58.42, 368.3, 58.42)                # +12V rail
L('+12V', 368.3, 58.42, 0)
for xx in (346.71, 355.6, 364.49):
    J(xx, 58.42)
W(355.6, 66.04, 355.6, 68.58)
G(355.6, 68.58)
W(364.49, 66.04, 364.49, 68.58)
G(364.49, 68.58)
W(346.71, 58.42, 346.71, 63.5)                # ADJ divider
W(346.71, 71.12, 346.71, 74.93)
W(340.36, 60.96, 342.9, 60.96)
W(342.9, 60.96, 342.9, 74.93)
W(342.9, 74.93, 346.71, 74.93)
J(346.71, 74.93)
L('ADJ1', 346.71, 73.66, 0)
G(346.71, 82.55)                              # R51 bottom

# --- LDO -12 ---
W(306.07, 135.89, 318.77, 135.89)             # -12V6 input bus
L('-12V6', 306.07, 135.89, 180)
W(312.42, 135.89, 312.42, 148.59)
J(312.42, 135.89)
W(312.42, 138.43, 318.77, 138.43)
J(312.42, 138.43)
W(312.42, 140.97, 318.77, 140.97)
J(312.42, 140.97)
W(312.42, 148.59, 330.2, 148.59)              # EP
W(306.07, 143.51, 306.07, 146.05)             # C53 ground
G(306.07, 146.05)
W(318.77, 143.51, 314.96, 143.51)             # GND pin 4
G(314.96, 143.51)
W(341.63, 135.89, 344.17, 135.89)             # GND pin 5
G(344.17, 135.89)
W(341.63, 140.97, 341.63, 143.51)             # OUT pin tie
W(341.63, 143.51, 368.3, 143.51)              # -12V rail
L('-12V', 368.3, 143.51, 0)
for xx in (351.79, 355.6, 367.03):
    J(xx, 143.51)
G(355.6, 151.13)                              # C54/C55 grounds
G(367.03, 151.13)
W(351.79, 143.51, 351.79, 144.78)             # R52 top
W(351.79, 152.4, 351.79, 160.02)              # ADJ2 node
W(341.63, 138.43, 344.17, 138.43)             # ADJ route (crosses OUT rail)
W(344.17, 138.43, 344.17, 154.94)
W(344.17, 154.94, 351.79, 154.94)
J(351.79, 154.94)
L('ADJ2', 351.79, 157.48, 0)
G(351.79, 167.64)                             # R53 bottom

# --- indicators ---
W(307.34, 190.5, 307.34, 193.04)              # R60 -> D5
L('LD12', 307.34, 193.04, 90)
L('+12V', 314.96, 190.5, 0)
W(307.34, 200.66, 307.34, 203.2)
G(307.34, 203.2)
L('LN12', 307.34, 210.82, 90)
L('-12V', 314.96, 210.82, 0)                  # R61 <-> D6 pin-to-pin
W(307.34, 218.44, 307.34, 220.98)
G(307.34, 220.98)
L('L5', 307.34, 228.6, 90)
L('+5V', 314.96, 228.6, 0)                    # R62 <-> D7 pin-to-pin
W(307.34, 236.22, 307.34, 238.76)
G(307.34, 238.76)

# --- Eurorack headers ---
def euro(cy):
    x_L, x_R = 361.95, 374.65
    NC(x_L, cy - 8.89)
    NC(x_L, cy - 6.35)
    NC(x_R, cy - 8.89)
    NC(x_R, cy - 6.35)
    for yoff, name in ((-3.81, '+5V'), (-1.27, '+12V'), (8.89, '-12V')):
        W(x_L, cy + yoff, 356.87, cy + yoff)
        L(name, 356.87, cy + yoff, 180)
        W(x_R, cy + yoff, 379.73, cy + yoff)
        L(name, 379.73, cy + yoff, 0)
    for px, bx in ((x_L, 359.41), (x_R, 377.19)):
        for yoff in (1.27, 3.81, 6.35):
            W(px, cy + yoff, bx, cy + yoff)
        W(bx, cy + 1.27, bx, cy + 6.35)
        J(bx, cy + 3.81)
        G(bx, cy + 6.35)

euro(88.9)
euro(132.08)

# --- 5V terminal + caps ---
W(377.19, 190.5, 373.38, 190.5)
W(373.38, 190.5, 373.38, 187.96)
L('+5V', 373.38, 187.96, 90)
W(377.19, 193.04, 373.38, 193.04)
W(373.38, 193.04, 373.38, 195.58)
G(373.38, 195.58)
for xx in (359.41, 363.22):
    L('+5V', xx, 194.31, 90)
    G(xx, 201.93)

# --- PWR_FLAG row ---
for k, net in enumerate(('GND', '+VBUS', '+12V6', '-12V6', 'VDD', '+5V')):
    FLAG(net, 30.48 + k * 17.78, 222.25)

# --------------------------------------------------------------------------
# Group boxes
# --------------------------------------------------------------------------
GROUPS = [
    ('USB-C PD INPUT 20 V', ['J1', 'F1', 'D1', 'C1', 'C2'], 6.35),
    ('USB PD SINK CONTROLLER', ['U1', 'R1', 'R2', 'R3', 'R4', 'C3'], 10.16),
    ('+12.6 V BUCK PREREGULATOR (TPS54360)', ['U2'] + ['R%d' % n for n in range(30, 36)] + ['C%d' % n for n in range(30, 34)] + ['L1', 'D2'], 6.35),
    ('-12.6 V INVERTING BUCK-BOOST (TPS54360)', ['U3'] + ['R%d' % n for n in range(36, 42)] + ['C%d' % n for n in range(34, 38)] + ['L2', 'D3'], 6.35),
    ('+5.07 V BUCK (TPS54360)', ['U4'] + ['R%d' % n for n in range(42, 48)] + ['C%d' % n for n in range(38, 42)] + ['L3', 'D4'], 6.35),
    ('+12 V LDO POST-REG (LT1963A)', ['U5', 'C50', 'R50', 'R51', 'C51', 'C52'], 10.16),
    ('-12 V LDO POST-REG (LT3015)', ['U6', 'C53', 'R52', 'R53', 'C54', 'C55'], 10.16),
    ('RAIL INDICATORS', ['D5', 'R60', 'D6', 'R61', 'D7', 'R62'], 6.35),
    ('EURORACK POWER HEADERS', ['J2', 'J3'], 6.35),
    ('5 V AUX TERMINAL', ['J4', 'C56', 'C57'], 12.7),
]
BLUE = '(color 39 110 214 1)'
PAD = 6.35

def group_box(members, padl=PAD):
    xs, ys = [], []
    for ref in members:
        pl = PLACE[ref]
        bx1, by1, bx2, by2 = LIBBBOX[INST[ref]['lib']]
        for px, py in ((bx1, by1), (bx2, by2)):
            dx, dy = tf(px, py, pl['rot'], pl['my'])
            xs.append(pl['x'] + dx)
            ys.append(pl['y'] + dy)
        for num in LIBPINS[INST[ref]['lib']]:
            px, py = pinpos(ref, num)
            xs.append(px)
            ys.append(py)
    def fl(v):
        return math.floor(v / GRID) * GRID
    def ce(v):
        return math.ceil(v / GRID) * GRID
    return (fl(min(xs) - padl), fl(min(ys) - PAD - 3.81),
            ce(max(xs) + PAD + 2.54), ce(max(ys) + PAD))

# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------
def verify():
    errs = []
    def on_grid(v, what):
        if abs(round(v / GRID) * GRID - v) > 1e-6:
            errs.append('off grid %s: %s' % (what, v))
    for ref, pl in PLACE.items():
        on_grid(pl['x'], ref + '.x')
        on_grid(pl['y'], ref + '.y')
    for x1, y1, x2, y2 in WIRES:
        for v in (x1, y1, x2, y2):
            on_grid(v, 'wire')
    for pts in JUNCS + NCS + GNDS + [(x, y) for _, x, y, _ in LBL] + \
            [(x, y) for _, x, y in FLAGS]:
        on_grid(pts[0], 'pt')
        on_grid(pts[1], 'pt')
    for x1, y1, x2, y2 in WIRES:
        if x1 != x2 and y1 != y2:
            errs.append('diagonal wire %s' % ((x1, y1, x2, y2),))
        if x1 == x2 and y1 == y2:
            errs.append('zero-length wire %s' % ((x1, y1),))
    for a in WIRES:
        for b in WIRES:
            if a is b:
                continue
            ax1, ay1, ax2, ay2 = a
            bx1, by1, bx2, by2 = b
            if ax1 == ax2 == bx1 == bx2:
                lo_a, hi_a = sorted((ay1, ay2))
                lo_b, hi_b = sorted((by1, by2))
                if max(lo_a, lo_b) < min(hi_a, hi_b):
                    errs.append('overlapping V wires at x=%s' % ax1)
            elif ay1 == ay2 == by1 == by2:
                lo_a, hi_a = sorted((ax1, ax2))
                lo_b, hi_b = sorted((bx1, bx2))
                if max(lo_a, lo_b) < min(hi_a, hi_b):
                    errs.append('overlapping H wires at y=%s' % ay1)

    parent = {}
    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    wires = list(WIRES)
    for x1, y1, x2, y2 in wires:
        union((x1, y1), (x2, y2))

    def pt_on_seg(x, y, x1, y1, x2, y2, strict):
        eps = 1e-9
        if x1 == x2:
            if abs(x - x1) > eps:
                return False
            lo, hi = sorted((y1, y2))
            return lo + eps < y < hi - eps if strict else lo - eps <= y <= hi + eps
        if abs(y - y1) > eps:
            return False
        lo, hi = sorted((x1, x2))
        return lo + eps < x < hi - eps if strict else lo - eps <= x <= hi + eps

    pins = [(ref, num, net) + pinpos(ref, num) for (ref, num), net in NETMAP.items()]
    attaches = []
    for ref, num, net, px, py in pins:
        attaches.append(((px, py), 'pin', (ref, num, net)))
    for name, x, y, ang in LBL:
        attaches.append(((x, y), 'label', name))
    for x, y in GNDS:
        attaches.append(((x, y), 'gnd', 'GND'))
    for net, x, y in FLAGS:
        attaches.append(((x, y), 'flag', net))
    for x, y in NCS:
        attaches.append(((x, y), 'nc', None))
    for x, y in JUNCS:
        attaches.append(((x, y), 'junc', None))

    for pt, kind, info in attaches:
        hit = False
        for x1, y1, x2, y2 in wires:
            if pt_on_seg(pt[0], pt[1], x1, y1, x2, y2, strict=False):
                hit = True
                union(pt, (x1, y1))
                if kind in ('pin', 'gnd', 'flag') and \
                        pt_on_seg(pt[0], pt[1], x1, y1, x2, y2, strict=True) and \
                        pt not in JUNCS:
                    errs.append('%s %s lands mid-wire without junction %s' % (kind, info, pt))
        if kind == 'nc' and hit:
            errs.append('NC flag touches wire at %s' % (pt,))
        if kind == 'nc':
            continue
        touched = hit or any(p == pt for p, k, _ in attaches if k != 'nc')
        if not touched:
            errs.append('%s %s floats at %s' % (kind, info, pt))

    netpins, netnames = defaultdict(set), defaultdict(set)
    for pt, kind, info in attaches:
        if kind == 'pin':
            netpins[find(pt)].add((info[0], info[1]))
        elif kind in ('label', 'gnd'):
            netnames[find(pt)].add(info)
    intended = defaultdict(set)
    for (ref, num), net in NETMAP.items():
        intended[net].add((ref, num))
    # islands that hold pins; global labels/gnd symbols unite islands by name
    got = defaultdict(set)
    for root, names in netnames.items():
        pinset = netpins.get(root, set())
        if not pinset:
            continue
        if not names:
            errs.append('island with pins but no net name: %s' % sorted(pinset))
            continue
        if len(names) > 1:
            errs.append('island with multiple names %s: %s' % (names, pinset))
        for nm in names:
            got[nm] |= pinset
    if set(got) != set(intended):
        errs.append('net name sets differ: extra=%s missing=%s' %
                    (set(got) - set(intended), set(intended) - set(got)))
    else:
        for nm in intended:
            if got.get(nm, set()) != intended[nm]:
                errs.append('net %s differs:\n  got      %s\n  intended %s' %
                            (nm, sorted(got.get(nm, ())), sorted(intended[nm])))
    for x, y in JUNCS:
        n = sum(1 for x1, y1, x2, y2 in wires
                if pt_on_seg(x, y, x1, y1, x2, y2, strict=False))
        n += sum(1 for pt, k, _ in attaches
                 if k in ('pin', 'label', 'gnd', 'flag') and pt == (x, y))
        if n < 2:
            errs.append('junction at %s has only %d connections' % ((x, y), n))
    for x1, y1, x2, y2 in wires:
        for pt in ((x1, y1), (x2, y2)):
            touched = any(p == pt for p, k, _ in attaches if k != 'junc') or \
                any(pt_on_seg(pt[0], pt[1], a, b, c, d, strict=False)
                    for a, b, c, d in wires if (a, b, c, d) != (x1, y1, x2, y2))
            if not touched:
                errs.append('dangling wire endpoint %s' % (pt,))
    return errs

errs = verify()
if errs:
    print('VERIFY FAILED (%d):' % len(errs))
    for e in errs[:80]:
        print('  -', e)
    sys.exit(1)
print('verify OK: %d wires, %d junctions, %d labels, %d gnd, %d nc, %d flags, %d parts'
      % (len(WIRES), len(JUNCS), len(LBL), len(GNDS), len(NCS), len(FLAGS), len(PLACE)))

if '--dry' in sys.argv:
    sys.exit(0)

# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------
def U():
    return str(uuid.uuid4())

def fmt(v):
    v = round(v, 3)
    return str(int(v)) if v == int(v) else ('%.3f' % v).rstrip('0').rstrip('.')

JUST = {'l': 'left', 'r': 'right', 'c': ''}

def prop(ref, name, value, dx, dy, just, hide):
    pl = PLACE[ref]
    head = ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s 0)\n'
            % (name, value, fmt(pl['x'] + dx), fmt(pl['y'] + dy)))
    if hide:
        head += '\t\t\t(hide yes)\n'
    head += '\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n'
    eff = '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
    if just and not hide:
        eff += '\t\t\t\t(justify %s)\n' % JUST[just]
    eff += '\t\t\t)\n\t\t)\n'
    return head + eff

def make_power_sym(lib, refdisp, x, y, desc):
    val = 'GND' if lib.endswith('GND') else 'PWR_FLAG'
    def pr(name, value, dy, hide):
        h = '\t\t\t(hide yes)\n' if hide else ''
        return ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s 0)\n%s'
                '\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n'
                '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
                % (name, value, fmt(x), fmt(y + dy), h))
    return ('\t(symbol\n\t\t(lib_id "%s")\n\t\t(at %s %s 0)\n\t\t(unit 1)\n'
            '\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n'
            '\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)\n\t\t(uuid "%s")\n'
            '%s%s%s%s%s'
            '\t\t(pin "1"\n\t\t\t(uuid "%s")\n\t\t)\n'
            '\t\t(instances\n\t\t\t(project "Maxxi"\n\t\t\t\t(path "/%s"\n'
            '\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)'
            % (lib, fmt(x), fmt(y), U(),
               pr('Reference', refdisp, -1.27, True),
               pr('Value', val, 1.27, False),
               pr('Footprint', '', 0, True),
               pr('Datasheet', '', 0, True),
               pr('Description', desc, 0, True),
               U(), ROOT_UUID, refdisp))

out = []
out.append('(kicad_sch')
out.append('\t(version 20260306)')
out.append('\t(generator "eeschema")')
out.append('\t(generator_version "10.0")')
out.append('\t(uuid "%s")' % ROOT_UUID)
out.append('\t(paper "A3")')
out.append('\t(title_block')
out.append('\t\t(title "Maxxi - USB-C PD Eurorack power supply")')
out.append('\t\t(date "2026-09-22")')
out.append('\t\t(rev "1")')
out.append('\t\t(company "Nanas Sound OÜ")')
out.append('\t)')
out.append('\t(lib_symbols')
for lid in ('Device:C', 'Device:C_Polarized', 'Device:D_Schottky', 'Device:D_TVS',
            'Device:L', 'Device:LED', 'Device:Polyfuse', 'Device:R',
            'Maxxi:CH224K', 'Maxxi:Eurorack_Power_16pin_Shrouded', 'Maxxi:LT3015EDD',
            'Maxxi:USB_C_Receptacle_USB2.0_16P', 'Maxxi:VN02A1500000G',
            'Regulator_Linear:LT1963EQ', 'Regulator_Linear:LT1963AEQ',
            'Regulator_Switching:TPS54360DDA', 'power:GND', 'power:PWR_FLAG'):
    if lid in LIBDEF:
        out.append(LIBDEF[lid])
out.append('\t)')

for title, members, padl in GROUPS:
    x1, y1, x2, y2 = group_box(members, padl)
    out.append('\t(rectangle\n\t\t(start %s %s)\n\t\t(end %s %s)\n'
               '\t\t(stroke\n\t\t\t(width 0.254)\n\t\t\t(type dash)\n'
               '\t\t\t%s\n\t\t)\n\t\t(fill\n\t\t\t(type none)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)'
               % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), BLUE, U()))
    out.append('\t(text "%s"\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n'
               '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
               '\t\t\t\tbold\n\t\t\t)\n\t\t\t(justify left)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)'
               % (title, fmt(x1 + 2.54), fmt(y1 + 2.54), U()))

for x1, y1, x2, y2 in WIRES:
    out.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n'
               '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), U()))
for x, y in JUNCS:
    out.append('\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n'
               '\t\t(uuid "%s")\n\t)' % (fmt(x), fmt(y), U()))
for name, x, y, ang in LBL:
    out.append('\t(global_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s %d)\n'
               '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)' % (name, fmt(x), fmt(y), ang, U()))
for x, y in NCS:
    out.append('\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)' % (fmt(x), fmt(y), U()))

for i, (net, x, y) in enumerate(FLAGS, 1):
    out.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n'
               '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)' % (fmt(x), fmt(y), fmt(x + 2.54), fmt(y), U()))
    out.append('\t(global_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s 0)\n'
               '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n'
               '\t\t(uuid "%s")\n\t)' % (net, fmt(x + 2.54), fmt(y), U()))
    out.append(make_power_sym('power:PWR_FLAG', '#FLG%02d' % i, x, y,
                              'Special symbol for telling ERC where power comes from'))
for i, (x, y) in enumerate(GNDS, 1):
    out.append(make_power_sym('power:GND', '#PWR%03d' % i, x, y,
                              'Power symbol creates a global label with name \\"GND\\" , ground'))

for ref in sorted(PLACE, key=lambda r: (len(r), r)):
    inst = INST[ref]
    pl = PLACE[ref]
    out.append('\t(symbol')
    out.append('\t\t(lib_id "%s")' % inst['lib'])
    out.append('\t\t(at %s %s %d)%s' % (fmt(pl['x']), fmt(pl['y']), pl['rot'],
                                        '\n\t\t(mirror y)' if pl['my'] else ''))
    out.append('\t\t(unit 1)')
    out.append('\t\t(body_style 1)')
    out.append('\t\t(exclude_from_sim no)')
    out.append('\t\t(in_bom %s)' % inst['in_bom'])
    out.append('\t\t(on_board yes)')
    out.append('\t\t(in_pos_files yes)')
    out.append('\t\t(dnp %s)' % inst['dnp'])
    out.append('\t\t(uuid "%s")' % U())
    for name, value in inst['props']:
        if name == 'Reference':
            dx, dy, just = pl['rt'] or (0, -11.43, 'c')
            out.append(prop(ref, name, value, dx, dy, just, False))
        elif name == 'Value':
            dx, dy, just = pl['vt'] or (0, 11.43, 'c')
            out.append(prop(ref, name, value, dx, dy, just, False))
        else:
            out.append(prop(ref, name, value, 0, 0, '', True))
    for num in inst['pins']:
        out.append('\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)' % (num, U()))
    out.append('\t\t(instances\n\t\t\t(project "Maxxi"\n\t\t\t\t(path "/%s"\n'
               '\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)'
               % (ROOT_UUID, ref))
    out.append('\t)')

out.append('\t(sheet_instances')
out.append('\t\t(path "/"')
out.append('\t\t\t(page "1")')
out.append('\t\t)')
out.append('\t)')
out.append('\t(embedded_fonts no)')
out.append(')')

SCH.write_text('\n'.join(out) + '\n')
print('wrote %s' % SCH)

# --------------------------------------------------------------------------
# Post-emit geometry lint: text boxes vs bodies/wires/borders (run via --lint)
# --------------------------------------------------------------------------
def _text_boxes():
    CH = 0.85  # mm per char estimate at 1.27 font (conservative)
    boxes = []  # (x1,y1,x2,y2, tag)
    for ref, pl in PLACE.items():
        for key, default in (('rt', (0, -11.43, 'c')), ('vt', (0, 11.43, 'c'))):
            dx, dy, just = pl.get(key) or default
            txt = ref if key == 'rt' else INST[ref]['props'][1][1]
            w = max(len(txt), 1) * CH
            x, y = pl['x'] + dx, pl['y'] + dy
            if just == 'l':
                box = (x, y - 1.0, x + w, y + 0.3)
            elif just == 'r':
                box = (x - w, y - 1.0, x, y + 0.3)
            else:
                box = (x - w/2, y - 1.0, x + w/2, y + 0.3)
            boxes.append(box + ('%s:%s' % (ref, key),))
    for name, x, y, ang in LBL:
        w = max(len(name), 1) * CH
        if ang == 0:
            box = (x, y - 1.1, x + w, y + 0.2)
        elif ang == 180:
            box = (x - w, y - 1.1, x, y + 0.2)
        elif ang == 90:
            box = (x - 0.2, y - w - 0.3, x + 1.1, y)
        else:
            box = (x - 0.2, y, x + 1.1, y + w + 0.3)
        boxes.append(box + ('lbl:' + name,))
    return boxes

def _body_boxes():
    out = []
    for ref, pl in PLACE.items():
        bx1, by1, bx2, by2 = LIBBBOX[INST[ref]['lib']]
        corners = [tf(px, py, pl['rot'], pl['my']) for px, py in
                   ((bx1, by1), (bx2, by1), (bx1, by2), (bx2, by2))]
        xs = [pl['x'] + c[0] for c in corners]
        ys = [pl['y'] + c[1] for c in corners]
        out.append((min(xs), min(ys), max(xs), max(ys), ref))
    return out

def _rect_overlap(a, b, pad=0.0):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or
                a[3] + pad < b[1] or b[3] + pad < a[1])

def lint():
    issues = []
    tb = _text_boxes()
    bb = _body_boxes()
    # text vs text
    for i in range(len(tb)):
        for j in range(i + 1, len(tb)):
            if _rect_overlap(tb[i][:4], tb[j][:4]):
                issues.append('TEXT/TEXT %s %s vs %s %s' %
                              (tb[i][4], tb[i][:4], tb[j][4], tb[j][:4]))
    # text vs foreign bodies
    for t in tb:
        for b in bb:
            ref = t[4].split(':')[0]
            if b[4] == ref:
                continue
            if _rect_overlap(t[:4], b[:4], pad=0.1):
                issues.append('TEXT/BODY %s %s overlaps body of %s %s' %
                              (t[4], t[:4], b[4], b[:4]))
    # label text vs foreign wires: wire net via union-find-lite
    wires = list(WIRES)
    def wires_of_net_at(x, y):
        return [w for w in wires if (abs(w[0]-x) < 1e-6 and abs(w[1]-y) < 1e-6) or
                (abs(w[2]-x) < 1e-6 and abs(w[3]-y) < 1e-6) or
                (w[0] == w[2] and abs(w[0]-x) < 1e-6 and min(w[1], w[3]) <= y <= max(w[1], w[3])) or
                (w[1] == w[3] and abs(w[1]-y) < 1e-6 and min(w[0], w[2]) <= x <= max(w[0], w[2]))]
    for name, x, y, ang in LBL:
        w = max(len(name), 1) * 0.85
        if ang == 0:
            box = (x + 0.2, y - 1.1, x + w, y - 0.1)   # text body only (above wire)
        elif ang == 180:
            box = (x - w, y - 1.1, x - 0.2, y - 0.1)
        elif ang == 90:
            box = (x + 0.2, y - w, x + 1.1, y - 0.2)
        else:
            box = (x + 0.2, y + 0.2, x + 1.1, y + w)
        for wx1, wy1, wx2, wy2 in wires:
            # skip wires touching the label anchor point
            def near(px, py):
                return abs(px - x) < 1e-6 and abs(py - y) < 1e-6
            if near(wx1, wy1) or near(wx2, wy2):
                continue
            if wx1 == wx2:
                if wx1 + 1e-9 < box[0] or wx1 > box[2] + 1e-9:
                    continue
                if max(wy1, wy2) < box[1] or min(wy1, wy2) > box[3]:
                    continue
            else:
                if wy1 + 1e-9 < box[1] or wy1 > box[3] + 1e-9:
                    continue
                if max(wx1, wx2) < box[0] or min(wx1, wx2) > box[2]:
                    continue
            issues.append('LABEL/WIRE %s@%s,%s crosses wire %s' % (name, x, y, (wx1, wy1, wx2, wy2)))
    # wires through foreign bodies
    for wx1, wy1, wx2, wy2 in wires:
        for b in bb:
            ref = b[4]
            pins = [pinpos(ref, n) for n in LIBPINS[INST[ref]['lib']]]
            onpins = any(abs(px-wx1) < 1e-6 and abs(py-wy1) < 1e-6 or
                         abs(px-wx2) < 1e-6 and abs(py-wy2) < 1e-6 for px, py in pins)
            if onpins:
                continue
            # shrink body slightly
            bx1, by1, bx2, by2 = b[0] + 0.3, b[1] + 0.3, b[2] - 0.3, b[3] - 0.3
            # segment vs rect
            if wx1 == wx2:
                if not (bx1 < wx1 < bx2):
                    continue
                lo, hi = sorted((wy1, wy2))
                if lo < by2 and hi > by1:
                    issues.append('WIRE/BODY vertical wire %s passes through %s' % ((wx1, wy1, wx2, wy2), ref))
            else:
                if not (by1 < wy1 < by2):
                    continue
                lo, hi = sorted((wx1, wx2))
                if lo < bx2 and hi > bx1:
                    issues.append('WIRE/BODY horizontal wire %s passes through %s' % ((wx1, wy1, wx2, wy2), ref))
    return issues

if '--lint' in sys.argv:
    errs = verify()
    if errs:
        print('verify failed; fix first')
        sys.exit(1)
    li = lint()
    print('lint: %d issues' % len(li))
    for it in li:
        print('  -', it)
    sys.exit(0)
