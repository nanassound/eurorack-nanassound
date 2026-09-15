#!/usr/bin/env python3
"""8HP completion: finish IO5, IO2, USB_DP, IO18, IO19, VBUS-bridge
with obstacle-aware BFS (freerouting routed the rest)."""
import os
import pcbnew
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
mm = 1e6
CLEAR = 0.41  # 0.1 track half + 0.1 other half + 0.21 clearance
X0, Y0, X1, Y1 = 50.0, 50.0, 90.3, 130.0
STEP = 0.1
W, H = int((X1 - X0) / STEP), int((Y1 - Y0) / STEP)

board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name): n for name, n in board.GetNetsByName().items()}

def add_seg(x1, y1, x2, y2, netname, width_mm, layer):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
    t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
    t.SetWidth(int(width_mm * mm))
    t.SetLayer(pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu)
    t.SetNet(nets[netname])
    board.Add(t)

def add_via(x, y, netname):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(int(x * mm), int(y * mm)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(int(0.7 * mm))
    v.SetDrill(int(0.3 * mm))
    v.SetNet(nets[netname])
    board.Add(v)

def cells_of(x, y, r):
    x0, x1 = int((x - r - X0) / STEP), int((x + r - X0) / STEP) + 1
    y0, y1 = int((y - r - Y0) / STEP), int((y + r - Y0) / STEP) + 1
    for gy in range(max(0, y0), min(H, y1)):
        for gx in range(max(0, x0), min(W, x1)):
            cx, cy = X0 + gx * STEP, Y0 + gy * STEP
            if (cx - x) ** 2 + (cy - y) ** 2 <= r * r:
                yield gx, gy

SRC = {}
def build(layer, route_net):
    SRC.clear()
    g = [[False] * W for _ in range(H)]
    pl = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            if str(t.GetNetname()) == route_net:
                continue
            for gx, gy in cells_of(t.GetPosition().x / mm, t.GetPosition().y / mm, 0.35 + CLEAR):
                g[gy][gx] = True
                SRC.setdefault((gx, gy), 'VIA ' + str(t.GetNetname()))
            continue
        if t.GetLayer() != pl or str(t.GetNetname()) == route_net:
            continue
        n = int(max(abs(t.GetEnd().x - t.GetStart().x), abs(t.GetEnd().y - t.GetStart().y)) / mm / 0.05) + 1
        for i in range(n + 1):
            tt = i / n
            cx = (t.GetStart().x + (t.GetEnd().x - t.GetStart().x) * tt) / mm
            cy = (t.GetStart().y + (t.GetEnd().y - t.GetStart().y) * tt) / mm
            for gx, gy in cells_of(cx, cy, t.GetWidth() / mm / 2 + CLEAR):
                g[gy][gx] = True
                SRC.setdefault((gx, gy), 'TRK ' + str(t.GetNetname()))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if str(p.GetNetname()) == route_net or not p.IsOnLayer(pl):
                continue
            bb = p.GetBoundingBox()
            tagp = 'PAD ' + str(p.GetNetname()) + ' ' + fp.GetReference() + '.' + p.GetNumber()
            for gy in range(max(0, int((bb.GetTop() / mm - CLEAR - Y0) / STEP)),
                            min(H, int((bb.GetBottom() / mm + CLEAR - Y0) / STEP) + 1)):
                for gx in range(max(0, int((bb.GetLeft() / mm - CLEAR - X0) / STEP)),
                                min(W, int((bb.GetRight() / mm + CLEAR - X0) / STEP) + 1)):
                    g[gy][gx] = True
                    SRC.setdefault((gx, gy), tagp)
    m = int((0.3 + CLEAR) / STEP)
    for gy in range(H):
        for gx in range(W):
            if gx < m or gx >= W - m or gy < m or gy >= H - m:
                g[gy][gx] = True
    return g

def cell(x, y):
    return int((x - X0) / STEP), int((y - Y0) / STEP)

def bfs(g, start, goal):
    prev = {start: None}
    q = deque([start])
    while q:
        c = q.popleft()
        if c == goal:
            break
        x, y = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if 0 <= n[0] < W and 0 <= n[1] < H and n not in prev and not g[n[1]][n[0]]:
                prev[n] = c
                q.append(n)
    if goal not in prev:
        best = min(prev.keys(), key=lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1]))
        raise SystemExit(f"no path ->({goal}); closest ({X0 + best[0] * STEP:.2f},{Y0 + best[1] * STEP:.2f})")
    path, c = [], goal
    while c:
        path.append(c)
        c = prev[c]
    return path[::-1]

