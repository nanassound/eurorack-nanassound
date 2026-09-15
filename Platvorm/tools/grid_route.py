#!/usr/bin/env python3
"""Remove conflicting hand routes, then re-route the 5 unfinished connections
with a 0.1 mm-grid BFS that respects actual board occupancy.
Idempotent: safe to re-run (skips already-routed work via same-net exemption).
"""
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

# ---- 1. removals (collect first, then remove; pcbnew iterators are fragile)
doomed = []
for t in list(board.GetTracks()):
    if t.GetClass() == "PCB_VIA":
        if (str(t.GetNetname()) in ("IO18", "IO19")
                and abs(t.GetPosition().x / mm - 79.2) < 5
                and t.GetPosition().x / mm > 76):
            doomed.append(t)  # old in-pad IO18/IO19 vias from earlier attempts
        if (str(t.GetNetname()) == "IO7"
                and abs(t.GetPosition().x / mm - 59.8) < 0.05):
            doomed.append(t)
    else:
        if (str(t.GetNetname()) == "IO7" and t.GetLayer() == pcbnew.F_Cu
                and abs(t.GetStart().x / mm - 61.25) < 0.05
                and abs(t.GetEnd().x / mm - 59.8) < 0.05):
            doomed.append(t)

print(f"removing {len(doomed)} stale items")
for t in doomed:
    board.Remove(t)
pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name): n for name, n in board.GetNetsByName().items()}

# ---- 2. grid router -------------------------------------------------------
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
        raise SystemExit(f"no path {start}->{goal}; closest {best} "
                         f"= ({X0 + best[0] * STEP:.2f},{Y0 + best[1] * STEP:.2f})")
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

def add_track(segs, netname, width_mm, layer):
    net = nets[netname]
    pl = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    for (x1, y1), (x2, y2) in segs:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
        t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
        t.SetWidth(int(width_mm * mm))
        t.SetLayer(pl)
        t.SetNet(net)
        board.Add(t)

def via(x, y, netname):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(int(x * mm), int(y * mm)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(int(0.7 * mm))
    v.SetDrill(int(0.3 * mm))
    v.SetNet(nets[netname])
    board.Add(v)

def already_routed(netname, target):
    """heuristic: net has a track endpoint within 0.6mm of the target pad"""
    for t in board.GetTracks():
        if t.GetClass() != "PCB_VIA" and str(t.GetNetname()) == netname:
            for pt in (t.GetStart(), t.GetEnd()):
                if (pt.x / mm - target[0]) ** 2 + (pt.y / mm - target[1]) ** 2 < 0.36:
                    return True
    return False

JOBS = [
    ("+5V", 0.5, "B", (76.47, 78.57), (53.5, 83.54)),
    ("/USB & UART Bridge/CC2", 0.2, "F", (68.15, 129.0), (62.09, 121.4)),
]
for netname, w, layer, s, e in JOBS:
    if already_routed(netname, e):
        print(f"{netname}: already routed, skipping")
        continue
    g = build(layer, netname)
    path = bfs(g, cell(*s), cell(*e))
    segs = to_segments(path)
    add_track(segs, netname, w, layer)
    print(f"{netname}: routed {len(segs)} segments, {len(path) * STEP:.1f} mm on {layer}.Cu")


def via_job(netname, pad_center, target, xs, ys):
    for vy in ys:
        for vx in xs:
            g = build("B", netname)
            sc = cell(vx, vy)
            if g[sc[1]][sc[0]]:
                print(f"  {netname} via ({vx},{vy}): blocked")
                continue
            try:
                path = bfs(g, sc, cell(*target))
            except SystemExit as e:
                print(f"  {netname} via ({vx},{vy}): {e}")
                continue
            add_track([(pad_center, (vx, vy))], netname, 0.2, "F")
            add_track(to_segments(path), netname, 0.2, "B")
            via(vx, vy, netname)
            print(f"{netname}: via ({vx},{vy}), {len(path) * STEP:.1f} mm on B.Cu")
            return True
    print(f"{netname}: FAILED")
    return False


via_job("IO7", (61.25, 59.115), (76.47, 96.35),
        [61.0, 60.7, 60.9, 61.2], [59.1, 59.3, 58.9])
JOBS2 = [
    ("IO18", 0.2, "F", (78.75, 66.735), (73.93, 86.19)),
    ("IO19", 0.2, "F", (78.75, 65.465), (76.47, 86.19)),
]
for netname, w, layer, s, e in JOBS2:
    if already_routed(netname, e):
        print(f"{netname}: already routed, skipping")
        continue
    g = build(layer, netname)
    path = bfs(g, cell(*s), cell(*e))
    segs = to_segments(path)
    add_track(segs, netname, w, layer)
    print(f"{netname}: routed {len(segs)} segments, {len(path) * STEP:.1f} mm on {layer}.Cu")

pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
print("saved")
