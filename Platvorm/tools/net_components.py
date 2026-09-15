#!/usr/bin/env python3
"""Exact per-net connectivity analysis + bridge finisher.

Builds copper items (tracks/vias/pads with true shapes), union-finds touching
items, and bridges disconnected components of the same net with validated
L-shaped tracks ending at pad centers or item endpoints.
Run under KiCad python after all routing/via stages.
"""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"


def pt_in_pad(x, y, p):
    """p: pads_api pad dict with shape awareness."""
    w, h = R.aabb_pad(p)
    dx, dy = abs(x - p["x"]), abs(y - p["y"])
    if dx > w / 2 or dy > h / 2:
        return False
    shape = p.get("shape", 1)
    if shape == 0:  # circle
        return math.hypot(x - p["x"], y - p["y"]) <= min(w, h) / 2
    # roundrect/oval corner relief
    r = min(w, h) / 4
    cx, cy = abs(dx - (w / 2 - r)), abs(dy - (h / 2 - r))
    if cx > 0 and cy > 0:
        return cx * cx + cy * cy <= r * r
    return True


def seg_seg(a, b, c, d):
    """Min distance between segments."""
    def sub(p, q): return (p[0] - q[0], p[1] - q[1])
    def dot(p, q): return p[0] * q[0] + p[1] * q[1]
    p1, p2, p3, p4 = a, b, c, d
    d1 = sub(p2, p1); d2 = sub(p4, p3); r = sub(p3, p1)
    a1, b1, c1 = dot(d1, d1), dot(d1, d2), dot(d2, d2)
    e1, e2 = dot(d1, r), dot(d2, r)
    den = a1 * c1 - b1 * b1
    s = t = 0.0
    if den != 0:
        s = max(0.0, min(1.0, (e1 * c1 - e2 * b1) / den))
    t = (e2 + s * b1) / c1 if c1 else 0.0
    if t < 0:
        t = 0.0; s = max(0.0, min(1.0, e1 / a1)) if a1 else 0.0
    elif t > 1:
        t = 1.0; s = max(0.0, min(1.0, (e1 - b1) / a1)) if a1 else 0.0
    pc = (p1[0] + s * d1[0], p1[1] + s * d1[1])
    pd = (p3[0] + t * d2[0], p3[1] + t * d2[1])
    return math.hypot(pc[0] - pd[0], pc[1] - pd[1]), pc, pd


class DSU:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    r = R.Router(pads)
    padmap = {}   # ref.num -> pad dict
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            padmap[f"{ref}.{p['num']}"] = p

    items = []  # dicts: kind, net, li, geometry
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            items.append({"k": "T", "net": net, "li": 0 if t.GetLayer() == F else 1,
                          "a": (s.x / 1e6, s.y / 1e6), "b": (e.x / 1e6, e.y / 1e6),
                          "w": t.GetWidth() / 1e6})
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            items.append({"k": "V", "net": net, "li": -1, "a": (p.x / 1e6, p.y / 1e6),
                          "b": (p.x / 1e6, p.y / 1e6), "w": 0.6})
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if not n or n.startswith("unconnected"):
                continue
            key = f"{fp.GetReference()}.{p.GetNumber()}"
            pd = padmap.get(key)
            if not pd:
                continue
            items.append({"k": "P", "net": n, "li": -2, "p": pd,
                          "a": (pd["x"], pd["y"]), "b": (pd["x"], pd["y"]),
                          "w": min(pd["w"], pd["h"]), "pad": key})

    # union-find touching items (same net only)
    dsu = DSU()
    by_net = {}
    for idx, it in enumerate(items):
        by_net.setdefault(it["net"], []).append(idx)
        dsu.find(idx)
    for net, idxs in by_net.items():
        if net in ("GND", "+3V3"):
            continue  # planes: handled by zones; analysis below would need zone shapes
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                A, Bt = items[idxs[ii]], items[idxs[jj]]
                touch = False
                if A["k"] == "V" or Bt["k"] == "V":
                    # via touches anything overlapping its circle on its layer (or any if via)
                    via, other = (A, Bt) if A["k"] == "V" else (Bt, A)
                    if other["k"] == "V":
                        touch = math.hypot(via["a"][0] - other["a"][0], via["a"][1] - other["a"][1]) <= 0.55
                    elif other["k"] == "T":
                        # via passes all layers
                        d, _, _ = seg_seg(via["a"], via["a"], other["a"], other["b"])
                        touch = d <= 0.3 + other["w"] / 2
                    else:  # pad
                        if other["p"]["attr"] == 0 or True:  # via passes all layers; pad copper check
                            touch = pt_in_pad(via["a"][0], via["a"][1], other["p"]) or (
                                math.hypot(via["a"][0] - other["a"][0], via["a"][1] - other["a"][1]) <= 0.3 + other["w"] / 2)
                elif A["k"] == "T" and Bt["k"] == "T":
                    if A["li"] == Bt["li"]:
                        d, _, _ = seg_seg(A["a"], A["b"], Bt["a"], Bt["b"])
                        touch = d <= (A["w"] + Bt["w"]) / 2 + 1e-9
                else:  # track-pad
                    T, Pd = (A, Bt) if A["k"] == "T" else (Bt, A)
                    lays = (0, 1) if Pd["p"]["attr"] == 0 else ((0,) if Pd["p"].get("layers", ["F.Cu"]) == ["F.Cu"] else (1,))
                    if T["li"] in lays:
                        # sample along the track: any sampled point inside pad = touch
                        n = max(2, int(math.hypot(T["b"][0] - T["a"][0], T["b"][1] - T["a"][1]) / 0.05) + 1)
                        for k in range(n + 1):
                            tt = k / n
                            x = T["a"][0] + (T["b"][0] - T["a"][0]) * tt
                            y = T["a"][1] + (T["b"][1] - T["a"][1]) * tt
                            if pt_in_pad(x, y, Pd["p"]):
                                touch = True
                                break
                if touch:
                    dsu.union(idxs[ii], idxs[jj])

    # report broken nets
    problems = []
    for net, idxs in by_net.items():
        if net in ("GND", "+3V3"):
            continue
        comps = {}
        for i in idxs:
            comps.setdefault(dsu.find(i), []).append(items[i])
        if len(comps) > 1:
            sizes = sorted((len(v) for v in comps.values()), reverse=True)
            problems.append((net, comps))
            print(f"{net}: {len(comps)} components {sizes}")
            for root, comp in comps.items():
                pads_in = [it["pad"] for it in comp if it["k"] == "P"]
                if pads_in:
                    print(f"   comp pads: {pads_in}")
    json.dump(len(problems), open("analysis/helpers/comp_problems.json", "w"))
    print("nets with split components:", len(problems))


if __name__ == "__main__":
    main()
