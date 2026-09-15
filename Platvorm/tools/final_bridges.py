#!/usr/bin/env python3
"""Final surgical bridges: hand-verified paths + GND via spots + GPIO escapes."""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"
DM = "/USB & UART Bridge/USB_DM"
DP = "/USB & UART Bridge/USB_DP"

# (net, layer, width, waypoints) — start/end land on pad centers or stub ends
BRIDGES = [
    # DP: A6 stub end -> link east -> down to U3.4 (also closes A6 into net)
    (DP, F, 0.2, [(69.6, 121.11), (69.9, 121.11), (69.9, 117.26), (68.45, 117.26)]),
    # VBUS: A4B9 stub end -> south lane under U3/C10 halos -> up to C10 stub end
    ("VBUS", F, 0.2, [(67.5, 121.01), (67.5, 119.5), (61.9, 119.5), (61.9, 122.75), (61.5, 122.75)]),
    # CC1: A5 stub end -> shared lane y120.55 -> into R7.1 center
    ("/USB & UART Bridge/CC1", F, 0.2,
     [(68.65, 121.26), (68.65, 120.55), (76.2, 120.55), (76.2, 121.75), (76.99, 121.75), (76.99, 123.0)]),
    # CC2: B5 stub end -> lower lane y120.15 -> under R8 into R8.1 center
    ("/USB & UART Bridge/CC2", F, 0.2,
     [(71.575, 121.26), (71.575, 120.15), (76.2, 120.15), (76.2, 119.3), (76.99, 119.3), (76.99, 120.4)]),
    # FB: U2.4 up through pin window -> west lane -> up to R1.1
    ("/Power Supply/FB", F, 0.2, [(65.55, 90.94), (65.55, 89.8), (64.2, 89.8), (64.2, 86.0), (68.49, 86.0)]),
    # BOOT: C7.1 escape end -> pin-window lane y89.8 -> into U2.6
    ("/Power Supply/BOOT", F, 0.2, [(61.22, 91.9), (61.22, 89.8), (67.45, 89.8), (67.45, 90.94)]),
]

# GND pads without vias: (ref, num, via_x, via_y) — via south of pad
GND_VIAS = [
    ("C1", "2", 64.3, 94.8),
    ("C3", "2", 78.55, 94.2),
    ("U3", "2", 67.2, 120.5),
]

# GPIO nets needing J2/U1 escapes post-hoc
GPIO_ESCAPES = [
    ("IO10", "J2", "11"),
    ("IO15", "J2", "13"),
    ("IO23", "J2", "22"),
    ("IO11", "U1", "12"),
]


