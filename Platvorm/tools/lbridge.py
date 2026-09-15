#!/usr/bin/env python3
"""Deterministic L-bridge finisher: pad-center to pad-center with corner search.

For each (net, padA, padB): try L/Z paths whose corner points are searched on
a coarse grid; validate every segment against foreign copper via the router
grids; emit with exact pad-center terminations.
"""
import sys, json, math, re, subprocess
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/drc_board.kicad_pcb"

# hand-picked bridge targets (net, refA, numA, refB, numB, layer)
BRIDGES = [
    ("/USB & UART Bridge/USB_DP", "J3", "A6", "J3", "B6", F),
    ("/USB & UART Bridge/USB_DP", "U3", "3", "J3", "B6", F),
    ("VBUS", "C10", "1", "J3", "A4B9", F),
    ("/Power Supply/FB", "U2", "4", "R1", "1", F),
    ("/Power Supply/BOOT", "C7", "1", "U2", "6", F),
    ("/USB & UART Bridge/CC1", "J3", "A5", "R7", "1", F),
    ("/USB & UART Bridge/CC2", "J3", "B5", "R8", "1", F),
    ("IO10", "U1", "11", "J2", "11", B),
    ("IO11", "U1", "12", "J2", "12", B),
    ("IO23", "U1", "21", "J2", "22", B),
    ("IO15", "U1", "23", "J2", "13", B),
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


def try_L(r, li, a, b, w):
    """Search L and Z (via one corner) paths; returns point list or None."""
    ax, ay = a; bx, by = b
    cands = []
    # L variants with corner offsets
    for ddx in (0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5):
        for ddy in (0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0):
            c1 = (ax + ddx, by + ddy)
            c2 = (bx + ddx, ay + ddy)
            cands.append([a, c1, b])
            cands.append([a, c2, b])
    # Z variants: out of a, across, into b
    for mid in (0.25, 0.5, 0.75):
        mx, my = ax + (bx - ax) * mid, ay + (by - ay) * mid
        for d in (0.8, -0.8, 1.6, -1.6):
            cands.append([a, (ax, my + d), (bx, my + d), b])
            cands.append([a, (mx + d, ay), (mx + d, by), b])
    for pts in cands:
        ok = True
        for p in pts:
            if not (r.x0 <= p[0] <= r.x1 and r.y0 <= p[1] <= r.y1):
                ok = False; break
        if not ok:
            continue
        if all(DR.seg_clear(r, li, p[0], p[1], q[0], q[1])
               for p, q in zip(pts, pts[1:])):
            return pts
    return None


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    net_pads = DR.build_net_pads(pads)
    r = replay(board, pads)
    DR.mark_static_vias(r)

    # dedupe: skip bridges where pads already connected (rough check: same-net
    # copper graph via endpoints) — just attempt all; seg validation prevents dups

    for (net, ra, na, rb, nb, lay) in BRIDGES:
        npads = net_pads.get(net)
        if not npads:
            continue
        ea = [t for t in npads if t[0] == ra and str(t[2]["num"]) == str(na)]
        eb = [t for t in npads if t[0] == rb and str(t[2]["num"]) == str(nb)]
        if not ea or not eb:
            print(f"  !! pad lookup {ra}.{na} or {rb}.{nb}")
            continue
        padA, padB = ea[0][2], eb[0][2]
        snap = DR.unblock_net(r, net, npads)
        li = 0 if lay == F else 1
        w = 0.2
        pts = try_L(r, li, (padA["x"], padA["y"]), (padB["x"], padB["y"]), w)
        if pts is None and (padA["attr"] == 0 or padB["attr"] == 0):
            # THT pads: try other layer too
            pts = try_L(r, 1 - li, (padA["x"], padA["y"]), (padB["x"], padB["y"]), w)
            if pts is not None:
                li = 1 - li
        if pts is None:
            print(f"  !! no L path {net}: {ra}.{na} <-> {rb}.{nb}")
            DR.reblock_net(r, net, npads, snap)
            continue
        netcode = board.FindNet(net)
        lay_real = F if li == 0 else B
        for p, q in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(p[0], p[1])); t.SetEnd(R.V(q[0], q[1]))
            t.SetWidth(int(w * 1e6)); t.SetLayer(lay_real)
            t.SetNet(netcode); board.Add(t)
            r.block_track(li, p[0], p[1], q[0], q[1], w, net)
        print(f"  bridged {net}: {ra}.{na} <-> {rb}.{nb} via {pts[1]} ({'F' if li==0 else 'B'})")
        DR.reblock_net(r, net, npads, snap)

    # GND C3.2 via (hand-validated spot south of the pad)
    for t in board.GetTracks():
        pass
    fp = pads["footprints"]["C3"]
    pad = [p for p in fp["pads"] if p["num"] == "2"][0]
    netcode = board.FindNet("GND")
    vx, vy = 78.55, 93.75
    i, j = r.cell(vx, vy)
    if all(r.g[l2]["via"][j * r.nx + i] == 0 for l2 in (0, 1)):
        tr = pcbnew.PCB_TRACK(board)
        tr.SetStart(R.V(pad["x"], pad["y"])); tr.SetEnd(R.V(vx, vy))
        tr.SetWidth(int(0.45 * 1e6)); tr.SetLayer(F)
        tr.SetNet(netcode); board.Add(tr)
        v = pcbnew.PCB_VIA(board)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetPosition(R.V(vx, vy))
        v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
        v.SetNet(netcode); board.Add(v)
        print("  C3.2 GND stub+via placed")
    else:
        print("  !! C3.2 via spot blocked")

    pcbnew.SaveBoard(BOARD, board)
    out = "/tmp/drc/lbridge.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json",
                    "-o", out, BOARD], capture_output=True, check=True)
    d = json.load(open(out))
    print("unconnected:", len(d.get("unconnected_items", [])))
    print("violations:", len(d.get("violations", [])))


if __name__ == "__main__":
    main()
