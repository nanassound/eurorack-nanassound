#!/usr/bin/env python3
"""Probe why a specific net fails: instrumented A* + explored-region dump."""
import sys, json, math, heapq
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"
NET = sys.argv[2] if len(sys.argv) > 2 else "IO23"


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

    net_pads = []
    for ref, fp in pads["footprints"].items():
        for p in fp["pads"]:
            if p["net"] == NET:
                net_pads.append((ref, fp, p))
    print("pads:", [(a, b["num"], round(b["x"], 2), round(b["y"], 2)) for a, _, b in net_pads])
    DR.unblock_net(r, NET, net_pads)

    a, b_ = net_pads[0], net_pads[-1]
    starts = DR.pad_core_cells(r, a[2], a[1])
    goals = DR.pad_core_cells(r, b_[2], b_[1])
    print("start cells:", {k: len(v) for k, v in starts.items()},
          "goal cells:", {k: len(v) for k, v in goals.items()})

    gsig = (r.g[0]["sig"], r.g[1]["sig"])
    gvia = (r.g[0]["via"], r.g[1]["via"])
    start_set = {(i, j, li) for li, c in starts.items() for (i, j) in c}
    goal_keys = {(i, j) for li, c in goals.items() for (i, j) in c}
    dist, parent, pq = {}, {}, []
    for s in sorted(start_set):
        dist[s] = 0.0; heapq.heappush(pq, (0.0, s))
    goal_state = None
    popped = 0
    while pq:
        d, cur = heapq.heappop(pq)
        if d > dist.get(cur, 1e18) + 1e-9:
            continue
        popped += 1
        i, j, li = cur
        if (i, j) in goal_keys:
            goal_state = cur; break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if not r.inb(ni, nj): continue
            if gsig[li][nj * r.nx + ni]: continue
            st = (ni, nj, li); nd = d + (0.5 if li == 1 else 1.0)
            if nd < dist.get(st, 1e18) - 1e-9:
                dist[st] = nd; parent[st] = cur; heapq.heappush(pq, (nd, st))
        oli = 1 - li
        if not gvia[li][j * r.nx + i] and not gvia[oli][j * r.nx + i]:
            st = (i, j, oli); nd = d + 6.0
            if nd < dist.get(st, 1e18) - 1e-9:
                dist[st] = nd; parent[st] = cur; heapq.heappush(pq, (nd, st))
    print("path:", goal_state is not None, "popped:", popped)
    if goal_state is None:
        # reachable frontier: nodes adjacent to explored but blocked
        frontier = {}
        for st in dist:
            i, j, li = st
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if r.inb(ni, nj) and (ni, nj, li) not in dist and gsig[li][nj * r.nx + ni]:
                    x, y = r.xy(ni, nj)
                    frontier.setdefault("blocked_step", []).append((round(x, 2), round(y, 2), li))
            oli = 1 - li
            if (i, j, oli) not in dist and (gvia[li][j * r.nx + i] or gvia[oli][j * r.nx + i]):
                x, y = r.xy(i, j)
                frontier.setdefault("blocked_via", []).append((round(x, 2), round(y, 2), li))
        for k, v in frontier.items():
            xs = [p[0] for p in v]; ys = [p[1] for p in v]
            print(f"{k}: {len(v)} cells, x [{min(xs):.2f},{max(xs):.2f}] y [{min(ys):.2f},{max(ys):.2f}]")
            print("  sample:", v[:8])
        # explored bbox
        xs = [r.xy(*st[:2])[0] for st in dist]; ys = [r.xy(*st[:2])[1] for st in dist]
        print(f"explored bbox x [{min(xs):.2f},{max(xs):.2f}] y [{min(ys):.2f},{max(ys):.2f}] n={len(dist)}")


if __name__ == "__main__":
    main()
