#!/usr/bin/env python3
"""Two-layer negotiated-congestion router (PathFinder-style).
Hard blocks: other nets' pads (+edge margin). Other nets' tracks/vias are
SOFT: proximity cost + occupancy cost + accumulated history. Iterations raise
penalties until no cell is shared. Never calls board.Remove (swig corrupts)."""
import os
import heapq
from collections import defaultdict
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
mm = 1e6
STEP = 0.1
X0, Y0, X1, Y1 = 50.0, 50.0, 90.3, 130.0
W, H = int((X1 - X0) / STEP), int((Y1 - Y0) / STEP)
VIA_COST = 45
POWER_NETS = {"+12V", "+12V_RAW", "+3V3", "+5V", "+5V_EURO", "-12V",
              "-12V_RAW", "VBUS", "VIN_BUCK", "VOUT_PRE", "SW"}
ORDER = ["/Power Supply/+12V", "/Power Supply/-12V",
         "/Power Supply/+5V_EURO", "VBUS", "/Power Supply/VIN_BUCK",
         "/Power Supply/VOUT_PRE", "/Power Supply/SW",
         "IO22", "IO20", "IO15", "IO19", "IO18", "IO11", "IO10", "IO9",
         "IO7", "IO6", "IO5", "IO4", "IO2", "IO1", "IO0",
         "U0TXD", "U0RXD",
         "/USB & UART Bridge/USB_DP", "/USB & UART Bridge/USB_DM",
         "/USB & UART Bridge/CC1", "/USB & UART Bridge/CC2", "EN",
         "/Power Supply/FB", "/Power Supply/BOOT", "+5V", "+3V3", "IO8"]
MAX_ITER = 24

board = pcbnew.LoadBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"))
nets = {str(name).split("/")[-1]: n for name, n in board.GetNetsByName().items()}
TRACK_REG = []

def _short(x):
    return str(x).split("/")[-1]

def cell(x, y):
    return int((x - X0) / STEP), int((y - Y0) / STEP)

PADBB = []
for fp in board.GetFootprints():
    for p in fp.Pads():
        net = _short(p.GetNetname())
        if not net:
            continue
        bb = p.GetBoundingBox()
        PADBB.append((net,
                      {0 if l == pcbnew.F_Cu else 1
                       for l in (pcbnew.F_Cu, pcbnew.B_Cu) if p.IsOnLayer(l)},
                      max(0, int((bb.GetLeft() / mm - 0.26 - X0) / STEP)),
                      max(0, int((bb.GetTop() / mm - 0.26 - Y0) / STEP)),
                      min(W - 1, int((bb.GetRight() / mm + 0.26 - X0) / STEP)),
                      min(H - 1, int((bb.GetBottom() / mm + 0.26 - Y0) / STEP))))

OWN = defaultdict(dict)
for net, layers, x0, y0, x1, y1 in PADBB:
    d = OWN[net]
    for gx in range(x0, x1 + 1):
        for gy in range(y0, y1 + 1):
            d[(gx, gy)] = layers

def pad_grid(route_net, width_mm):
    hard = [[[False] * W for _ in range(H)] for _ in range(2)]
    extra = width_mm / 2
    for net, layers, x0, y0, x1, y1 in PADBB:
        if net == _short(route_net):
            continue
        ex0 = max(0, int((x0 * STEP - extra) / STEP))
        ex1 = min(W - 1, int((x1 * STEP + extra) / STEP))
        ey0 = max(0, int((y0 * STEP - extra) / STEP))
        ey1 = min(H - 1, int((y1 * STEP + extra) / STEP))
        for l in layers:
            for gy in range(ey0, ey1 + 1):
                row = hard[l][gy]
                for gx in range(ex0, ex1 + 1):
                    row[gx] = True
    m = int((0.3 + width_mm / 2 + 0.15) / STEP)
    for l in range(2):
        for gy in range(H):
            row = hard[l][gy]
            for gx in range(W):
                if gx < m or gx >= W - m or gy < m or gy >= H - m:
                    row[gx] = True
    return hard

NET_W = {}  # net -> route width (mm), filled in main

