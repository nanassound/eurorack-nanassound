#!/usr/bin/env python3
"""Find chain gaps: per-net endpoint graph over tracks+vias+pads (KiCad python)."""
import sys
sys.path.insert(0, "tools")
import pcbnew
from collections import defaultdict

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"

b = pcbnew.LoadBoard(BOARD)

def key(x, y):
    return (round(x / 25.0), round(y / 25.0))  # 25nm buckets

# build per-net node graph
adj = defaultdict(set)
node_meta = {}

def nodes_of_track(t):
    s, e = t.GetStart(), t.GetEnd()
    return key(s.x, s.y), key(e.x, e.y)

for t in b.GetTracks():
    net = t.GetNetname()
    if t.Type() == pcbnew.PCB_TRACE_T:
        a, c = nodes_of_track(t)
        adj[(net, a)].add((net, c)); adj[(net, c)].add((net, a))
        node_meta.setdefault((net, a), []).append(("trk", t.GetLayer()))
    else:
        p = t.GetPosition()
        k = key(p.x, p.y)
        adj[(net, k)].add((net, "VIA"))
        adj[(net, "VIA")].add((net, k))
        node_meta.setdefault((net, k), []).append(("via",))

for fp in b.GetFootprints():
    for p in fp.Pads():
        net = p.GetNetname()
        if not net or net.startswith("unconnected"):
            continue
        pos = p.GetPosition()
        k = key(pos.x, pos.y)
        adj[(net, k)].add((net, "PAD"))
        adj[(net, "PAD")].add((net, k))

# via nodes bridge layers implicitly (through vias) — tracks on F and B at same key connect only via VIA node
# count components per net
seen = set()
gaps = []
nets = {n for (n, _) in adj}
for net in sorted(nets):
    start = None
    # components
    comps = []
    for node in list(adj):
        if node[0] != net or node in seen:
            continue
        stack = [node]; comp = set()
        while stack:
            cur = stack.pop()
            if cur in seen or cur[0] != net:
                continue
            seen.add(cur); comp.add(cur)
            stack.extend(adj[cur])
        comps.append(comp)
    if len(comps) > 1:
        sizes = sorted(len(c) for c in comps)
        print(f"{net}: {len(comps)} components {sizes}")
        for c in comps:
            if "PAD" not in c and len(c) < 8:
                print("   small orphan:", [x for x in sorted(map(str,c))[:6]])
