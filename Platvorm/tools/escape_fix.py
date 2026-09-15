#!/usr/bin/env python3
"""Deterministic escape stubs for pads the generic router can't escape,
then A* completes from the stub end to the net's existing copper.

Run under KiCad python after drive_route.py.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
W = 0.2

# net -> (ref, padnum, [relative waypoints], via_after, layer)
# waypoints are offsets (dx,dy) from pad center; orthogonal legs implied.
ESCAPES = [
    ("/Power Supply/SW", "C7", "2", [(-1.5, 0), (0, 0)], False, F),
    ("/Power Supply/SW", "L1", "1", [(0, -2.5), (0, 0)], False, F),
    ("/Power Supply/FB", "R2", "1", [(0, -1.8), (0, 0)], False, F),
]


def seg_cells(r, x1, y1, x2, y2):
    n = int(math.hypot(x2 - x1, y2 - y1) / (R.GRID / 2)) + 1
    for k in range(n + 1):
        t = k / n
        yield r.cell(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)


def stub_ok(r, li, cls, x1, y1, x2, y2):
    g = r.g[li][cls]
    for (i, j) in seg_cells(r, x1, y1, x2, y2):
        if not r.inb(i, j):
            return False
        if g[j * r.nx + i]:
            return False
    return True


def via_spot_ok(r, x, y):
    i, j = r.cell(x, y)
    if not r.inb(i, j):
        return False
    return all(r.g[li]["via"][j * r.nx + i] == 0 for li in (0, 1))


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
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
    DR.mark_static_vias(r)
    net_pads = DR.build_net_pads(pads)

    still_failed = []
    for (net, ref, num, offs, via_after, lay0) in ESCAPES:
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if str(p["num"]) == num][0]
        px, py = pad["x"], pad["y"]
        # skip if net copper already reaches this pad
        reached = False
        for (li2, x1, y1, x2, y2, w2, n2) in r.placed_tracks:
            if n2 != net:
                continue
            for (qx, qy) in ((x1, y1), (x2, y2)):
                if math.hypot(qx - px, qy - py) < 0.45:
                    reached = True
                    break
            if reached:
                break
        if not reached:
            for (vx, vy, n2) in r.vias:
                if n2 == net and math.hypot(vx - px, vy - py) < 0.45:
                    reached = True
                    break
        if reached:
            print(f"  skip {net} {ref}.{num}: already connected")
            continue
        npads = net_pads[net]
        snap = DR.unblock_net(r, net, npads)
        cls = "sig"
        # stub legs through waypoints (any angle), each validated
        pts = [(px, py)] + [(px + ox, py + oy) for (ox, oy) in offs]
        legs = list(zip(pts, pts[1:]))
        ok = True
        shift = 0.0
        for attempt in range(9):  # lateral shifts to dodge foreign copper
            shift = [0.0, 0.1, -0.1, 0.2, -0.2, 0.3, -0.3, 0.45, -0.45][attempt]
            sx = shift if abs(offs[0][1]) >= abs(offs[0][0]) else 0.0
            sy = shift if abs(offs[0][0]) > abs(offs[0][1]) else 0.0
            ok = all(stub_ok(r, 0 if lay0 == F else 1, cls,
                             a[0] + sx, a[1] + sy, b[0] + sx, b[1] + sy) for (a, b) in legs)
            last = pts[-1]
            via_x, via_y = last[0] + sx, last[1] + sy
            if ok and via_after:
                ok = via_spot_ok(r, via_x, via_y)
            if ok:
                break
        if not ok:
            print(f"  !! {net} {ref}.{num}: stub blocked even with shifts")
            still_failed.append((net, f"{ref}.{num}"))
            DR.reblock_net(r, net, npads, snap)
            continue
        netcode = board.FindNet(net)
        li = 0 if lay0 == F else 1
        for ((a, b), (c, d)) in legs:
            if abs(a - c) < 1e-9 and abs(b - d) < 1e-9:
                continue
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(a + sx, b + sy)); t.SetEnd(R.V(c + sx, d + sy))
            t.SetWidth(int(W * 1e6)); t.SetLayer(lay0)
            t.SetNet(netcode); board.Add(t)
            r.block_track(li, a + sx, b + sy, c + sx, d + sy, W, net)
            r.placed_tracks.append((li, a + sx, b + sy, c + sx, d + sy, W, net))
        if via_after:
            v = pcbnew.PCB_VIA(board)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetPosition(R.V(via_x, via_y))
            v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
            v.SetNet(netcode); board.Add(v)
            r.block_via(via_x, via_y)
            r.vias.append((via_x, via_y, net))
        # A* from stub end (and via other side) to remaining net copper
        starts = {}
        if via_after:
            starts[0] = {r.cell(via_x, via_y)}
            starts[1] = {r.cell(via_x, via_y)}
        else:
            starts[li] = {r.cell(via_x, via_y)}
        for c in npads:
            if c[2] is pad:
                continue
            for li2, cells in DR.pad_core_cells(r, c[2], c[1]).items():
                starts.setdefault(li2, set()).update(cells)
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
        if path is None:
            print(f"  !! {net} {ref}.{num}: stub placed but A* completion failed")
            still_failed.append((net, f"{ref}.{num}"))
        else:
            r.emit(path, wtry, net, board, None, None)
            print(f"  ok {net} {ref}.{num}: escaped via ({via_x:.2f},{via_y:.2f})")
        DR.reblock_net(r, net, npads, snap)

    pcbnew.SaveBoard(BOARD, board)
    print("still failed:", still_failed if still_failed else "NONE")


if __name__ == "__main__":
    main()
