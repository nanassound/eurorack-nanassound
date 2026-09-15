#!/usr/bin/env python3
"""Rip named nets' tracks/vias. Run in its own process; save repairs swig."""
import sys
import pcbnew
b = pcbnew.LoadBoard('Platvorm.kicad_pcb')
targets = {n.split('/')[-1] for n in sys.argv[1].split(',')}
doomed = [t for t in b.GetTracks()
          if str(t.GetNetname()).split('/')[-1] in targets]
for t in doomed:
    b.Remove(t)
pcbnew.SaveBoard('Platvorm.kicad_pcb', b)
print(f"ripped {len(doomed)} items for {sorted(targets)}")