def to_segments(path):
    out = [path[0]]
    for i in range(1, len(path) - 1):
        ax, ay = out[-1]
        bx, by = path[i]
        cx, cy = path[i + 1]
        if (bx - ax, by - ay) != (cx - bx, cy - by):
            out.append(path[i])
    out.append(path[-1])
    return [((X0 + a[0] * STEP, Y0 + a[1] * STEP), (X0 + b[0] * STEP, Y0 + b[1] * STEP))
            for a, b in zip(out, out[1:])]

def grid_job(netname, w, layer, s, e):
    g = build(layer, netname)
    path = bfs(g, cell(*s), cell(*e))
    segs = to_segments(path)
    for (x1, y1), (x2, y2) in segs:
        add_seg(x1, y1, x2, y2, netname, w, layer)
    print(f"{netname}: routed {len(segs)} segments, {len(path) * STEP:.1f} mm on {layer}.Cu")

# +5V: J2.24 -> JP1.3 (B: right-margin descent x 89.9, then left along
# y 105.24 below IO0's diag and J2.13's pad, up into JP1.3)
add_seg(86.77, 78.57, 89.9, 78.57, "+5V", 0.2, "B")
add_seg(89.9, 78.57, 89.9, 105.24, "+5V", 0.2, "B")
add_seg(89.9, 105.24, 53.5, 105.24, "+5V", 0.2, "B")
add_seg(53.5, 105.24, 53.5, 83.54, "+5V", 0.2, "B")
print("+5V: routed")

# IO5: U1.5 -> right, jog over EP, down x 78.3 (right of IO22's diag,
# left of IO3's F vertical), then right into J2.8 (all F)
add_seg(62.0, 56.58, 62.3, 56.58, "IO5", 0.2, "F")
add_seg(62.3, 56.58, 62.3, 59.5, "IO5", 0.2, "F")
add_seg(62.3, 59.5, 78.3, 59.5, "IO5", 0.2, "F")
add_seg(78.3, 59.5, 78.3, 98.89, "IO5", 0.2, "F")
add_seg(78.3, 98.89, 86.77, 98.89, "IO5", 0.2, "F")
print("IO5: routed on F")

# IO2: via-in-pad27, straight down B x=88.85 (0.25 from IO18/IO19), into J2.5
add_via(88.85, 52.77, "IO2")
add_seg(88.85, 52.77, 88.85, 102.7, "IO2", 0.2, "B")
add_seg(88.85, 102.7, 85.23, 102.7, "IO2", 0.2, "B")
add_seg(85.23, 102.7, 85.23, 101.43, "IO2", 0.2, "B")
print("IO2: routed")

# USB_DP: U3.4 -> J3.A6 (F: right, then down the A6/B7 gap x=70.15)
add_seg(68.57, 118.162, 70.6, 118.162, "/USB & UART Bridge/USB_DP", 0.2, "F")
add_seg(70.6, 118.162, 70.6, 129.0, "/USB & UART Bridge/USB_DP", 0.2, "F")

# IO18: via-in-pad16, down x=88.7, row-gap y 84.92, col-gap channel x 85.5
add_via(88.4, 66.735, "IO18")
add_seg(88.4, 66.735, 88.4, 87.9, "IO18", 0.2, "B")
add_seg(88.4, 87.9, 85.5, 87.9, "IO18", 0.2, "B")
add_seg(85.5, 87.9, 85.5, 86.19, "IO18", 0.2, "B")
add_seg(85.5, 86.19, 84.98, 86.19, "IO18", 0.2, "B")

# IO19: via-in-pad17, down x=89.4, row-gap y 87.45, up into J2.18
add_via(89.55, 65.465, "IO19")
add_seg(89.55, 65.465, 89.55, 87.45, "IO19", 0.2, "B")
add_seg(89.55, 87.45, 86.77, 87.45, "IO19", 0.2, "B")
add_seg(86.77, 87.45, 86.77, 86.19, "IO19", 0.2, "B")

# VBUS: B4A9 -> A4B9 on B.Cu (vias in pads; tab rings clear by 0.205)
add_via(67.5, 129.0, "VBUS")
add_via(72.3, 129.0, "VBUS")
add_seg(67.5, 129.0, 72.3, 129.0, "VBUS", 0.2, "B")

pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
print("saved")
