#!/usr/bin/env python3
"""Rip all routing and grid-route every net (obstacle-aware sequential BFS).
GND is left to the zone pour. Power nets 0.5mm, signals 0.2mm."""
import os
import pcbnew
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
mm = 1e6
CLEAR = 0.41
X0, Y0, X1, Y1 = 50.0, 50.0, 90.3, 130.0
STEP = 0.1
W, H = int((X1 - X0) / STEP), int((Y1 - Y0) / STEP)
POWER_NETS = {"+12V", "+12V_RAW", "+3V3", "+5V", "+5V_EURO", "-12V",
              "-12V_RAW", "VBUS", "VIN_BUCK", "VOUT_PRE", "SW"}
TRACK_W = {"power": 0.5, "signal": 0.2}

board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name).split("/")[-1]: n for name, n in board.GetNetsByName().items()}
# pcbnew 10 quirk: board.Remove() corrupts Tracks(); keep our own registry
TRACK_REG = list(board.GetTracks())

def rip_all():
    # Never call board.Remove(): it corrupts the pcbnew swig runtime.
    # The board arrives fresh from layout_build (no tracks); if tracks exist,
    # route on a COPY of their list but do not remove them.
    if TRACK_REG:
        print(f"board not fresh: {len(TRACK_REG)} tracks present, continuing on top")

    # in-memory rip; final save happens after routing

# ---- 2. collect net pad positions (B-side pads for THT, F for SMD) --------
net_pads = {}
for fp in board.GetFootprints():
    for p in fp.Pads():
        net = str(p.GetNetname())
        if not net:
            continue
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            lay = "F" if p.IsOnLayer(pcbnew.F_Cu) else "B"
        else:
            lay = "THT"
        net_pads.setdefault(net, []).append(
            (fp.GetReference() + "." + p.GetNumber(),
             p.GetPosition().x / mm, p.GetPosition().y / mm, lay))

# ---- 3. grid router -------------------------------------------------------
def _short(name):
    return name.split("/")[-1]

SRC = {}

def build(layer, route_net, route_w):
    rn = _short(route_net)
    g = [[False] * W for _ in range(H)]
    gtrk = [[False] * W for _ in range(H)]
    pl = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    for t in TRACK_REG:
        if t.GetClass() == "PCB_VIA":
            if _short(str(t.GetNetname())) == rn:
                continue
            for gx, gy in cells_of(t.GetPosition().x / mm, t.GetPosition().y / mm,
                                   0.35 + route_w / 2 + 0.36):
                g[gy][gx] = True
                gtrk[gy][gx] = True
            continue
        if t.GetLayer() != pl or _short(str(t.GetNetname())) == rn:
            continue
        n = int(max(abs(t.GetEnd().x - t.GetStart().x), abs(t.GetEnd().y - t.GetStart().y)) / mm / 0.05) + 1
        for i in range(n + 1):
            tt = i / n
            cx = (t.GetStart().x + (t.GetEnd().x - t.GetStart().x) * tt) / mm
            cy = (t.GetStart().y + (t.GetEnd().y - t.GetStart().y) * tt) / mm
            for gx, gy in cells_of(cx, cy, t.GetWidth() / mm / 2 + route_w / 2 + 0.36):
                g[gy][gx] = True
                gtrk[gy][gx] = True
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if _short(str(p.GetNetname())) == rn or not p.IsOnLayer(pl):
                continue
            bb = p.GetBoundingBox()
            pad = route_w / 2 + 0.26
            for gy in range(max(0, int((bb.GetTop() / mm - pad - Y0) / STEP)),
                            min(H, int((bb.GetBottom() / mm + pad - Y0) / STEP) + 1)):
                for gx in range(max(0, int((bb.GetLeft() / mm - pad - X0) / STEP)),
                                min(W, int((bb.GetRight() / mm + pad - X0) / STEP) + 1)):
                    g[gy][gx] = True
    m = int((0.3 + route_w / 2 + 0.15) / STEP)
    for gy in range(H):
        for gx in range(W):
            if gx < m or gx >= W - m or gy < m or gy >= H - m:
                g[gy][gx] = True
                gtrk[gy][gx] = True
                SRC.setdefault((gx, gy), "EDGE")
    return g, gtrk

def cells_of(x, y, r):
    x0, x1 = int((x - r - X0) / STEP), int((x + r - X0) / STEP) + 1
    y0, y1 = int((y - r - Y0) / STEP), int((y + r - Y0) / STEP) + 1
    for gy in range(max(0, y0), min(H, y1)):
        for gx in range(max(0, x0), min(W, x1)):
            cx, cy = X0 + gx * STEP, Y0 + gy * STEP
            if (cx - x) ** 2 + (cy - y) ** 2 <= r * r:
                yield gx, gy

def cell(x, y):
    return int((x - X0) / STEP), int((y - Y0) / STEP)

