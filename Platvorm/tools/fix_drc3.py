#!/usr/bin/env python3
"""Phase 3: footprint pad fixes + offset GND vias + component stitching.

Component stitcher: for each net with multiple true copper components,
A*-bridge the two largest components through their own copper cells.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR
from collections import deque

F, B = pcbnew.F_Cu, pcbnew.B_Cu
NM = 1000000
BOARD = sys.argv[1]
board = pcbnew.LoadBoard(BOARD)
pads = json.load(open("analysis/helpers/pads_api.json"))
net_pads = DR.build_net_pads(pads)


def pad_of(ref, num):
    fp = pads["footprints"][ref]
    return fp, [p for p in fp["pads"] if str(p["num"]) == str(num)][0]


# ---------- 1. J3 footprint pad fixes ----------
j3 = [f for f in board.GetFootprints() if f.GetReference() == "J3"][0]
for p in j3.Pads():
    num = p.GetNumber()
    if num in ("A4B9", "B4A9", "A1B12", "B1A12"):
        p.DeletePrimitivesList()
        p.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
        p.SetSize(pcbnew.VECTOR2I(int(0.5 * NM), int(1.3 * NM)))
        print(f"[3] J3 {num}: -> RECT 0.5x1.3")
    if num == "" and int(p.GetAttribute()) == 0:
        p.SetDrillSize(pcbnew.VECTOR2I(int(0.5 * NM), int(0.35 * NM)))
        print("[3] J3 shell: drill 0.5x0.35")

# ---------- 2. offset GND vias for C1.2 / C3.2 ----------
def build_router():
    r = R.Router(pads)
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            li = 0 if t.GetLayer() == F else 1
            r.block_track(li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net)
            r.placed_tracks.append((li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net))
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition(); r.block_via(p.x / NM, p.y / NM)
            r.vias.append((p.x / NM, p.y / NM, net))
    DR.mark_static_vias(r)
    return r


r = build_router()
netcode_gnd = board.FindNet("GND")

def add_gnd_drop(pad, vx, vy):
    li = 0
    npads = net_pads.get("GND", [])
    snap = DR.unblock_net(r, "GND", npads)
    ok = DR.seg_clear(r, li, pad["x"], pad["y"], vx, vy)
    i, j = r.cell(vx, vy)
    via_ok = r.inb(i, j) and all(r.g[l2]["via"][j * r.nx + i] == 0 and
                                 (not hasattr(r, "viastat") or r.viastat[l2][j * r.nx + i] == 0)
                                 for l2 in (0, 1))
    DR.reblock_net(r, "GND", npads, snap)
    if not (ok and via_ok):
        print(f"[3] !! GND drop at ({vx},{vy}) blocked (seg={ok} via={via_ok})")
        return
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(vx, vy))
    t.SetWidth(int(0.45 * NM)); t.SetLayer(F)
    t.SetNet(netcode_gnd); board.Add(t)
    v = pcbnew.PCB_VIA(board)
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetPosition(R.V(vx, vy))
    v.SetWidth(int(0.6 * NM)); v.SetDrill(int(0.3 * NM))
    v.SetNet(netcode_gnd); board.Add(v)
    r.block_track(0, pad["x"], pad["y"], vx, vy, 0.45, "GND")
    r.block_via(vx, vy)
    print(f"[3] GND drop -> via ({vx},{vy})")

fp, c12 = pad_of("C1", "2")
add_gnd_drop(c12, 64.4, 94.4)
fp, c32 = pad_of("C3", "2")
add_gnd_drop(c32, 78.55, 94.4)

# ---------- 3. U4.4 <-> FB1.2 (+3V3) A* bridge ----------
def bridge_pads(net, refA, numA, refB, numB):
    npads = net_pads.get(net, [])
    ea = [t for t in npads if t[0] == refA and str(t[2]["num"]) == str(numA)]
    eb = [t for t in npads if t[0] == refB and str(t[2]["num"]) == str(numB)]
    if not ea or not eb:
        print(f"[3] !! lookup {refA}.{numA}/{refB}.{numB}")
        return False
    snap = DR.unblock_net(r, net, npads)
    starts = DR.pad_core_cells(r, ea[0][2], ea[0][1])
    goals = DR.pad_core_cells(r, eb[0][2], eb[0][1])
    for (ci, cj, cli) in r.net_cells.get(net, ()):
        starts.setdefault(cli, set()).add((ci, cj))
    path = None
    for wtry in DR.width_chain(net):
        path = r.route(wtry, starts, goals, bmult=1.0)
        if path is not None:
            break
    ok = False
    if path:
        r.emit(path, wtry, net, board, None, None)
        print(f"[3] bridged {net}: {refA}.{numA} <-> {refB}.{numB}")
        ok = True
    else:
        print(f"[3] !! no path {net}: {refA}.{numA} <-> {refB}.{numB}")
    DR.reblock_net(r, net, npads, snap)
    return ok

bridge_pads("+3V3", "U4", "4", "FB1", "2")

# ---------- 4. U1 escapes for stuck GPIO ----------
def u1_escape(net, num):
    fp, pad = pad_of("U1", num)
    ex = pad["x"] - 1.8
    npads = net_pads.get(net, [])
    snap = DR.unblock_net(r, net, npads)
    ok1 = DR.seg_clear(r, 0, pad["x"], pad["y"], ex, pad["y"])
    i, j = r.cell(ex, pad["y"])
    ok2 = r.inb(i, j) and all(r.g[l2]["via"][j * r.nx + i] == 0 for l2 in (0, 1))
    DR.reblock_net(r, net, npads, snap)
    if not (ok1 and ok2):
        print(f"[3] !! U1.{num} escape blocked")
        return
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(ex, pad["y"]))
    t.SetWidth(int(0.2 * NM)); t.SetLayer(F)
    t.SetNet(board.FindNet(net)); board.Add(t)
    v = pcbnew.PCB_VIA(board)
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetPosition(R.V(ex, pad["y"]))
    v.SetWidth(int(0.6 * NM)); v.SetDrill(int(0.3 * NM))
    v.SetNet(board.FindNet(net)); board.Add(v)
    r.block_track(0, pad["x"], pad["y"], ex, pad["y"], 0.2, net)
    r.block_via(ex, pad["y"])
    print(f"[3] U1.{num} escape + via ({ex:.2f},{pad['y']:.2f})")

for (net, num) in (("IO19", "17"), ("IO21", "19"), ("IO4", "4")):
    u1_escape(net, num)
for (net, ra, na, rb, nb) in (("IO19", "U1", "17", "J2", "18"),
                               ("IO21", "U1", "19", "J2", "20"),
                               ("IO4", "U1", "4", "J2", "7"),
                               ("IO11", "U1", "12", "J2", "12")):
    bridge_pads(net, ra, na, rb, nb)

pcbnew.SaveBoard(BOARD, board)
print("[3] phase3 saved")
