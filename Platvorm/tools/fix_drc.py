#!/usr/bin/env python3
"""DRC fix v2: full rip + coordinated re-route of the J3-area nets.

Single LoadBoard (avoids swig wrapper corruption from reload cycles).
1. Rip DM/DP/CC1/CC2/VBUS/FB/BOOT completely; re-place pad-row stubs.
2. route_net each in dependency-friendly order (A* over clean south area).
3. GND via-in-pad for C1.2/C3.2/U3.2; U4.4 stub (L-path).
4. Rip+re-bridge the 9 stuck GPIO nets and the SW/VOUT_PRE gaps.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
NM = 1000000
BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
DM = "/USB & UART Bridge/USB_DM"
DP = "/USB & UART Bridge/USB_DP"
CC1 = "/USB & UART Bridge/CC1"
CC2 = "/USB & UART Bridge/CC2"

board = pcbnew.LoadBoard(BOARD)
pads = json.load(open("analysis/helpers/pads_api.json"))
net_pads = DR.build_net_pads(pads)

STUBS = [  # (net, pad ref, pad num, end x, end y)
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
    ("/Power Supply/BOOT", "C7", "1", 61.22, 91.9),
    ("VBUS", "D1", "2", 60.8, 119.8),
    (CC1, "R7", "1", 76.99, 125.2),
    (CC2, "R8", "1", 76.99, 118.6),
    ("/Power Supply/FB", "R2", "1", 70.69, 84.2),
]


def pad_of(ref, num):
    fp = pads["footprints"][ref]
    return fp, [p for p in fp["pads"] if str(p["num"]) == str(num)][0]


ALL_TRACKS = [t for t in board.GetTracks()]   # captured once: wrappers stay valid
DEAD = set()


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


def iter_alive():
    for t in ALL_TRACKS:
        if id(t) not in DEAD:
            try:
                yield t
            except Exception:
                pass


def fresh_router():
    r = R.Router(pads)
    for t in iter_alive():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            li = 0 if t.GetLayer() == F else 1
            r.block_track(li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net)
            r.placed_tracks.append((li, s.x / NM, s.y / NM, e.x / NM, e.y / NM, t.GetWidth() / NM, net))
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition(); r.block_via(p.x / NM, p.y / NM)
            r.vias.append((p.x / NM, p.y / NM, net))
    # newly added tracks this session (added via board.Add in this script)
    for t in NEW_TRACKS:
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


NEW_TRACKS = []


def main():
    # ---- 1. rip the tangled nets ----
    for net in (DM, DP, CC1, CC2, "VBUS", "/Power Supply/FB", "/Power Supply/BOOT"):
        print(f"[1] rip {net}: {remove_net(net)} items")

    r = fresh_router()

    # ---- 2. re-place pad-row stubs ----
    DIRECT_STUBS = {  # hand-verified geometry; grid margin cannot model these
        (CC1, "J3", "A5"): True,   # 0.25 to B8/A6 edges
        (CC2, "J3", "B5"): True,   # 0.25 to B6/B4A9
        (DP, "J3", "A6"): True,    # 0.25 to B7/B6
        (DP, "J3", "B6"): True,    # 0.25 to A6/A7
        (DM, "J3", "A7"): True,    # 0.25 to B6/B8... to B6/A8
        (DM, "J3", "B7"): True,    # 0.275/0.225 to A5/A6
        ("/Power Supply/FB", "U2", "4"): True,  # pin window + VIN via: 0.334 to ring
    }
    for (net, ref, num, ex, ey) in STUBS:
        fp, pad = pad_of(ref, num)
        npads = net_pads.get(net, [])
        snap = DR.unblock_net(r, net, npads)
        li = 0
        if not DR.seg_clear(r, li, pad["x"], pad["y"], ex, ey) and not DIRECT_STUBS.get((net, ref, num)):
            print(f"[2] !! stub {ref}.{num} blocked")
        else:
            netcode = board.FindNet(net)
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(ex, ey))
            t.SetWidth(int(0.2 * NM)); t.SetLayer(F)
            t.SetNet(netcode); board.Add(t)
            NEW_TRACKS.append(t)
            r.block_track(0, pad["x"], pad["y"], ex, ey, 0.2, net)
            print(f"[2] stub {ref}.{num} -> ({ex},{ey})")
        DR.reblock_net(r, net, npads, snap)

    # ---- 3. route each net fully (A*) ----
    for net in ("VBUS", DM, DP, CC1, CC2, "/Power Supply/FB", "/Power Supply/BOOT"):
        npads = net_pads.get(net, [])
        if not npads:
            continue
        ok, fails = DR.route_net(r, board, net, npads)
        print(f"[3] {net}: {ok}/{len(npads)} {fails}")

    pcbnew.SaveBoard(BOARD, board)
    print("phase A saved")

    # ---- 4. GND via-in-pad + U4.4 stub ----
    for (ref, num) in (("C1", "2"), ("C3", "2"), ("U3", "2")):
        fp, pad = pad_of(ref, num)
        netcode = board.FindNet("GND")
        v = pcbnew.PCB_VIA(board)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetPosition(R.V(pad["x"], pad["y"]))
        v.SetWidth(int(0.6 * NM)); v.SetDrill(int(0.3 * NM))
        v.SetNet(netcode); board.Add(v)
        print(f"[4] GND via-in-pad {ref}.{num}")

    # U4.4 -> +3V3 via at (66.555,109.1125): L-path candidates
    fp, pad4 = pad_of("U4", "4")
    cands = [
        [(pad4["x"], pad4["y"]), (pad4["x"], 116.2), (66.555, 116.2), (66.555, 109.1125)],
        [(pad4["x"], pad4["y"]), (pad4["x"], 115.5), (66.555, 115.5), (66.555, 109.1125)],
        [(pad4["x"], pad4["y"]), (69.0, pad4["y"]), (69.0, 116.2), (66.555, 116.2), (66.555, 109.1125)],
    ]
    pts = None
    for cand in cands:
        if all(DR.seg_clear(r, 0, p[0], p[1], q[0], q[1]) for p, q in zip(cand, cand[1:])):
            pts = cand
            break
    npads = net_pads.get("+3V3", [])
    snap = DR.unblock_net(r, "+3V3", npads)
    ok = pts is not None
    if ok:
        netcode = board.FindNet("+3V3")
        for p, q in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(p[0], p[1])); t.SetEnd(R.V(q[0], q[1]))
            t.SetWidth(int(0.45 * NM)); t.SetLayer(F)
            t.SetNet(netcode); board.Add(t)
            NEW_TRACKS.append(t)
            r.block_track(0, p[0], p[1], q[0], q[1], 0.45, "+3V3")
        print("[4] U4.4 +3V3 stub placed")
    else:
        print("[4] !! U4.4 stub blocked")
    DR.reblock_net(r, "+3V3", npads, snap)

    # ---- 5. GPIO fragments rip + pad-pair bridges ----
    GPIO = ["IO7", "IO10", "IO11", "IO15", "IO18", "IO19", "IO21", "IO22", "IO23"]
    ripped = 0
    for t in list(iter_alive()):
        if t.GetNetname() in GPIO and t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            if math.hypot(e.x - s.x, e.y - s.y) / NM < 0.35:
                board.Remove(t); DEAD.add(id(t)); ripped += 1
    print(f"[5] ripped {ripped} GPIO fragments")

    # SW / VOUT_PRE violating segments rip
    for t in list(iter_alive()):
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        s, e = t.GetStart(), t.GetEnd()
        mx, my = (s.x + e.x) / 2 / NM, (s.y + e.y) / 2 / NM
        if t.GetNetname() == "/Power Supply/SW" and (
                (abs(mx - 64.275) < 0.2 and abs(my - 91.725) < 0.25) or
                (abs(mx - 68.425) < 0.4 and abs(my - 90.225) < 0.4)):
            board.Remove(t); DEAD.add(id(t))
        if t.GetNetname() == "/Power Supply/VOUT_PRE" and abs(mx - 69.625) < 0.25 and abs(my - 86.175) < 0.25:
            board.Remove(t); DEAD.add(id(t))

    # un-mark ripped fragments from the live router state
    for t in [t for t in ALL_TRACKS]:
        pass  # fragment unmarking handled by forget-style clear below

    import router as _R
    for net in GPIO:
        r.forget_net(net)
    r.forget_net("/Power Supply/SW")
    r.forget_net("/Power Supply/VOUT_PRE")

    def bridge(net, refA, numA, refB, numB):
        npads = net_pads.get(net, [])
        ea = [t for t in npads if t[0] == refA and str(t[2]["num"]) == str(numA)]
        eb = [t for t in npads if t[0] == refB and str(t[2]["num"]) == str(numB)]
        if not ea or not eb:
            print(f"[5] !! pad lookup {refA}.{numA}/{refB}.{numB}")
            return
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
        if path:
            r.emit(path, wtry, net, board, {"x": ea[0][2]["x"], "y": ea[0][2]["y"]},
                   {"x": eb[0][2]["x"], "y": eb[0][2]["y"]})
            print(f"[5] bridged {net}: {refA}.{numA} <-> {refB}.{numB}")
        else:
            print(f"[5] !! no path {net}: {refA}.{numA} <-> {refB}.{numB}")
        DR.reblock_net(r, net, npads, snap)

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
            before = len([v for v in r.vias])  # cheap progress signal
            ok = [None]
            def try_bridge(job=job, ok=ok):
                net, ra, na, rb, nb = job
                npads = net_pads.get(net, [])
                ea = [t for t in npads if t[0] == ra and str(t[2]["num"]) == str(na)]
                eb = [t for t in npads if t[0] == rb and str(t[2]["num"]) == str(nb)]
                if not ea or not eb:
                    return
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
                if path:
                    r.emit(path, wtry, net, board, {"x": ea[0][2]["x"], "y": ea[0][2]["y"]},
                           {"x": eb[0][2]["x"], "y": eb[0][2]["y"]})
                    print(f"[5] bridged {net}: {ra}.{na} <-> {rb}.{nb} (r{rnd})")
                    ok[0] = True
                DR.reblock_net(r, net, npads, snap)
            try_bridge()
            if not ok[0]:
                still.append(job)
        pending = still

    for (net, ra, na, rb, nb) in [
        ("/Power Supply/SW", "U2", "2", "L1", "1"),
        ("/Power Supply/SW", "L1", "1", "C7", "2"),
        ("/Power Supply/VOUT_PRE", "L1", "2", "C3", "1"),
        ("/Power Supply/VOUT_PRE", "L1", "2", "R1", "2"),
    ]:
        bridge(net, ra, na, rb, nb)

    pcbnew.SaveBoard(BOARD, board)
    print("saved")


if __name__ == "__main__":
    main()
