#!/usr/bin/env python3
"""Complete the 7 connections freerouting left behind + remove stub vias.
Coordinates verified against the placed board (see plan notes)."""
import os
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
mm = 1e6

board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name): n for name, n in board.GetNetsByName().items()}


def seg(pts, netname, width_mm, layer):
    net = nets[netname]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
        t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
        t.SetWidth(int(width_mm * mm))
        t.SetLayer(layer)
        t.SetNet(net)
        board.Add(t)


F, B = pcbnew.F_Cu, pcbnew.B_Cu

# VBUS: J3.B4A9 -> U3.5 (up the B1A12/B5 gap, x=67.67 cleared vs 0.1 pad clearance)
seg([(67.5, 128.6), (67.67, 128.5), (67.67, 118.162)], "VBUS", 0.2, F)

# CC2: J3.B5 -> R8.1 (up the B5/B6 gap, across y=125.6, down to R8.1)
seg([(68.15, 128.4), (68.475, 127.95), (68.475, 125.6), (61.45, 125.6),
     (61.45, 121.4), (62.09, 121.4)], "/USB & UART Bridge/CC2", 0.2, F)

# +5V: J2.24 -> JP1.3 (between J2 columns on B.Cu, 0.5mm power track)
seg([(76.47, 78.57), (75.2, 78.57), (75.2, 84), (66, 84), (54.2, 84),
     (53.5, 83.54)], "+5V", 0.5, B)

# IO7: U1.7 -> J2.10 (via at 59.8, right margin x=78.2 on B.Cu)
seg([(61.25, 59.115), (59.8, 59.115)], "IO7", 0.2, F)
seg([(59.8, 59.115), (78.2, 59.115), (78.2, 96.35), (77.22, 96.35)], "IO7", 0.2, B)

# IO18: U1.16 -> J2.17 (via in pad, down x=79.2, below J2, up the column gap)
seg([(79.2, 66.735), (79.2, 108.7), (72.5, 108.7), (72.5, 86.19), (74.68, 86.19)],
    "IO18", 0.2, B)

# IO19: U1.17 -> J2.18 (via in pad, down x=78.6, enter J2.18 from top)
seg([(78.6, 65.465), (78.6, 84.75), (76.9, 84.75), (76.9, 86.19)], "IO19", 0.2, B)


def via(x, y, netname):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(int(x * mm), int(y * mm)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(int(0.7 * mm))
    v.SetDrill(int(0.3 * mm))
    v.SetNet(nets[netname])
    board.Add(v)


via(59.8, 59.115, "IO7")
via(79.2, 66.735, "IO18")
via(78.6, 65.465, "IO19")

# --- delete dangling stub vias left by freerouting's optimizer ripup ---
STUBS = {  # (net, x, y) from DRC via_dangling list
    ("/USB & UART Bridge/USB_DP", 68.9499, 124.3278),
    ("VBUS", 67.62, 116.9213),
    ("/Power Supply/BOOT", 53.0516, 105.4812),
    ("IO4", 62.5041, 55.5324),
    ("IO6", 62.5025, 58.0708),
    ("IO0", 62.5163, 60.2926),
    ("IO10", 62.5041, 64.4208),
    ("/USB & UART Bridge/CC2", 61.386, 123.1454),
}
removed = 0
for t in list(board.GetTracks()):
    if t.GetClass() == "PCB_VIA":
        key = (t.GetNetname(), round(t.GetPosition().x / mm, 3), round(t.GetPosition().y / mm, 3))
        for s in STUBS:
            if key[0] == s[0] and abs(key[1] - s[1]) < 0.01 and abs(key[2] - s[2]) < 0.01:
                board.Remove(t)
                removed += 1
print(f"stub vias removed: {removed}/8")

pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
print("manual routes saved")
