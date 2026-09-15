#!/usr/bin/env python3
"""Via passes after routing: plane stubs, perimeter fence, transition stitching.

Run under KiCad python AFTER drive_route.py. Re-derives obstacles from the
routed board so clearance checks reflect actual copper.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R

BOARD = sys.argv[1] if len(sys.argv) > 1 else "Platvorm.kicad_pcb"
F, B = pcbnew.F_Cu, pcbnew.B_Cu
STUB_W = 0.45


def collect_copper(board, pads):
    """All copper geometry as clearance-testable shapes."""
    shapes = []  # ("pad", x,y,hw,hh,net,is_tht/layers) | ("seg", li,x1,y1,x2,y2,w,net) | ("via", x,y,net)
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            n = p["net"] or ""
            w, h = R.aabb_pad(p)
            lays = (0, 1) if p["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
            shapes.append(("pad", p["x"], p["y"], w / 2, h / 2, n, lays))
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            li = 0 if t.GetLayer() == F else 1
            shapes.append(("seg", li, s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6,
                           t.GetWidth() / 1e6, net))
        elif t.Type() == pcbnew.PCB_VIA_T:
            pos = t.GetPosition()
            # K10: via width is per-layer; all board vias are 0.6 through-vias
            shapes.append(("via", pos.x / 1e6, pos.y / 1e6, net, R.VIA_D))
    return shapes


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def via_ok(x, y, shapes, own_net, li_needed=(0, 1), pad_core=None, edge=(0, 0, 0, 0)):
    x0, y0, x1, y1 = edge
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    need = R.VIA_HALF + R.CLR
    for sh in shapes:
        if sh[0] == "pad":
            _, px, py, hw, hh, net, lays = sh
            if net == own_net and pad_core and abs(x - pad_core[0]) <= pad_core[2] + 0.05 \
               and abs(y - pad_core[1]) <= pad_core[3] + 0.05:
                continue  # own pad overlap allowed (stub lands on it)
            dx = max(abs(x - px) - hw, 0.0)
            dy = max(abs(y - py) - hh, 0.0)
            if dx * dx + dy * dy < need * need and (set(lays) & set(li_needed)):
                return False
        elif sh[0] == "seg":
            _, li, sx1, sy1, sx2, sy2, w, net = sh
            if li not in li_needed:
                continue
            if seg_dist(x, y, sx1, sy1, sx2, sy2) < need + w / 2:
                return False
        else:
            _, vx, vy, net, vd = sh
            if math.hypot(x - vx, y - vy) < need + vd / 2:
                return False
    return True


def add_plane_vias(board, pads, shapes, edge):
    netcode = {n: board.FindNet(n) for n in ("GND", "+3V3")}
    n_stub = 0
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            net = p["net"]
            if net not in ("GND", "+3V3") or p["attr"] == 0:
                continue  # THT plane pads already stitch
            w, h = R.aabb_pad(p)
            li = 0 if fp["layer"] == "F.Cu" else 1
            lay = F if li == 0 else B
            # candidate directions: perpendicular to pad long axis first
            dirs = []
            if w >= h:
                dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            else:
                dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
            dirs += [(s, d) for s in (1, -1) for d in (1, -1)]
            placed = False
            for dist in (0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.45, 1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.0):
                for (dx, dy) in dirs:
                    vx, vy = p["x"] + dx * dist, p["y"] + dy * dist
                    if not via_ok(vx, vy, shapes, net, (0, 1), pad_core=(p["x"], p["y"], w / 2, h / 2), edge=edge):
                        continue
                    # stub must also clear foreign copper along its length
                    ok = True
                    for k in range(1, 6):
                        t = k / 6.0
                        sx, sy = p["x"] + (vx - p["x"]) * t, p["y"] + (vy - p["y"]) * t
                        for sh in shapes:
                            if sh[0] == "pad":
                                _, px, py, hw, hh, n2, lays = sh
                                if n2 == net or li not in lays:
                                    continue
                                if abs(sx - px) < hw + STUB_W / 2 + R.CLR and abs(sy - py) < hh + STUB_W / 2 + R.CLR:
                                    ok = False; break
                            elif sh[0] == "seg":
                                _, li2, a, b2, c, d2, w2, n2 = sh
                                if n2 == net or li2 != li:
                                    continue
                                if seg_dist(sx, sy, a, b2, c, d2) < w2 / 2 + STUB_W / 2 + R.CLR:
                                    ok = False; break
                            else:
                                _, vx2, vy2, n2, vd2 = sh
                                if n2 == net:
                                    continue
                                if math.hypot(sx - vx2, sy - vy2) < vd2 / 2 + STUB_W / 2 + R.CLR:
                                    ok = False; break
                        if not ok:
                            break
                    if not ok:
                        continue
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(R.V(p["x"], p["y"])); t.SetEnd(R.V(vx, vy))
                    t.SetWidth(int(STUB_W * 1e6)); t.SetLayer(lay)
                    t.SetNet(netcode[net]); board.Add(t)
                    v = pcbnew.PCB_VIA(board)
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetPosition(R.V(vx, vy))
                    v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
                    v.SetNet(netcode[net]); board.Add(v)
                    shapes.append(("seg", li, p["x"], p["y"], vx, vy, STUB_W, net))
                    shapes.append(("via", vx, vy, net, R.VIA_D))
                    placed = True; n_stub += 1
                    break
                if placed:
                    break
            if not placed:
                print(f"  !! no via spot for {ref}.{p['num']} ({net})")
    return n_stub


def add_fence(board, shapes, edge, pitch=3.5, inset=1.1):
    x0, y0, x1, y1 = edge
    fx0, fy0, fx1, fy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    net = board.FindNet("GND")
    # walk perimeter
    pts = []
    per_w, per_h = fx1 - fx0, fy1 - fy0
    nx = max(2, int(per_w / pitch))
    ny = max(2, int(per_h / pitch))
    for k in range(nx + 1):
        x = fx0 + per_w * k / nx
        pts += [(x, fy0), (x, fy1)]
    for k in range(1, ny):
        y = fy0 + per_h * k / ny
        pts += [(fx0, y), (fx1, y)]
    n = 0
    for (x, y) in pts:
        x = round(x, 3); y = round(y, 3)
        if via_ok(x, y, shapes, "GND", (0, 1), edge=edge):
            v = pcbnew.PCB_VIA(board)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetPosition(R.V(x, y))
            v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
            v.SetNet(net); board.Add(v)
            shapes.append(("via", x, y, "GND", R.VIA_D))
            n += 1
    return n, len(pts)


def add_transition_stitch(board, shapes, edge):
    """GND via near every signal via (return-path continuity)."""
    net = board.FindNet("GND")
    vias = [sh for sh in shapes if sh[0] == "via" and sh[2] not in ("GND", "+3V3")]
    n = 0
    for (_, x, y, sig_net, vd) in vias:
        for dist in (0.85, 1.0):
            for (dx, dy) in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                gx, gy = round(x + dx * dist, 3), round(y + dy * dist, 3)
                if via_ok(gx, gy, shapes, "GND", (0, 1), edge=edge):
                    v = pcbnew.PCB_VIA(board)
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetPosition(R.V(gx, gy))
                    v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
                    v.SetNet(net); board.Add(v)
                    shapes.append(("via", gx, gy, "GND", R.VIA_D))
                    n += 1
                    break
            else:
                continue
            break
    return n


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    x0, y0, x1, y1 = pads["bbox"]
    edge = (x0 + 0.6, y0 + 0.6, x1 - 0.6, y1 - 0.6)
    shapes = collect_copper(board, pads)
    print("copper shapes:", len(shapes))
    n1 = add_plane_vias(board, pads, shapes, edge)
    # NOTE: perimeter fence + transition stitching intentionally omitted:
    # GND exists on a single layer (In1) with no outer-layer GND pours, so
    # vias touching only In1 are electrically inert and DRC-dangling.
    print(f"plane stubs+vias: {n1}")
    pcbnew.SaveBoard(BOARD, board)


if __name__ == "__main__":
    main()
