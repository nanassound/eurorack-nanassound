#!/usr/bin/env python3
"""Fix J3 USB-C shell pads: oval 1.2x0.7 pad, oval 0.55x0.4 drill.

Original 0.6 round pad / 0.6 drill had zero annular ring, and a round pad
large enough for ring violates clearance to the A4B9/B4A9 power pads
(0.36 mm vertical budget). Oval keeps ring (x 0.325 / y 0.15) and gap 0.21.
"""
import sys
import pcbnew

BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
b = pcbnew.LoadBoard(BOARD)
n = 0
for fp in b.GetFootprints():
    if fp.GetReference() != "J3":
        continue
    for p in fp.Pads():
        if int(p.GetAttribute()) == 0 and p.GetNumber() == "":
            p.SetSize(pcbnew.VECTOR2I(1200000, 700000))
            p.SetDrillSize(pcbnew.VECTOR2I(530000, 380000))
            p.SetShape(pcbnew.PAD_SHAPE_OVAL)
            n += 1
print(f"patched {n} shell pads -> oval 1.2x0.7 / drill 0.53x0.38")
pcbnew.SaveBoard(BOARD, b)
