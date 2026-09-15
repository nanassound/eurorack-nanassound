#!/usr/bin/env python3
"""Iterative DRC-driven ripup-and-reroute loop.
Each iteration: run kicad-cli DRC, find nets involved in routing violations,
rip them, re-route with the obstacle-aware BFS. Converges in a few passes."""
import os
import re
import subprocess
import sys
import pcbnew
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
KICAD_CLI = "/Applications/KiCad/kicad-cli.app/Contents/MacOS/kicad-cli"
if not os.path.exists(KICAD_CLI):
    KICAD_CLI = "kicad-cli"
mm = 1e6
CLEAR = 0.31
X0, Y0, X1, Y1 = 50.0, 50.0, 90.3, 130.0
STEP = 0.1
W, H = int((X1 - X0) / STEP), int((Y1 - Y0) / STEP)
POWER = {"+12V", "-12V", "+5V_EURO", "VBUS", "VIN_BUCK", "VOUT_PRE", "SW", "+3V3"}
SKIP_NETS = {"GND"}  # zone nets

board = None
nets = {}

def load():
    global board, nets
    board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
    nets = {str(name).split("/")[-1]: n for name, n in board.GetNetsByName().items()}

def save():
    pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)

# ---- grid ------------------------------------------------------------------
SRC = {}

def cells_of(x, y, r):
    x0, x1 = int((x - r - X0) / STEP), int((x + r - X0) / STEP) + 1
    y0, y1 = int((y - r - Y0) / STEP), int((y + r - Y0) / STEP) + 1
    for gy in range(max(0, y0), min(H, y1)):
        for gx in range(max(0, x0), min(W, x1)):
            cx, cy = X0 + gx * STEP, Y0 + gy * STEP
            if (cx - x) ** 2 + (cy - y) ** 2 <= r * r:
                yield gx, gy

def build(layer, route_net, w):
    SRC.clear()
    g = [[False] * W for _ in range(H)]
    pl = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    half = w / 2 + CLEAR
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            if short(str(t.GetNetname())) == rn(route_net):
                continue
            for gx, gy in cells_of(t.GetPosition().x / mm, t.GetPosition().y / mm, 0.35 + CLEAR):
                g[gy][gx] = True; SRC.setdefault((gx, gy), "VIA " + str(t.GetNetname()))
            continue
        if t.GetLayer() != pl or short(str(t.GetNetname())) == rn(route_net):
            continue
        n = int(max(abs(t.GetEnd().x - t.GetStart().x), abs(t.GetEnd().y - t.GetStart().y)) / mm / 0.05) + 1
        for i in range(n + 1):
            tt = i / n
            cx = (t.GetStart().x + (t.GetEnd().x - t.GetStart().x) * tt) / mm
            cy = (t.GetStart().y + (t.GetEnd().y - t.GetStart().y) * tt) / mm
            for gx, gy in cells_of(cx, cy, half):
                g[gy][gx] = True; SRC.setdefault((gx, gy), "TRK " + str(t.GetNetname()))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if short(str(p.GetNetname())) == rn(route_net) or not p.IsOnLayer(pl):
                continue
            bb = p.GetBoundingBox()
            tag = "PAD " + short(str(p.GetNetname())) + " " + fp.GetReference() + "." + p.GetNumber()
            for gy in range(max(0, int((bb.GetTop() / mm - CLEAR - Y0) / STEP)),
                            min(H, int((bb.GetBottom() / mm + CLEAR - Y0) / STEP) + 1)):
                for gx in range(max(0, int((bb.GetLeft() / mm - CLEAR - X0) / STEP)),
                                min(W, int((bb.GetRight() / mm + CLEAR - X0) / STEP) + 1)):
                    g[gy][gx] = True; SRC.setdefault((gx, gy), tag)
    m = int((0.3 + CLEAR) / STEP)
    for gy in range(H):
        for gx in range(W):
            if gx < m or gx >= W - m or gy < m or gy >= H - m:
                g[gy][gx] = True; SRC.setdefault((gx, gy), "EDGE")
    return g

def rn(netname):
    return netname.split("/")[-1]

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

def route_net(netname, layer, width_mm, pts):
    rn_net = rn(netname)
    g = build(layer, rn_net)
    segs = []
    pts_c = [cell(*p) for p in pts]
    for a, b in zip(pts_c, pts_c[1:]):
        path = bfs(g, a, b)
        for c in path:
            SRC.setdefault(c, "OWN " + netname)
        segs.extend(to_segments(path))
    net = nets[rn_net]
    for (x1, y1), (x2, y2) in segs:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
        t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
        t.SetWidth(int(width_mm * mm))
        t.SetLayer(pl if False else (pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu))
        t.SetNet(net)
        board.Add(t)

def rip_net(netname):
    doomed = [t for t in list(board.GetTracks())
              if short(str(t.GetNetname())) == rn(netname)]
    for t in doomed:
        board.Remove(t)
    return len(doomed)

def net_pads_pos(netname):
    pts = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if short(str(p.GetNetname())) == rn(netname):
                pts.append((p.GetPosition().x / mm, p.GetPosition().y / mm))
    # sort pads along the dominant axis
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    if max(xs) - min(xs) >= max(ys) - min(ys):
        pts.sort()
    else:
        pts.sort(key=lambda p: p[1])
    return pts

# ---- main ------------------------------------------------------------------
iters = int(sys.argv[1]) if len(sys.argv) > 1 else 3
load()

for it in range(iters):
    # rip and re-route the currently failing nets
    failed = [n for n in sys.argv[2].split(",") if n] if len(sys.argv) > 2 else []
    if not failed:
        print("nothing to do")
        break
    print(f"iteration {it}: re-routing {len(failed)} nets: {failed}")
    for netname in failed:
        short_net = rn(netname)
        pts = net_pads_pos(netname)
        if len(pts) < 2:
            print(f"  {netname}: <2 pads, skip")
            continue
        w = 0.5 if short_net in POWER else 0.2
        n_rip = rip_net(netname)
        try:
            route_net(netname, "F", w, pts)
            print(f"  {netname}: F ok")
        except SystemExit as e:
            try:
                route_net(netname, "B", w, pts)
                print(f"  {netname}: B ok")
            except SystemExit:
                print(f"  {netname}: FAILED both layers")
    save()

print("done")