def build_prox(occ):
    """Cost field: entering a cell within the clearance radius of another
    net's copper is expensive. Radius depends on the occupant's width:
    0.5mm power needs 0.71mm center distance (8 cells) to worst-case
    neighbors; 0.2mm signals need 0.41mm (4 cells). Vias need ~0.65mm (7).
    Near-zone cost == occupancy cost: a clearance violation is as bad as
    an overlap, so the optimizer trades them identically."""
    prox = {0: defaultdict(int), 1: defaultdict(int)}
    for l in (0, 1):
        via_c, wide_c, sig_c = set(), set(), set()
        for c, s in occ[l].items():
            if not s:
                continue
            if occ[1 - l].get(c):
                via_c.add(c)
            elif max(NET_W.get(n, 0.2) for n in s) > 0.3:
                wide_c.add(c)
            else:
                sig_c.add(c)
        stamps = [(via_c, 43, 81), (wide_c, 64, 100), (sig_c, 16, 36)]
        near_v, mid_v = 50000, 2000
        costs = (near_v, mid_v)
        for (cells, d2_near, d2_mid), (cnear, cmid) in zip(stamps, [costs] * 3):
            for gx, gy in cells:
                for dx in range(-10, 11):
                    for dy in range(-10, 11):
                        d2 = dx * dx + dy * dy
                        if d2 == 0:
                            continue
                        if d2 <= d2_near:
                            val = cnear
                        elif d2 <= d2_mid:
                            val = cmid
                        else:
                            continue
                        c = (gx + dx, gy + dy)
                        if val > prox[l][c]:
                            prox[l][c] = val
    return prox

def route(netname, width_mm, pads, occ, hist, k, prox):
    rn = _short(netname)
    hard = pad_grid(netname, width_mm)

    def occ_cost(l, c):
        s = occ[l].get(c)
        if s:
            others = len(s) - (1 if rn in s else 0)
            if others > 0:
                return 6000 * k + hist[l].get(c, 0)
        return prox[l].get(c, 0) * k + hist[l].get(c, 0)

    pts = [(cell(x, y)[0], cell(x, y)[1], tht) for x, y, tht in pads]
    state_paths = []
    prev_state = None
    for gx, gy, tht in pts:
        layers = (0, 1) if tht else (OWN[rn].get((gx, gy)) or (0, 1))
        goal_states = {(gx, gy, l) for l in layers}
        if prev_state is None:
            prev_state = (gx, gy, sorted(layers)[0])
            state_paths.append([prev_state])
            continue
        dist = {prev_state: 0}
        back = {}
        pq = [(0, prev_state)]
        done = None
        while pq:
            d, s = heapq.heappop(pq)
            if d != dist.get(s):
                continue
            if s in goal_states and d > 0:
                done = s
                break
            x, y, l = s
            succ = []
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and (not hard[l][ny][nx]
                                                    or (nx, ny, l) in goal_states):
                    succ.append(((nx, ny, l), 1))
            nl = 1 - l
            if not hard[nl][y][x] or (x, y, nl) in goal_states:
                succ.append(((x, y, nl), VIA_COST))
            for ns, w_ in succ:
                c = d + w_ + occ_cost(ns[2], (ns[0], ns[1]))
                if c < dist.get(ns, 1 << 30):
                    dist[ns] = c
                    back[ns] = s
                    heapq.heappush(pq, (c, ns))
        if done is None:
            return None
        path, s = [], done
        while s is not None:
            path.append(s)
            s = back.get(s)
        path.reverse()
        state_paths.append(path)
        prev_state = done
    full = []
    for pth in state_paths:
        if full and pth and full[-1] == pth[0]:
            full.extend(pth[1:])
        else:
            full.extend(pth)
    # collapse same-cell layer sandwiches (F,B,F at one cell = pointless vias)
    out = []
    for s in full:
        if len(out) >= 2 and out[-1][0] == s[0] and out[-1][1] == s[1] \
                and out[-2][0] == s[0] and out[-2][1] == s[1] and out[-2][2] == s[2]:
            out.pop()  # drop the middle-layer detour
        else:
            out.append(s)
    return out

