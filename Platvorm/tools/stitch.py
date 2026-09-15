#!/usr/bin/env python3
"""Component stitcher: detect true copper islands per net, A*-bridge them.

Islands computed geometrically (tracks/vias/pads, layer-aware). For each net
with >1 island, bridge the two largest islands: starts = grid cells under
island-A copper, goals = cells under island-B copper.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
NM = 1000000
BOARD = sys.argv[1]
board = pcbnew.LoadBoard(BOARD)
pads = json.load(open("analysis/helpers/pads_api.json"))
net_pads = DR.build_net_pads(pads)


def pt_in_pad(x, y, p, shrink=0.0):
    w, h = p["w"], p["h"]
    dx, dy = abs(x - p["x"]), abs(y - p["y"])
    if dx > w / 2 - shrink or dy > h / 2 - shrink:
        return False
    shape = p.get("shape", 1)
    if shape == 0:
        return math.hypot(x - p["x"], y - p["y"]) <= min(w, h) / 2 - shrink
    r = min(w, h) / 4
    cx, cy = abs(dx - (w / 2 - r)), abs(dy - (h / 2 - r))
    if cx > 0 and cy > 0:
        return cx * cx + cy * cy <= r * r
    return True


def seg_seg(a, b, c, d):
    def sub(p, q): return (p[0] - q[0], p[1] - q[1])
    def dot(p, q): return p[0] * q[0] + p[1] * q[1]
    d1, d2, rr = sub(b, a), sub(d, c), sub(c, a)
    a1, b1, c1 = dot(d1, d1), dot(d1, d2), dot(d2, d2)
    e1, e2 = dot(d1, rr), dot(d2, rr)
    den = a1 * c1 - b1 * b1
    s = max(0.0, min(1.0, (e1 * c1 - e2 * b1) / den)) if den else 0.0
    t = (e2 + s * b1) / c1 if c1 else 0.0
    if t < 0:
        t = 0.0
        s = max(0.0, min(1.0, e1 / a1)) if a1 else 0.0
    elif t > 1:
        t = 1.0
        s = max(0.0, min(1.0, (e1 - b1) / a1)) if a1 else 0.0
    pc = (a[0] + s * d1[0], a[1] + s * d1[1])
    pd = (c[0] + t * d2[0], c[1] + t * d2[1])
    return math.hypot(pc[0] - pd[0], pc[1] - pd[1])


class DSU:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def components():
    items = []
    padmap = {}
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            padmap[f"{ref}.{p['num']}"] = p
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            items.append({"k": "T", "net": net, "li": 0 if t.GetLayer() == F else 1,
                          "a": (s.x / NM, s.y / NM), "b": (e.x / NM, e.y / NM), "w": t.GetWidth() / NM})
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            items.append({"k": "V", "net": net, "a": (p.x / NM, p.y / NM), "b": (p.x / NM, p.y / NM), "w": 0.6})
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if not n or n.startswith("unconnected"):
                continue
            pd = padmap.get(f"{fp.GetReference()}.{p.GetNumber()}")
            if pd:
                items.append({"k": "P", "net": n, "p": pd, "a": (pd["x"], pd["y"]), "b": (pd["x"], pd["y"])})
    dsu = DSU()
    by_net = {}
    for idx, it in enumerate(items):
        by_net.setdefault(it["net"], []).append(idx)
    for net, idxs in by_net.items():
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                A, Bt = items[idxs[ii]], items[idxs[jj]]
                touch = False
                if A["k"] == "V" or Bt["k"] == "V":
                    via, other = (A, Bt) if A["k"] == "V" else (Bt, A)
                    if other["k"] == "V":
                        touch = math.hypot(via["a"][0] - other["a"][0], via["a"][1] - other["a"][1]) <= 0.62
                    elif other["k"] == "T":
                        touch = seg_seg(via["a"], via["a"], other["a"], other["b"]) <= 0.3 + other["w"] / 2
                    else:
                        d = seg_seg(via["a"], via["a"], other["a"], other["a"])
                        touch = pt_in_pad(via["a"][0], via["a"][1], other["p"], 0.15) or d <= 0.3
                elif A["k"] == "T" and Bt["k"] == "T":
                    if A["li"] == Bt["li"]:
                        touch = seg_seg(A["a"], A["b"], Bt["a"], Bt["b"]) <= (A["w"] + Bt["w"]) / 2 - 0.01
                elif A["k"] == "T" and Bt["k"] == "T":
                    pass
                else:
                    T, Pd = (A, Bt) if A["k"] == "T" else (Bt, A)
                    if "li" not in T:
                        touch = False
                    else:
                        lays = (0, 1) if Pd["p"]["attr"] == 0 else (0 if Pd["p"].get("layers", ["F.Cu"]) == ["F.Cu"] else 1,)
                        if T["li"] in lays:
                            n = max(2, int(math.hypot(T["b"][0] - T["a"][0], T["b"][1] - T["a"][1]) / 0.05))
                            for k in range(n + 1):
                                tt = k / n
                                x = T["a"][0] + (T["b"][0] - T["a"][0]) * tt
                                y = T["a"][1] + (T["b"][1] - T["a"][1]) * tt
                                if pt_in_pad(x, y, Pd["p"], 0.02):
                                    touch = True
                                    break
                if touch:
                    dsu.union(idxs[ii], idxs[jj])
    comps = {}
    for net, idxs in by_net.items():
        m = {}
        for i in idxs:
            m.setdefault(dsu.find(i), []).append(items[i])
        comps[net] = list(m.values())
    return items, comps


def main():
    items, comps = components()
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

    def cells_of(comp):
        cells = {}
        for it in comp:
            if it["k"] == "P":
                li = None if it["p"]["attr"] == 0 else (0 if it["p"].get("layers") == ["F.Cu"] else 1)
                lay = (0, 1) if li is None else (li,)
                for l2 in lay:
                    i, j = r.cell(it["p"]["x"], it["p"]["y"])
                    if r.inb(i, j):
                        cells.setdefault(l2, set()).add((i, j))
            elif it["k"] == "V":
                i, j = r.cell(it["a"][0], it["a"][1])
                if r.inb(i, j):
                    cells.setdefault(0, set()).add((i, j))
                    cells.setdefault(1, set()).add((i, j))
            else:
                n = max(2, int(math.hypot(it["b"][0] - it["a"][0], it["b"][1] - it["a"][1]) / 0.05))
                for k in range(n + 1):
                    tt = k / n
                    x = it["a"][0] + (it["b"][0] - it["a"][0]) * tt
                    y = it["a"][1] + (it["b"][1] - it["a"][1]) * tt
                    i, j = r.cell(x, y)
                    if r.inb(i, j):
                        cells.setdefault(it["li"], set()).add((i, j))
        return cells

    bridged_total = 0
    for round_i in range(4):
        items, comps = components()
        # rebuild router state after previous emit? emit tracks copper in r already
        did = 0
        for net, cl in sorted(comps.items()):
            if net in ("GND", "+3V3") or len(cl) < 2:
                continue
            # largest two
            cl.sort(key=len, reverse=True)
            A, Bc = cl[0], cl[1]
            npads = net_pads.get(net, [])
            if not npads:
                continue
            snap = DR.unblock_net(r, net, npads)
            starts = cells_of(A)
            goals = cells_of(Bc)
            path = None
            for wtry in DR.width_chain(net):
                path = r.route(wtry, starts, goals, bmult=1.0)
                if path is not None:
                    break
            if path:
                r.emit(path, wtry, net, board, None, None)
                print(f"[S] stitched {net}: {len(A)}+{len(Bc)} items")
                did += 1
            DR.reblock_net(r, net, npads, snap)
        bridged_total += did
        if did == 0:
            break

    # refresh components for report
    items, comps = components()
    left = {n: len(c) for n, c in comps.items() if len(c) > 1 and n not in ("GND", "+3V3")}
    print("[S] remaining split nets:", left)
    pcbnew.SaveBoard(BOARD, board)
    print("saved")


if __name__ == "__main__":
    main()
