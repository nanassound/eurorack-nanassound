#!/usr/bin/env python3
"""Refill zones and save (KiCad python)."""
import sys
import pcbnew

BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
b = pcbnew.LoadBoard(BOARD)
filler = pcbnew.ZONE_FILLER(b)
zones = [z for z in b.Zones()]
ok = filler.Fill(zones)
print("filled:", ok, "zones:", len(zones))
pcbnew.SaveBoard(BOARD, b)