COMMIT_COUNT = [0]
def path_segments(path, width_mm, netname):
    net = nets[_short(netname)]
    runs = []
    cur = [path[0]]
    layer_name = {0: "F", 1: "B"}
    for s in path[1:]:
        if s[2] == cur[-1][2]:
            cur.append(s)
        else:
            runs.append(cur)
            cur = [s]
    runs.append(cur)
    for run in runs:
        l = run[0][2]
        pts = [(X0 + gx * STEP, Y0 + gy * STEP) for gx, gy, _ in run]
        keep = [pts[0]]
        for i in range(1, len(pts) - 1):
            ax, ay = keep[-1]
            bx, by = pts[i]
            cx, cy = pts[i + 1]
            if (bx - ax, by - ay) != (cx - bx, cy - by):
                keep.append(pts[i])
        keep.append(pts[-1])
        for (x1, y1), (x2, y2) in zip(keep, keep[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(int(x1 * mm), int(y1 * mm)))
            t.SetEnd(pcbnew.VECTOR2I(int(x2 * mm), int(y2 * mm)))
            t.SetWidth(int(width_mm * mm))
            t.SetLayer(pcbnew.F_Cu if l == 0 else pcbnew.B_Cu)
            t.SetNet(net)
            board.Add(t)
            TRACK_REG.append(t)
            COMMIT_COUNT[0] += 1
    for a, b in zip(runs, runs[1:]):
        gx, gy, _ = b[0]
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(int((X0 + gx * STEP) * mm),
                                      int((Y0 + gy * STEP) * mm)))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetWidth(int(0.7 * mm))
        v.SetDrill(int(0.3 * mm))
        v.SetNet(net)
        board.Add(v)
        TRACK_REG.append(v)

def path_segments__orig(routed):
    import pcbnew as pn
    from collections import defaultdict as dd
    # capture what the commit ACTUALLY adds, per net
    real = dd(set)
    orig_add = pcbnew.BOARD.Add
    tracking = {'net': None}
    class Watch:
        pass
    for nm, (path, w) in routed.items():
        want = nets[_short(nm)]
        mycells = set()
        # replicate commit
        runs = []
        cur = [path[0]]
        for st in path[1:]:
            if st[2] == cur[-1][2]:
                cur.append(st)
            else:
                runs.append(cur); cur = [st]
        runs.append(cur)
        for run in runs:
            l = run[0][2]
            pts2 = [(50 + gx * 0.1, 50 + gy * 0.1) for gx, gy, _ in run]
            keep = [pts2[0]]
            for i in range(1, len(pts2) - 1):
                ax, ay = keep[-1]; bx, by = pts2[i]; cx2, cy2 = pts2[i + 1]
                if (bx - ax, by - ay) != (cx2 - bx, cy2 - by):
                    keep.append(pts2[i])
            keep.append(pts2[-1])
            for (axx, ayy), (bxx, byy) in zip(keep, keep[1:]):
                n2 = int(max(abs(bxx - axx), abs(byy - ayy)) / 0.05) + 1
                for i2 in range(n2 + 1):
                    tt = i2 / n2
                    mycells.add((l, int((axx + (bxx - axx) * tt - 50) / 0.1 + 1e-9),
                                    int((ayy + (byy - ayy) * tt - 50) / 0.1 + 1e-9)))
        for a2, b2 in zip(runs, runs[1:]):
            mycells.add((0, b2[0][0], b2[0][1])); mycells.add((1, b2[0][0], b2[0][1]))
        real[_short(nm)] |= mycells
    for nm2, (path, w) in routed.items():
        path_segments(path, w, nm2)

