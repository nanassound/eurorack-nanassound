#!/usr/bin/env python3
"""Hand-verified patch routes for J3 USB pair + BFS via-finder for plane pads
that could not get a stub via (run after routing, before drive_vias)."""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR
from collections import deque

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"
DM = "/USB & UART Bridge/USB_DM"
DP = "/USB & UART Bridge/USB_DP"

# All coordinates hand-verified against pad halos + escape stub geometry
PATCHES = [
    # DM: B7 stub end (121.86) -> y120.7 lane (clears A6/B6 stub ends at 121.11
    # by 0.41 > 0.375 halo) -> up into A7 stub end
    (DM, F, 0.2, [(69.2, 121.86), (69.2, 120.7), (70.175, 120.7), (70.175, 121.86)]),
    # DP: A6 stub end -> y119.6 lane -> up into B6 stub end
    (DP, F, 0.2, [(69.6, 121.11), (69.6, 119.6), (70.7, 119.6), (70.7, 121.11)]),
    # DP: A6 stub end -> east x69.9 corridor -> down into U3.4 pad
    (DP, F, 0.2, [(69.9, 121.11), (69.9, 117.26), (68.45, 117.26)]),
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
    r = replay(board, pads)

    # 1. hand patches (validated against current obstacles)
    for (net, lay, w, pts) in PATCHES:
        npads = [(r2, f2, p2) for r2, f2 in pads["footprints"].items()
                 for p2 in f2["pads"] if p2["net"] == net]
        snap = DR.unblock_net(r, net, npads)
        li = 0 if lay == F else 1
        ok = all(DR.seg_clear(r, li, a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))
        if not ok:
            print(f"  !! patch {net} {pts[0]} blocked")
            DR.reblock_net(r, net, npads, snap)
            continue
        netcode = board.FindNet(net)
        for a, b2 in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(a[0], a[1])); t.SetEnd(R.V(b2[0], b2[1]))
            t.SetWidth(int(w * 1e6)); t.SetLayer(lay)
            t.SetNet(netcode); board.Add(t)
            r.block_track(li, a[0], a[1], b2[0], b2[1], w, net)
        print(f"  patch {net}: {pts[0]} -> {pts[-1]}")
        DR.reblock_net(r, net, npads, snap)

    # 2. BFS via-finder for plane pads without copper
    for ref, num in (("C1", "2"), ("C3", "2"), ("U3", "2"), ("C9", "2"), ("R2", "2")):
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if p["num"] == num][0]
        net = pad["net"]
        px, py = pad["x"], pad["y"]
        # already has copper?
        has = False
        for (li, x1, y1, x2, y2, w2, n2) in r.placed_tracks:
            if n2 == net and math.hypot(x1 - px, y1 - py) < 0.8:
                has = True; break
        if has:
            continue
        li = 0
        # BFS over fat08 grid from pad cells to nearest via-capable cell
        src = r.cell(px, py)
        g = r.g[li]["fat08"]
        viastat_ok = lambda i, j: (r.viastat is not None and
                                   all(r.viastat[l2][j * r.nx + i] == 0 for l2 in (0, 1)))
        via_ok2 = lambda i, j: all(r.g[l2]["via"][j * r.nx + i] == 0 for l2 in (0, 1)) and viastat_ok(i, j)
        dq = deque([(src[0], src[1])])
        prev = {src: None}
        goal = None
        start_own = set()
        w2, h2 = R.aabb_pad(pad)
        i0, j0 = r.cell(px - w2 / 2 - 0.05, py - h2 / 2 - 0.05)
        i1, j1 = r.cell(px + w2 / 2 + 0.05, py + h2 / 2 + 0.05)
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                start_own.add((i, j))
                if (i, j) not in prev:
                    prev[(i, j)] = "src"
                    dq.append((i, j))
        while dq and goal is None:
            i, j = dq.popleft()
            d0 = math.hypot(px - r.xy(i, j)[0], py - r.xy(i, j)[1])
            if d0 > 0.9 and via_ok2(i, j):
                goal = (i, j)
                break
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not r.inb(ni, nj) or (ni, nj) in prev:
                    continue
                if g[nj * r.nx + ni] and (ni, nj) not in start_own:
                    continue
                prev[(ni, nj)] = (i, j)
                dq.append((ni, nj))
        if goal is None:
            print(f"  !! BFS no via cell for {ref}.{num}")
            continue
        # trace back
        path = [goal]
        while prev[path[-1]] not in (None, "src"):
            path.append(prev[path[-1]])
        path.reverse()
        # simplify to corners + pad center
        pts = [(px, py)] + [r.xy(i, j) for (i, j) in path]
        simp = [pts[0]]
        for p in pts[1:]:
            lp = simp[-1]
            if len(simp) >= 2:
                pp = simp[-2]
                if (pp[0] == lp[0] == p[0]) or (pp[1] == lp[1] == p[1]):
                    simp[-1] = p
                    continue
            simp.append(p)
        netcode = board.FindNet(net)
        for a, b2 in zip(simp, simp[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(R.V(a[0], a[1])); t.SetEnd(R.V(b2[0], b2[1]))
            t.SetWidth(int(0.45 * 1e6)); t.SetLayer(F)
            t.SetNet(netcode); board.Add(t)
            r.block_track(0, a[0], a[1], b2[0], b2[1], 0.45, net)
        v = pcbnew.PCB_VIA(board)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetPosition(R.V(*simp[-1]))
        v.SetWidth(int(R.VIA_D * 1e6)); v.SetDrill(int(R.VIA_DRILL * 1e6))
        v.SetNet(netcode); board.Add(v)
        r.block_via(simp[-1][0], simp[-1][1])
        print(f"  via-finder {ref}.{num} ({net}): via at ({simp[-1][0]:.2f},{simp[-1][1]:.2f})")

    pcbnew.SaveBoard(BOARD, board)
    print("saved")


if __name__ == "__main__":
    main()
