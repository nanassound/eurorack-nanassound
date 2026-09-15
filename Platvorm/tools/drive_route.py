#!/usr/bin/env python3
"""Driver: run router + via passes + fill on Platvorm.kicad_pcb (KiCad python)."""
import sys, json, math, os
sys.path.insert(0, "tools")
import pcbnew
import router as R

BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
F, B = pcbnew.F_Cu, pcbnew.B_Cu
DM = "/USB & UART Bridge/USB_DM"
DP = "/USB & UART Bridge/USB_DP"


def build_net_pads(pads):
    nets = {}
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            n = p["net"]
            if not n or n.startswith("unconnected"):
                continue
            nets.setdefault(n, []).append((ref, fp, p))
    return nets


def mark_static_vias(r):
    """Reuse router rect marker into dedicated static grids."""
    n = r.nx * r.ny
    r.viastat = [bytearray(n), bytearray(n)]
    inf = R.CLR + R.VIA_HALF + R.MARGIN
    for ref, fp in r.pads["footprints"].items():
        for p in fp["pads"]:
            w, h = R.aabb_pad(p)
            lays = (0, 1) if p["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
            for li in lays:
                # mark cells whose center is within pad aabb + inf
                i0, j0 = r.cell(p["x"] - w / 2 - inf, p["y"] - h / 2 - inf)
                i1, j1 = r.cell(p["x"] + w / 2 + inf, p["y"] + h / 2 + inf)
                for j in range(max(0, j0), min(r.ny, j1 + 1)):
                    for i in range(max(0, i0), min(r.nx, i1 + 1)):
                        x, y = r.xy(i, j)
                        if abs(x - p["x"]) <= w / 2 + inf and abs(y - p["y"]) <= h / 2 + inf:
                            r.viastat[li][j * r.nx + i] = 1


def via_free(r, x, y):
    i, j = r.cell(x, y)
    if not r.inb(i, j):
        return False
    for li in (0, 1):
        idx = j * r.nx + i
        if r.viastat[li][idx]:
            return False
        if r.g[li]["via"][idx]:
            return False
    return True


def unblock_net(r, net, net_pads):
    """Symmetric (refcount) unmark of own pads/tracks/vias.

    Returns the snapshot of shapes that were cleared; pass to reblock_net().
    Copper emitted AFTER this call keeps its own single mark (foreign-visible).
    """
    pre_tracks = [t for t in r.placed_tracks if t[6] == net]
    pre_vias = [v for v in r.vias if v[2] == net]
    for (ref, fp, p) in net_pads:
        w, h = R.aabb_pad(p)
        lays = (0, 1) if p["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
        for li in lays:
            r._mark_all_cls(li, "rect", (p["x"], p["y"]), (w, h), clear=True)
    for t in pre_tracks:
        r._mark_all_cls(t[0], "seg", (t[1], t[2], t[3], t[4]), t[5], clear=True)
    for (x, y, n) in pre_vias:
        for li in (0, 1):
            r._mark_all_cls(li, "rect", (x, y), (R.VIA_D, R.VIA_D), clear=True)
    return pre_tracks, pre_vias


def reblock_net(r, net, net_pads, snapshot=None):
    """Re-mark exactly what unblock_net cleared (pads + snapshot shapes)."""
    for (ref, fp, p) in net_pads:
        w, h = R.aabb_pad(p)
        lays = (0, 1) if p["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
        for li in lays:
            r._mark_all_cls(li, "rect", (p["x"], p["y"]), (w, h))
    if snapshot is None:
        return
    pre_tracks, pre_vias = snapshot
    for t in pre_tracks:
        r._mark_all_cls(t[0], "seg", (t[1], t[2], t[3], t[4]), t[5])
    for (x, y, n) in pre_vias:
        for li in (0, 1):
            r._mark_all_cls(li, "rect", (x, y), (R.VIA_D, R.VIA_D))


# PCB_PAD_Shape_t: 0 CIRCLE, 1 RECT, 2 OVAL, 3 TRAPEZOID, 4 ROUNDRECT, ...

def pad_core_cells(r, pad, fp):
    """Goal/start cells guaranteed inside true pad copper.

    Round THT pads (pin headers): AABB corners are NOT copper -> radial test.
    Roundrect/oval: shrink aggressively. Rect: shrink 0.05. Always include center.
    """
    w, h = R.aabb_pad(pad)
    cx, cy = pad["x"], pad["y"]
    shape = pad.get("shape", 1)
    lays = (0, 1) if pad["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
    out = {}
    for li in lays:
        cells = set()
        ci, cj = r.cell(cx, cy)
        if r.inb(ci, cj):
            cells.add((ci, cj))
        if shape == 0:  # circle: inscribed radius
            rad = min(w, h) / 2 - 0.05
            if rad > 0:
                i0, j0 = r.cell(cx - rad, cy - rad)
                i1, j1 = r.cell(cx + rad, cy + rad)
                for i in range(max(0, i0), min(r.nx, i1 + 1)):
                    for j in range(max(0, j0), min(r.ny, j1 + 1)):
                        x, y = r.xy(i, j)
                        if math.hypot(x - cx, y - cy) <= rad:
                            cells.add((i, j))
        else:
            shrink = 0.05 if shape in (1, 3) else min(w, h) / 4
            ww = max(w / 2 - shrink, 0.02)
            hh = max(h / 2 - shrink, 0.02)
            i0, j0 = r.cell(cx - ww, cy - hh)
            i1, j1 = r.cell(cx + ww, cy + hh)
            for i in range(max(0, i0), min(r.nx, i1 + 1)):
                for j in range(max(0, j0), min(r.ny, j1 + 1)):
                    cells.add((i, j))
        out[li] = cells
    return out


def width_chain(net):
    w = R.FAT_NETS.get(net, R.TRK_SIG)
    if w > R.TRK_SIG + 0.01:
        return [x for x in (w, 1.0, 0.8) if x <= w]  # power nets stay fat
    return [R.TRK_SIG, 0.2]


def route_net(r, board, net, net_pads, guide=None, bmult=1.0, avoid=False):
    width = R.FAT_NETS.get(net, R.TRK_SIG)
    remaining = list(net_pads)
    # start from pad nearest to net centroid
    cx = sum(p["x"] for _, _, p in remaining) / len(remaining)
    cy = sum(p["y"] for _, _, p in remaining) / len(remaining)
    remaining.sort(key=lambda t: math.hypot(t[2]["x"] - cx, t[2]["y"] - cy))
    connected = [remaining.pop(0)]
    fails = []
    snap = None
    try:
        while remaining:
        # nearest remaining pad to any connected pad
            best_i = min(range(len(remaining)),
                         key=lambda k: min(math.hypot(remaining[k][2]["x"] - c[2]["x"],
                                                      remaining[k][2]["y"] - c[2]["y"])
                                           for c in connected))
            tgt = remaining[best_i]
            snap = unblock_net(r, net, net_pads)
            starts = {}
            for c in connected:
                for li, cells in pad_core_cells(r, c[2], c[1]).items():
                    starts.setdefault(li, set()).update(cells)
            for (ci, cj, cli) in r.net_cells.get(net, ()):
                starts.setdefault(cli, set()).add((ci, cj))
            goals = pad_core_cells(r, tgt[2], tgt[1])
            path = None
            for wtry in width_chain(net):
                path = r.route(wtry, starts, goals, guide=guide, bmult=bmult, avoid=avoid)
                if path is not None:
                    width = wtry
                    break
            if path is None:
                fails.append(tgt[0] + "." + str(tgt[2]["num"]))
                remaining.pop(best_i)
                continue
            r.emit(path, width, net, board, None, {"x": tgt[2]["x"], "y": tgt[2]["y"]})
            connected.append(tgt)
            remaining.pop(best_i)
            reblock_net(r, net, net_pads, snap)
    finally:
        if snap is not None:
            reblock_net(r, net, net_pads, snap)
            snap = None
    if fails:
        print(f"  !! {net}: FAILED pads {fails}")
    return len(connected), fails




def remove_net_copper(board, net):
    for t in list(board.GetTracks()):
        if t.GetNetname() == net:
            board.Remove(t)


def connect_pad(r, board, net, net_pads, pad, fp):
    """Route a single pad into the net's existing copper (used by rip-up retry)."""
    snap = None
    try:
        snap = unblock_net(r, net, net_pads)
        others = [t for t in net_pads if t[2] is not pad]
        starts = {}
        for c in others:
            for li, cells in pad_core_cells(r, c[2], c[1]).items():
                starts.setdefault(li, set()).update(cells)
        for (ci, cj, cli) in r.net_cells.get(net, ()):
            starts.setdefault(cli, set()).add((ci, cj))
        goals = pad_core_cells(r, pad, fp)
        path = None
        for wtry in width_chain(net):
            path = r.route(wtry, starts, goals, bmult=0.5)
            if path is not None:
                r.emit(path, wtry, net, board, None, {"x": pad["x"], "y": pad["y"]})
                return 1, []
        return 0, [net + " pad"]
    finally:
        reblock_net(r, net, net_pads, snap)


# deterministic escapes placed BEFORE general routing, into known-free zones
ESCAPES = [
    # (net, ref, padnum, [offsets (dx,dy) from pad center], via_after, layer)
    ("IO23", "U1", "21", [(-1.8, 0)], True, F),
    ("IO10", "U1", "11", [(-1.5, 0)], True, F),
    ("IO15", "U1", "23", [(-1.8, 0)], True, F),
    ("IO18", "U1", "16", [(-1.8, 0)], True, F),
    ("IO7", "J2", "10", [(2.0, 0)], False, B),
    ("IO11", "J2", "12", [(2.0, 0)], False, B),
    ("IO19", "J2", "18", [(2.0, 0)], False, B),
    ("IO21", "J2", "20", [(2.0, 0)], False, B),
    ("IO22", "J2", "21", [(-2.0, 0)], False, B),
    ("/USB & UART Bridge/Q1B", "Q1", "1", [(2.2, 0)], True, F),
    ("/USB & UART Bridge/RTS", "Q1", "2", [(2.2, 0)], True, F),
    ("/USB & UART Bridge/Q2B", "Q2", "1", [(2.2, 0)], True, F),
    ("/Power Supply/BOOT", "C7", "1", [(-2.0, 0)], False, F),
    ("/USB & UART Bridge/CC1", "R7", "1", [(0, 2.2)], False, F),
    ("/USB & UART Bridge/CC2", "R8", "1", [(0, -1.8)], False, F),
    ("VBUS", "C10", "1", [(-1.9, 0)], False, F),
    # J3 mid-pad row tip escapes: single legs into verified halo corridors
    # (offsets are absolute from pad center; slight diagonal within own halo is fine)
    ("/USB & UART Bridge/USB_DM", "J3", "A7", [(0.025, -1.95)], False, F),
    ("/USB & UART Bridge/USB_DM", "J3", "B7", [(0.05, -1.95)], False, F),
    ("/USB & UART Bridge/USB_DP", "J3", "A6", [(-0.05, -2.7)], False, F),
    ("/USB & UART Bridge/USB_DP", "J3", "B6", [(0.05, -2.7)], False, F),
    ("/USB & UART Bridge/CC1", "J3", "A5", [(0, -2.55)], False, F),
    ("/USB & UART Bridge/CC2", "J3", "B5", [(-0.075, -2.55)], False, F),
    ("VBUS", "J3", "A4B9", [(0, -2.8)], False, F),
    ("VBUS", "J3", "B4A9", [(0, -2.8)], False, F),
]


def seg_clear(r, li, x1, y1, x2, y2):
    import math as _m
    n = int(_m.hypot(x2 - x1, y2 - y1) / 0.025) + 1
    g = r.g[li]["sig"]
    for k in range(n + 1):
        t = k / n
        i, j = r.cell(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        if not r.inb(i, j) or g[j * r.nx + i]:
            return False
    return True


def via_clear(r, x, y):
    i, j = r.cell(x, y)
    return r.inb(i, j) and all(r.g[li]["via"][j * r.nx + i] == 0 for li in (0, 1))


def place_escapes(r, board, pads, net_pads):
    for (net, ref, num, offs, via_after, lay) in ESCAPES:
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if str(p["num"]) == num][0]
        npads = net_pads.get(net, [])
        if not npads:
            continue
        snap = unblock_net(r, net, npads)
        li = 0 if lay == F else 1
        pts = [(pad["x"], pad["y"])] + [(pad["x"] + ox, pad["y"] + oy) for (ox, oy) in offs]
        ex, ey = pts[-1]
        ok = all(seg_clear(r, li, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
        if ok and via_after:
            ok = via_clear(r, ex, ey)
        if not ok:
            print(f"  escape pre-place failed {net} {ref}.{num}")
            reblock_net(r, net, npads, snap)
            continue
        netcode = board.FindNet(net)
        for a, bx in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(a[0], a[1])); t.SetEnd(R.V(bx[0], bx[1]))
            t.SetWidth(int(0.2 * 1e6)); t.SetLayer(lay)
            t.SetNet(netcode); board.Add(t)
            r.block_track(li, a[0], a[1], bx[0], bx[1], 0.2, net)
            r.placed_tracks.append((li, a[0], a[1], bx[0], bx[1], 0.2, net))
        if via_after:
            v = pcbnew.PCB_VIA(board)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetPosition(R.V(ex, ey))
            v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
            v.SetNet(netcode); board.Add(v)
            r.block_via(ex, ey)
            r.vias.append((ex, ey, net))
        reblock_net(r, net, npads)
        print(f"  escape {net} {ref}.{num} -> ({ex:.2f},{ey:.2f}){' +via' if via_after else ''}")

def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    r = R.Router(pads)
    mark_static_vias(r)
    net_pads = build_net_pads(pads)

    routed, failed = [], []
    place_escapes(r, board, pads, net_pads)
    todo = [n for n in R.ROUTE_ORDER if n in net_pads]
    rest = [n for n in net_pads
            if n not in todo and n not in ("GND", "+3V3")]
    # long nets first (span diagonal)
    def span(n):
        xs = [p["x"] for _, _, p in net_pads[n]]; ys = [p["y"] for _, _, p in net_pads[n]]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    rest.sort(key=span, reverse=True)
    todo += rest

    guide = None
    for net in todo:
        if net == DP and r.net_cells.get(DM):
            fields = r.dist_field({(i, j) for (i, j, li) in r.net_cells.get(DM, ())})
            guide = [bytearray(min(255, (f[i] - 6) * 15) if f[i] > 6 else 0 for i in range(len(f)))
                     for f in fields]
            print("  (DP coupling guide active)")
        sp = span(net)
        ok, fails = route_net(r, board, net, net_pads[net], guide=guide,
                              bmult=0.5 if sp > 25 else 1.0)
        guide = None
        routed.append(net)
        failed += [(net, f) for f in fails]
        print(f"routed {net}: {ok}/{len(net_pads[net])} pads")

    # ---- rip-up pass: disabled (destabilizing); enable with RIPUP=1 ----
    if os.environ.get("RIPUP"):
        for rnd in range(2):
            if not failed:
                break
            print(f"--- rip-up round {rnd+1}: {len(failed)} failures ---")
            still = []
            for (net, padstr) in failed:
                ref, num = padstr.rsplit(".", 1)
                fp = pads["footprints"][ref]
                pad = [p for p in fp["pads"] if str(p["num"]) == num][0]
                px, py = pad["x"], pad["y"]
                # find blocking nets: placed copper within 1.4mm of pad center
                blockers = {}
                for (li, x1, y1, x2, y2, w2, n2) in r.placed_tracks:
                    if n2 == net:
                        continue
                    import math as _m
                    dx, dy = x2 - x1, y2 - y1
                    L2 = dx * dx + dy * dy
                    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
                    dd = _m.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
                    if dd < 1.4:
                        blockers[n2] = min(blockers.get(n2, 9), dd)
                for (vx, vy, n2) in r.vias:
                    if n2 != net:
                        import math as _m
                        dd = _m.hypot(px - vx, py - vy)
                        if dd < 1.4:
                            blockers[n2] = min(blockers.get(n2, 9), dd)
                ripped = sorted(blockers, key=blockers.get)[:3]
                for n2 in ripped:
                    remove_net_copper(board, n2)
                    r.forget_net(n2)
                ok2, fails2 = connect_pad(r, board, net, net_pads[net], pad, fp)
                for n2 in ripped:
                    ok3, fails3 = route_net(r, board, n2, net_pads[n2])
                    still += [(n2, f) for f in fails3]
                if fails2:
                    still += [(net, f) for f in fails2]
            failed = list(dict.fromkeys(still))
    pcbnew.SaveBoard(BOARD, board)
    print("placed tracks:", len(r.placed_tracks), "vias:", len(r.vias))
    json.dump({"tracks": len(r.placed_tracks), "vias": len(r.vias),
               "failed": failed},
              open("analysis/helpers/route_report.json", "w"), indent=1)
    if failed:
        print("FAILED:", failed)


if __name__ == "__main__":
    main()
