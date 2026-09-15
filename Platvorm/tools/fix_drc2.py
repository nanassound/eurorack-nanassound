#!/usr/bin/env python3
"""DRC fix — two-phase (each phase its own process: fresh, complete grids).

P1: rip tangled nets, place escapes, route them (A*).
P2: via-in-pads (validated on ALL layers), GPIO/power bridges.

usage: fix_drc2.py <board> P1|P2
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
NM = 1000000
BOARD = sys.argv[1]
PHASE = sys.argv[2]
DM = "/USB & UART Bridge/USB_DM"
DP = "/USB & UART Bridge/USB_DP"
CC1 = "/USB & UART Bridge/CC1"
CC2 = "/USB & UART Bridge/CC2"

board = pcbnew.LoadBoard(BOARD)
pads = json.load(open("analysis/helpers/pads_api.json"))
net_pads = DR.build_net_pads(pads)
ALL_TRACKS = [t for t in board.GetTracks()]
DEAD = set()

STUBS = [
    ("VBUS", "J3", "A4B9", 67.5, 121.01),
    ("VBUS", "J3", "B4A9", 72.3, 121.01),
    (CC1, "J3", "A5", 68.65, 121.26),
    (CC2, "J3", "B5", 71.65, 121.26),
    (DP, "J3", "A6", 69.65, 121.11),
    (DP, "J3", "B6", 70.65, 121.11),
    (DM, "J3", "A7", 70.15, 121.86),
    (DM, "J3", "B7", 69.15, 121.86),
    ("VBUS", "C10", "1", 61.5, 122.75),
    ("/Power Supply/FB", "U2", "4", 65.55, 89.8),
    ("/Power Supply/FB", "R1", "1", 68.49, 84.2),
    ("/Power Supply/FB", "R2", "1", 70.69, 84.2),
    ("/Power Supply/BOOT", "C7", "1", 61.22, 91.9),
    ("VBUS", "D1", "2", 60.8, 119.8),
    (CC1, "R7", "1", 76.99, 125.2),
    (CC2, "R8", "1", 76.99, 118.6),
]
DIRECT = {(CC1, "J3", "A5"), (CC2, "J3", "B5"), (DP, "J3", "A6"), (DP, "J3", "B6"),
          (DM, "J3", "A7"), (DM, "J3", "B7"), ("/Power Supply/FB", "U2", "4")}

RIP_NETS = [DM, DP, CC1, CC2, "VBUS", "/Power Supply/FB", "/Power Supply/BOOT",
            "IO7", "IO10", "IO11", "IO15", "IO18", "IO19", "IO21", "IO22", "IO23",
            "/Power Supply/SW", "/Power Supply/VOUT_PRE"]


def iter_alive():
    for t in ALL_TRACKS:
        if id(t) not in DEAD:
            yield t


def remove_net(net):
    n = 0
    for t in ALL_TRACKS:
        if id(t) in DEAD:
            continue
        try:
            if t.GetNetname() == net:
                board.Remove(t); DEAD.add(id(t)); n += 1
        except Exception:
            DEAD.add(id(t))
    return n


def build_router(extra_tracks=()):
    r = R.Router(pads)
    src = list(iter_alive()) + list(extra_tracks)
    for t in src:
        try:
            net = t.GetNetname()
            if t.Type() == pcbnew.PCB_TRACE_T:
                s, e = t.GetStart(), t.GetEnd()
                li = 0 if t.GetLayer() == F else 1
                r.block_track(li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net)
                r.placed_tracks.append((li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net))
            elif t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition(); r.block_via(p.x / NM, p.y / NM)
                r.vias.append((p.x / NM, p.y / NM, net))
        except Exception:
            pass
    DR.mark_static_vias(r)
    return r


def pad_of(ref, num):
    fp = pads["footprints"][ref]
    return fp, [p for p in fp["pads"] if str(p["num"]) == str(num)][0]


def add_track(net, lay, w, pts):
    netcode = board.FindNet(net)
    li = 0 if lay == F else 1
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(R.V(pts[0][0], pts[0][1])); t.SetEnd(R.V(pts[1][0], pts[1][1]))
    t.SetWidth(int(w * NM)); t.SetLayer(lay)
    t.SetNet(netcode); board.Add(t)
    return t


def p1():
    for net in RIP_NETS:
        print(f"[P1] rip {net}: {remove_net(net)}")
    r = build_router()
    # stubs
    for (net, ref, num, ex, ey) in STUBS:
        fp, pad = pad_of(ref, num)
        npads = net_pads.get(net, [])
        snap = DR.unblock_net(r, net, npads)
        if (net, ref, num) not in DIRECT and not DR.seg_clear(r, 0, pad["x"], pad["y"], ex, ey):
            print(f"[P1] !! stub {ref}.{num} blocked")
        else:
            t = add_track(net, F, 0.2, [(pad["x"], pad["y"]), (ex, ey)])
            r.block_track(0, pad["x"], pad["y"], ex, ey, 0.2, net)
            print(f"[P1] stub {ref}.{num} -> ({ex},{ey})")
        DR.reblock_net(r, net, npads, snap)
    # route
    for net in ("VBUS", DM, DP, CC1, CC2, "/Power Supply/FB", "/Power Supply/BOOT"):
        npads = net_pads.get(net, [])
        if not npads:
            continue
        ok, fails = DR.route_net(r, board, net, npads)
        print(f"[P1] route {net}: {ok}/{len(npads)} {fails}")
    pcbnew.SaveBoard(BOARD, board)
    print("P1 saved")


def p2():
    r = build_router()  # fresh process: sees ALL copper from P1
    # via-in-pad GND drops, validated against all copper on all layers
    def via_spot_free(x, y):
        i, j = r.cell(x, y)
        if not r.inb(i, j):
            return False
        for li in (0, 1):
            if r.g[li]["via"][j * r.nx + i]:
                return False
        if hasattr(r, "viastat"):
            for li in (0, 1):
                if r.viastat[li][j * r.nx + i]:
                    return False
        # own pad region is expected blocked by its own pad mark: allow if the
        # only blocker is the pad itself (distance to pad center < 1mm)
        return True

    for (ref, num) in (("C1", "2"), ("C3", "2"), ("U3", "2")):
        fp, pad = pad_of(ref, num)
        if not via_spot_free(pad["x"], pad["y"]):
            # check if blocked by tracks (not just own pad): probe B tracks near
            conflict = False
            for (li, x1, y1, x2, y2, w, n2) in r.placed_tracks:
                if n2 == "GND":
                    continue
                dx, dy = x2 - x1, y2 - y1
                L2 = dx * dx + dy * dy
                tt = 0 if L2 == 0 else max(0, min(1, ((pad["x"] - x1) * dx + (pad["y"] - y1) * dy) / L2))
                d = math.hypot(pad["x"] - (x1 + tt * dx), pad["y"] - (y1 + tt * dy))
                if d < w / 2 + 0.5:
                    conflict = True
                    print(f"[P2] !! {ref}.{num} via-in-pad conflicts {n2} track (d={d:.2f})")
                    break
            if not conflict:
                for (vx, vy, n2) in r.vias:
                    if n2 != "GND" and math.hypot(pad["x"] - vx, pad["y"] - vy) < 1.1:
                        conflict = True
                        print(f"[P2] !! {ref}.{num} via-in-pad conflicts via {n2}")
                        break
            if conflict:
                continue
        netcode = board.FindNet("GND")
        v = pcbnew.PCB_VIA(board)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetPosition(R.V(pad["x"], pad["y"]))
        v.SetWidth(int(0.6 * NM)); v.SetDrill(int(0.3 * NM))
        v.SetNet(netcode); board.Add(v)
        print(f"[P2] GND via-in-pad {ref}.{num}")

    # U4.4 +3V3 stub candidates
    fp, pad4 = pad_of("U4", "4")
    cands = [
        [(pad4["x"], pad4["y"]), (pad4["x"], 116.2), (66.555, 116.2), (66.555, 109.1125)],
        [(pad4["x"], pad4["y"]), (pad4["x"], 115.5), (66.555, 115.5), (66.555, 109.1125)],
        [(pad4["x"], pad4["y"]), (69.0, pad4["y"]), (69.0, 116.2), (66.555, 116.2), (66.555, 109.1125)],
    ]
    npads = net_pads.get("+3V3", [])
    snap = DR.unblock_net(r, "+3V3", npads)
    placed_u4 = False
    for cand in cands:
        if all(DR.seg_clear(r, 0, p[0], p[1], q[0], q[1]) for p, q in zip(cand, cand[1:])):
            for p, q in zip(cand, cand[1:]):
                t = add_track("+3V3", F, 0.45, [p, q])
                r.block_track(0, p[0], p[1], q[0], q[1], 0.45, "+3V3")
            print("[P2] U4.4 +3V3 stub placed")
            placed_u4 = True
            break
    if not placed_u4:
        print("[P2] !! U4.4 stub blocked")
    DR.reblock_net(r, "+3V3", npads, snap)

    # GPIO + power bridges (grid = ALL copper)
    def bridge(net, refA, numA, refB, numB, tag=""):
        npads = net_pads.get(net, [])
        ea = [t for t in npads if t[0] == refA and str(t[2]["num"]) == str(numA)]
        eb = [t for t in npads if t[0] == refB and str(t[2]["num"]) == str(numB)]
        if not ea or not eb:
            print(f"[P2] !! pad lookup {refA}.{numA}/{refB}.{numB}")
            return False
        snap = DR.unblock_net(r, net, npads)
        starts = DR.pad_core_cells(r, ea[0][2], ea[0][1])
        goals = DR.pad_core_cells(r, eb[0][2], eb[0][1])
        for (ci, cj, cli) in r.net_cells.get(net, ()):
            starts.setdefault(cli, set()).add((ci, cj))
        path = None
        for wtry in DR.width_chain(net):
            path = r.route(wtry, starts, goals, bmult=0.7)
            if path is not None:
                break
        ok = False
        if path:
            r.emit(path, wtry, net, board, None, None)
            print(f"[P2] bridged {net}: {refA}.{numA} <-> {refB}.{numB}{tag}")
            ok = True
        else:
            print(f"[P2] !! no path {net}: {refA}.{numA} <-> {refB}.{numB}")
        DR.reblock_net(r, net, npads, snap)
        return ok

    GPIO_JOBS = [
        ("IO15", "U1", "23", "J2", "13"),
        ("IO19", "U1", "17", "J2", "18"),
        ("IO22", "U1", "20", "J2", "21"),
        ("IO23", "U1", "21", "J2", "22"),
        ("IO7", "U1", "7", "J2", "10"),
        ("IO10", "U1", "11", "J2", "11"),
        ("IO11", "U1", "12", "J2", "12"),
        ("IO18", "U1", "16", "J2", "17"),
        ("IO21", "U1", "19", "J2", "20"),
    ]
    pending = list(GPIO_JOBS)
    for rnd in range(3):
        if not pending:
            break
        still = []
        for job in pending:
            if not bridge(*job, tag=f" (r{rnd})"):
                still.append(job)
        pending = still

    for job in [
        ("/Power Supply/SW", "U2", "2", "L1", "1"),
        ("/Power Supply/SW", "L1", "1", "C7", "2"),
        ("/Power Supply/VOUT_PRE", "L1", "2", "C3", "1"),
        ("/Power Supply/VOUT_PRE", "L1", "2", "R1", "2"),
    ]:
        bridge(*job)

    pcbnew.SaveBoard(BOARD, board)
    print("P2 saved")


if PHASE == "P1":
    p1()
else:
    p2()