def bfs(g, gtrk, start, goal):
    """Grid BFS. Goal entry allowed only when the cell is free or blocked by
    pads alone (never by tracks/vias/edge) — avoids crossing existing copper.
    Returns (path, mode): mode 'reached' (path ends at goal cell),
    'tail' (path ends adjacent to goal; caller adds short tail to pad center)
    or raises SystemExit when unreachable within bounds."""
    prev = {start: None}
    q = deque([start])
    while q:
        c = q.popleft()
        if c == goal:
            break
        x, y = c
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in prev or not (0 <= n[0] < W and 0 <= n[1] < H):
                continue
            if not g[n[1]][n[0]]:
                prev[n] = c
                q.append(n)
            elif n == goal and not gtrk[n[1]][n[0]]:
                prev[n] = c
                q.append(n)
    if goal in prev:
        end, mode = goal, "reached"
    else:
        cand = [c for c in prev
                if abs(c[0] - goal[0]) + abs(c[1] - goal[1]) == 1]
        if not cand:
            best = min(prev.keys(), key=lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1]))
            raise SystemExit(
                f"no path ->({goal}); closest ({X0 + best[0] * STEP:.2f},{Y0 + best[1] * STEP:.2f})")
        end, mode = min(cand, key=lambda c: (abs(c[0] - goal[0]) + abs(c[1] - goal[1]),
                                             abs(c[0] - start[0]) + abs(c[1] - start[1]))), "tail"
    path, c = [], end
    while c:
        path.append(c)
        c = prev[c]
    return path[::-1], mode

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

def route_net(netname, layer, width_mm, pads):
    """pads: list of (x,y); connects pad1-pad2-...-padN sequentially"""
    g, gtrk = build(layer, netname, width_mm)
    segs = []
    pts = [cell(*pad) for pad in pads]
    for a, b, bp in zip(pts, pts[1:], pads[1:]):
        path, mode = bfs(g, gtrk, a, b)
        for c in path:
            SRC.setdefault(c, "OWN")
        segs.extend(to_segments(path))
        lx, ly = X0 + path[-1][0] * STEP, Y0 + path[-1][1] * STEP
        if mode == "tail" or (lx, ly) != bp:
            segs.append(((lx, ly), bp))
        SRC.setdefault(b, "OWN")
    for (x1, y1), (x2, y2) in segs:
        add_seg(x1, y1, x2, y2, netname, width_mm, layer)
    print(f"{netname}: {len(pads)} pads, {len(segs)} segments on {layer}.Cu")

def add_seg(x1, y1, x2, y2, netname, width_mm, layer):
    t = pcbnew.PCB_TRACK(board)
    net = nets[netname.split("/")[-1]]
    t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
    t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
    t.SetWidth(int(width_mm * mm))
    t.SetLayer(pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu)
    t.SetNet(net)
    board.Add(t)
    TRACK_REG.append(t)

def add_via(x, y, netname):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(int(x * mm), int(y * mm)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(int(0.7 * mm))
    v.SetDrill(int(0.3 * mm))
    v.SetNet(nets[netname])
    board.Add(v)
    TRACK_REG.append(v)

if __name__ == "__main__":
    rip_all()
    order = ["/Power Supply/+12V", "/Power Supply/-12V",
             "/Power Supply/+5V_EURO", "VBUS", "/Power Supply/VIN_BUCK",
             "/Power Supply/VOUT_PRE", "/Power Supply/SW",
             "IO2", "IO18", "IO19", "IO9", "IO15", "IO20", "IO22",
             "IO0", "IO1", "IO4", "IO5", "IO6", "IO7", "IO10", "IO11",
             "U0TXD", "U0RXD",
             "/USB & UART Bridge/USB_DP", "/USB & UART Bridge/USB_DM",
             "/USB & UART Bridge/CC1", "/USB & UART Bridge/CC2", "EN",
             "/Power Supply/FB", "/Power Supply/BOOT", "+5V", "+3V3", "IO8"]
    failed = []
    # Route deepest-reach nets first: their corridors are longest and most
    # constrained; short nets can still flex around them afterwards.
    def _ymax(nm):
        ps = net_pads.get(nm) or next((v for k, v in net_pads.items()
                                       if k.split("/")[-1] == nm.split("/")[-1]), [])
        return max((p[2] for p in ps), default=0)
    head, mid, tail = [], [], []
    for i, nm in enumerate(order):
        (mid if (nm.startswith("IO") or nm.startswith("U0")) else (head if i < 7 else tail)).append(nm)
    mid.sort(key=lambda nm: -_ymax(nm))
    order = head + mid + tail
    print("route order:", [n.split("/")[-1] for n in order])
    for netname in order:
        pads = net_pads.get(netname)
        if pads is None:
            _sn = netname.split("/")[-1]
            pads = next((v for k, v in net_pads.items()
                         if k.split("/")[-1] == _sn), [])
        if len(pads) < 2:
            print(f"{netname}: {len(pads)} pad(s), skipping")
            continue
        pts = [(x, y) for _r, x, y, _l in pads]
        # chain order: sort along the dominant axis
        if max(x for _, x, _y in [(0, p[0], p[1]) for p in pts]) - min(x for _, x, _y in [(0, p[0], p[1]) for p in pts]) >= \
           max(p[1] for p in pts) - min(p[1] for p in pts):
            pts.sort()
        else:
            pts.sort(key=lambda p: p[1])
        w = 0.5 if netname in POWER_NETS else 0.2
        try:
            route_net(netname, "F", w, pts)
        except SystemExit:
            try:
                route_net(netname, "B", w, pts)
                print(f"{netname}: F failed, routed on B")
            except SystemExit as e:
                print(f"{netname}: FAILED {e}")
                failed.append(netname)
    if failed:
        print("FAILED NETS:", failed)
    # stitching vias (GND) — safe to add now, no Remove ever happens
    gnd = nets["GND"]
    for (x, y) in [(63.0, 51.2), (66.0, 51.2), (72.5, 51.2), (89.3, 51.2),
                   (64.0, 71.6), (68.0, 71.6), (71.8, 71.6)]:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(int(x * mm), int(y * mm)))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetWidth(int(0.7 * mm))
        v.SetDrill(int(0.3 * mm))
        v.SetNet(gnd)
        board.Add(v)
        TRACK_REG.append(v)
    pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
    print("saved")
