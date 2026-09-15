#!/usr/bin/env python3
"""Import the freerouting Specctra session back into the board."""
import os
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
ses = os.path.join(PRJ, "Platvorm.ses")
board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
assert pcbnew.ImportSpecctraSES(board, ses), "SES import failed"
pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)

tracks = len(list(board.GetTracks()))
print(f"SES imported, saved; tracks+vias on board: {tracks}")