def replay(board, pads):
    r = R.Router(pads)
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            li = 0 if t.GetLayer() == F else 1
            r.block_track(li, s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6, t.GetWidth() / 1e6, net)
            r.placed_tracks.append((li, s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6, t.GetWidth() / 1e6, net))
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition(); r.block_via(p.x / 1e6, p.y / 1e6)
            r.vias.append((p.x / 1e6, p.y / 1e6, net))
    return r


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    net_pads = DR.build_net_pads(pads)
    r = replay(board, pads)
    DR.mark_static_vias(r)

    for (net, lay, w, pts) in BRIDGES:
        npads = net_pads.get(net, [])
        if not npads:
            continue
        snap = DR.unblock_net(r, net, npads)
        li = 0 if lay == F else 1
        ok = all(DR.seg_clear(r, li, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
        if not ok:
            print(f"  !! bridge {net} {pts[0]}->{pts[-1]} blocked")
            DR.reblock_net(r, net, npads, snap)
            continue
        netcode = board.FindNet(net)
        for a, b2 in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(a[0], a[1])); t.SetEnd(R.V(b2[0], b2[1]))
            t.SetWidth(int(w * 1e6)); t.SetLayer(lay)
            t.SetNet(netcode); board.Add(t)
            r.block_track(li, a[0], a[1], b2[0], b2[1], w, net)
        print(f"  bridged {net}: {pts[0]} -> {pts[-1]}")
        DR.reblock_net(r, net, npads, snap)

    for (ref, num, vx, vy) in GND_VIAS:
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if p["num"] == num][0]
        i, j = r.cell(vx, vy)
        if not (all(r.g[l2]["via"][j * r.nx + i] == 0 for l2 in (0, 1)) and
                all(r.viastat[l2][j * r.nx + i] == 0 for l2 in (0, 1))):
            print(f"  !! {ref}.{num} via spot ({vx},{vy}) blocked")
            continue
        if not DR.seg_clear(r, 0, pad["x"], pad["y"], vx, vy):
            print(f"  !! {ref}.{num} stub blocked")
            continue
        netcode = board.FindNet("GND")
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(vx, vy))
        t.SetWidth(int(0.45 * 1e6)); t.SetLayer(F)
        t.SetNet(netcode); board.Add(t)
        v = pcbnew.PCB_VIA(board)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetPosition(R.V(vx, vy))
        v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
        v.SetNet(netcode); board.Add(v)
        print(f"  GND {ref}.{num}: stub+via at ({vx},{vy})")

    # GPIO escapes: J2 pins outward on B (try both sides), U1.12 west+via
    for (net, ref, num) in GPIO_ESCAPES:
        npads = net_pads.get(net, [])
        if not npads:
            continue
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if str(p["num"]) == str(num)][0]
        snap = DR.unblock_net(r, net, npads)
        done = False
        if ref == "J2":
            for sgn in (1, -1):
                ex = pad["x"] + sgn * 2.0
                if DR.seg_clear(r, 1, pad["x"], pad["y"], ex, pad["y"]):
                    netcode = board.FindNet(net)
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(ex, pad["y"]))
                    t.SetWidth(int(0.2 * 1e6)); t.SetLayer(B)
                    t.SetNet(netcode); board.Add(t)
                    r.block_track(1, pad["x"], pad["y"], ex, pad["y"], 0.2, net)
                    print(f"  escape {net} {ref}.{num} -> ({ex:.2f},{pad['y']:.2f}) on B")
                    done = True
                    break
        else:  # U1 west tip + via
            ex = pad["x"] - 1.5
            if DR.seg_clear(r, 0, pad["x"], pad["y"], ex, pad["y"]) and DR.via_clear(r, ex, pad["y"]):
                netcode = board.FindNet(net)
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(ex, pad["y"]))
                t.SetWidth(int(0.2 * 1e6)); t.SetLayer(F)
                t.SetNet(netcode); board.Add(t)
                r.block_track(0, pad["x"], pad["y"], ex, pad["y"], 0.2, net)
                v = pcbnew.PCB_VIA(board)
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetPosition(R.V(ex, pad["y"]))
                v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
                v.SetNet(netcode); board.Add(v)
                r.block_via(ex, pad["y"])
                print(f"  escape {net} {ref}.{num} -> via ({ex:.2f},{pad['y']:.2f})")
                done = True
        if not done:
            print(f"  !! escape {net} {ref}.{num} failed")
        # A* completion from escape to net
        starts = DR.pad_core_cells(r, pad, fp)
        for (ci, cj, cli) in r.net_cells.get(net, ()):
            starts.setdefault(cli, set()).add((ci, cj))
        goals = {}
        for c in npads:
            if c[2] is pad:
                continue
            for li2, cells in DR.pad_core_cells(r, c[2], c[1]).items():
                goals.setdefault(li2, set()).update(cells)
        path = None
        for wtry in DR.width_chain(net):
            path = r.route(wtry, starts, goals, bmult=0.5)
            if path is not None:
                break
        if path:
            r.emit(path, wtry, net, board, None, None)
            print(f"  completed {net} {ref}.{num}")
        else:
            print(f"  !! completion failed {net} {ref}.{num}")
        DR.reblock_net(r, net, npads, snap)

    pcbnew.SaveBoard(BOARD, board)
    print("saved")


if __name__ == "__main__":
    main()