def main():
    import sys
    if len(sys.argv) > 1:
        global ORDER
        ORDER = [n for n in sys.argv[1].split(',')]
    net_pads = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            net = str(p.GetNetname())
            if not net:
                continue
            tht = p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD
            net_pads.setdefault(_short(net), []).append(
                (p.GetPosition().x / mm, p.GetPosition().y / mm, tht))

    order = [n for n in ORDER if _short(n) in net_pads
             and len(net_pads[_short(n)]) >= 2]
    routed = {}
    for nm in order:
        NET_W[_short(nm)] = 0.5 if _short(nm) in POWER_NETS else 0.2
    occ = {0: defaultdict(set), 1: defaultdict(set)}
    hard_others = len(sys.argv) > 2 and sys.argv[2] == "hard"
    if hard_others:
        # existing board copper becomes a HARD block for the routed nets
        for t in board.GetTracks():
            nl = 0 if t.GetLayer() == pcbnew.F_Cu else 1
            if t.GetClass() == "PCB_VIA":
                cells = {(int(t.GetPosition().x / mm / 0.1), int(t.GetPosition().y / mm / 0.1))}
                for l in (0, 1):
                    for c2 in cells:
                        occ[l][c2].add(_short(t.GetNetname()) + "~")
            else:
                x1, y1 = t.GetStart().x / mm, t.GetStart().y / mm
                x2, y2 = t.GetEnd().x / mm, t.GetEnd().y / mm
                n2 = int(max(abs(x2 - x1), abs(y2 - y1)) / 0.05) + 1
                for i2 in range(n2 + 1):
                    tt = i2 / n2
                    occ[nl][(int((x1 + (x2 - x1) * tt) / 0.1),
                             int((y1 + (y2 - y1) * tt) / 0.1))].add(
                        _short(t.GetNetname()) + "~")
    hist = {0: defaultdict(int), 1: defaultdict(int)}

    for it in range(MAX_ITER):
        prox = build_prox(occ)          # from previous iteration's occupancy
        occ[0].clear(); occ[1].clear()
        bad = 0
        for nm in order:
            pads = net_pads[_short(nm)]
            xs = [p[0] for p in pads]; ys = [p[1] for p in pads]
            pads = sorted(pads) if max(xs) - min(xs) >= max(ys) - min(ys) \
                else sorted(pads, key=lambda p: p[1])
            w = 0.5 if _short(nm) in POWER_NETS else 0.2
            path = route(nm, w, pads, occ, hist, it + 1, prox)
            if path is None:
                bad += 1
                continue
            routed[_short(nm)] = (path, w)
            for i, (gx, gy, l) in enumerate(path):
                occ[l][(gx, gy)].add(_short(nm))
                if i > 0 and path[i - 1][2] != l:
                    occ[0][(gx, gy)].add(_short(nm))
                    occ[1][(gx, gy)].add(_short(nm))
        def near_hits(l, c, w):
            """cells within clearance radius of c holding another net"""
            rad2 = 64 if w > 0.3 else 16
            hits = 0
            for dx in range(-8, 9):
                for dy in range(-8, 8):
                    d2 = dx * dx + dy * dy
                    if d2 == 0 or d2 > rad2:
                        continue
                    s2 = occ[l].get((c[0] + dx, c[1] + dy))
                    if s2 and (len(s2) > 1 or any(n not in s2 for n in s2)):
                        hits += 1
            return hits
        conflicts = sum(1 for l in (0, 1) for s in occ[l].values() if len(s) > 1)
        near_total = 0
        for l in (0, 1):
            for c, s in occ[l].items():
                w = max(NET_W.get(n, 0.2) for n in s)
                near_total += near_hits(l, c, w)
        print(f"iter {it}: conflicts={conflicts} near={near_total} no-path={bad}", flush=True)
        if conflicts == 0 and bad == 0:
            break
        for l in (0, 1):
            for c, s in occ[l].items():
                w = max(NET_W.get(n, 0.2) for n in s)
                if len(s) > 1:
                    hist[l][c] += 200
                elif near_hits(l, c, w):
                    hist[l][c] += 40

    from collections import defaultdict as dd
    pocc = dd(set)
    for nm2, (p2, w2) in routed.items():
        for i2, (gx2, gy2, l2) in enumerate(p2):
            pocc[(l2, gx2, gy2)].add(nm2)
            if i2 > 0 and p2[i2-1][2] != l2:
                pocc[(0, gx2, gy2)].add(nm2); pocc[(1, gx2, gy2)].add(nm2)
    pbad = {k: v for k, v in pocc.items() if len(v) > 1}
    print('PATH-CELL OVERLAPS:', len(pbad))
    for l in (0, 1):
        for c, s3 in occ[l].items():
            if len(s3) > 1 and {'+3V3', 'IO1'} <= set(s3):
                print(f"OCC-CONFLICT +3V3xIO1 at ({c[0]},{c[1]}) l={l}")
    for target in ('+3V3', 'IO1'):
        p2 = routed.get(target)
        if p2:
            near = [(gx, gy, l) for gx, gy, l in p2[0] if 330 <= gx <= 340 and 170 <= gy <= 190]
            print(f"{target} cells near (335,180): {len(near)}", near[:8])
    from collections import defaultdict as dd2
    chk = dd2(set)
    for nm2, (p2, w2) in routed.items():
        for i2, (gx2, gy2, l2) in enumerate(p2):
            chk[(l2, gx2, gy2)].add(nm2)
            if i2 > 0 and p2[i2-1][2] != l2:
                chk[(0, gx2, gy2)].add(nm2); chk[(1, gx2, gy2)].add(nm2)
    print("chk (1,335,180):", chk[(1, 335, 180)], " chk (1,335,179):", chk[(1, 335, 179)])
    missing = [n for n in order if _short(n) not in routed]
    if missing:
        print("FAILED NETS:", missing)
    for l in (0, 1):
        for c, s2 in occ[l].items():
            if len(s2) > 1:
                print(f"CONFLICT {'F' if l == 0 else 'B'} "
                      f"({X0 + c[0] * STEP:.2f},{Y0 + c[1] * STEP:.2f}): {sorted(s2)}")
    from collections import defaultdict as dd
    gocc = dd(set)
    for nm, (path, w) in routed.items():
        pcells = {(l, gx, gy) for gx, gy, l in path}
        for i, (gx, gy, l) in enumerate(path):
            if i > 0 and path[i-1][2] != l:
                pcells.add((0, gx, gy)); pcells.add((1, gx, gy))
        # simulate commit
        ccells = set()
        runs = []
        cur = [path[0]]
        for st in path[1:]:
            if st[2] == cur[-1][2]:
                cur.append(st)
            else:
                runs.append(cur); cur = [st]
        runs.append(cur)
        for run in runs:
            l = run[0][2]
            pts2 = [(gx, gy) for gx, gy, _ in run]
            keep = [pts2[0]]
            for i in range(1, len(pts2) - 1):
                ax, ay = keep[-1]; bx, by = pts2[i]; cx2, cy2 = pts2[i + 1]
                if (bx - ax, by - ay) != (cx2 - bx, cy2 - by):
                    keep.append(pts2[i])
            keep.append(pts2[-1])
            for (axx, ayy), (bxx, byy) in zip(keep, keep[1:]):
                n2 = int(max(abs(bxx - axx), abs(byy - ayy)) / 0.05) + 1
                for i2 in range(n2 + 1):
                    tt = i2 / n2
                    ccells.add((l, int(axx + (bxx - axx) * tt + 1e-9),
                                int(ayy + (byy - ayy) * tt + 1e-9)))
        for a2, b2 in zip(runs, runs[1:]):
            ccells.add((0, b2[0][0], b2[0][1])); ccells.add((1, b2[0][0], b2[0][1]))
        extra = ccells - pcells
        if extra:
            print(f"{nm}: commit cells outside path: {len(extra)} sample={list(extra)[:3]}")
        for c2 in ccells:
            gocc[c2].add(nm)
    gbad = {k: v for k, v in gocc.items() if len(v) > 1}
    print("SIMULATED COMMIT OVERLAPS:", len(gbad))
    path_segments__orig(routed)
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
        COMMIT_COUNT[0] += 1
    print("COMMITTED SEGMENTS+VIAS:", COMMIT_COUNT[0])
    pcbnew.SaveBoard(os.path.join(PRJ, "Platvorm.kicad_pcb"), board)
    print("saved")

if __name__ == "__main__":
    main()
