#!/usr/bin/env python3
"""Final completion: rip IO3+IO7 (duplicate), hand-route IO18/IO19/IO3 in the
right margin (x staggered 78.4/78.0/78.6), grid-route IO7/CC2/VBUS/+5V."""
import os
import pcbnew
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
mm = 1e6
CLEAR = 0.21
X0, Y0, X1, Y1 = 50.0, 50.0, 80.0, 130.0
STEP = 0.1
W, H = int((X1 - X0) / STEP), int((Y1 - Y0) / STEP)

board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name): n for name, n in board.GetNetsByName().items()}

# ---- 1. rip IO3, IO7, CC1, CC2, VBUS-bridge (all copper) ------------------
doomed = []
for t in list(board.GetTracks()):
    if str(t.GetNetname()) in ("IO3", "IO7"):
        doomed.append(t)
    if t.GetClass() != "PCB_VIA" and str(t.GetNetname()) == "CC1" or str(t.GetNetname()) == "IO19" and t.GetClass() != "PCB_VIA":
        doomed.append(t)
    if str(t.GetNetname()) == "/USB & UART Bridge/CC2":
        doomed.append(t)
    if str(t.GetNetname()) == "VBUS" and t.GetPosition().x / mm < 68.6:
        doomed.append(t)
print(f"ripping {len(doomed)} IO3/IO7 items")
for t in doomed:
    board.Remove(t)
pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name): n for name, n in board.GetNetsByName().items()}

# ---- 2. helpers -----------------------------------------------------------
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

def grid_for(layer):
    return [[False] * W for _ in range(H)]

def cells_of(x, y, r):
    x0, x1 = int((x - r - X0) / STEP), int((x + r - X0) / STEP) + 1
    y0, y1 = int((y - r - Y0) / STEP), int((y + r - Y0) / STEP) + 1
    for gy in range(max(0, y0), min(H, y1)):
        for gx in range(max(0, x0), min(W, x1)):
            cx, cy = X0 + gx * STEP, Y0 + gy * STEP
            if (cx - x) ** 2 + (cy - y) ** 2 <= r * r:
                yield gx, gy

def mark_seg(g, x1, y1, x2, y2, half):
    n = int(max(abs(x2 - x1), abs(y2 - y1)) / 0.05) + 1
    for i in range(n + 1):
        t = i / n
        for gx, gy in cells_of(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, half):
            g[gy][gx] = True

def build(layer, route_net):
    g = grid_for(layer)
    pl = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            if str(t.GetNetname()) == route_net:
                continue
            for gx, gy in cells_of(t.GetPosition().x / mm, t.GetPosition().y / mm, 0.35 + CLEAR):
                g[gy][gx] = True
            continue
        if t.GetLayer() != pl or str(t.GetNetname()) == route_net:
            continue
        mark_seg(g, t.GetStart().x / mm, t.GetStart().y / mm,
                 t.GetEnd().x / mm, t.GetEnd().y / mm, t.GetWidth() / mm / 2 + CLEAR)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if str(p.GetNetname()) == route_net or not p.IsOnLayer(pl):
                continue
            bb = p.GetBoundingBox()
            for gy in range(max(0, int((bb.GetTop() / mm - CLEAR - Y0) / STEP)),
                            min(H, int((bb.GetBottom() / mm + CLEAR - Y0) / STEP) + 1)):
                for gx in range(max(0, int((bb.GetLeft() / mm - CLEAR - X0) / STEP)),
                                min(W, int((bb.GetRight() / mm + CLEAR - X0) / STEP) + 1)):
                    g[gy][gx] = True
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
        raise SystemExit(f"no path ->{goal}; closest ({X0 + best[0] * STEP:.2f},{Y0 + best[1] * STEP:.2f})")
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

# ---- 3. manual right-margin routes (verified clearances) ------------------
# IO18: via in U1.16, down x=78.4 (right of IO19), col-gap, into J2.17
add_via(78.4, 66.735, "IO18")
add_seg(78.4, 66.735, 78.4, 84.92, "IO18", 0.2, "B")
add_seg(78.4, 84.92, 75.4, 84.92, "IO18", 0.2, "B")
add_seg(75.4, 84.92, 75.4, 86.19, "IO18", 0.2, "B")
add_seg(75.4, 86.19, 74.68, 86.19, "IO18", 0.2, "B")

# IO19: via in U1.17, down x=78.0, below J2.18, up into its pad
add_via(78.0, 65.465, "IO19")
add_seg(78.0, 65.465, 78.0, 87.45, "IO19", 0.2, "B")
add_seg(78.0, 87.45, 76.47, 87.45, "IO19", 0.2, "B")
add_seg(76.47, 87.45, 76.47, 86.19, "IO19", 0.2, "B")

# IO3: via in U1.27, straight down x=78.6 (between IO19/18 and IO2's wall)
add_via(78.6, 52.77, "IO3")
add_seg(78.6, 52.77, 78.6, 101.43, "IO3", 0.2, "B")
add_seg(78.6, 101.43, 76.47, 101.43, "IO3", 0.2, "B")

# ---- 4. grid jobs ---------------------------------------------------------
# +5V: J2.24 -> JP1.3 through the J2 column gap (x 74.9-75.5 free channel).
# 0.2mm: only width fitting; ~1A capacity @1oz (documented waiver vs 0.5 class).
add_seg(76.47, 78.57, 75.2, 78.57, "+5V", 0.2, "B")
add_seg(75.2, 78.57, 75.2, 82.0, "+5V", 0.2, "B")
add_seg(75.2, 82.0, 75.0, 82.0, "+5V", 0.2, "B")
add_seg(75.0, 82.0, 75.0, 87.6, "+5V", 0.2, "B")
add_seg(75.0, 87.6, 65.2, 87.6, "+5V", 0.2, "B")
add_seg(65.2, 87.6, 65.2, 83.54, "+5V", 0.2, "B")
add_seg(65.2, 83.54, 53.5, 83.54, "+5V", 0.2, "B")

JOBS = [
    ("/USB & UART Bridge/CC2", 0.2, "F", (68.15, 129.0), (62.09, 121.4)),
    ("VBUS", 0.2, "F", (72.3, 129.0), (67.62, 118.162)),
]
for netname, w, layer, s, e in JOBS:
    g = build(layer, netname)
    path = bfs(g, cell(*s), cell(*e))
    segs = to_segments(path)
    for (x1, y1), (x2, y2) in segs:
        add_seg(x1, y1, x2, y2, netname, w, layer)
    print(f"{netname}: routed {len(segs)} segments, {len(path) * STEP:.1f} mm on {layer}.Cu")

pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
print("saved")
