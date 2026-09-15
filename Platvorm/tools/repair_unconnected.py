#!/usr/bin/env python3
"""DRC-driven connectivity repair: connect same-net items DRC reports unconnected.

Loop: kicad-cli DRC (json) -> parse unconnected pairs -> for each, A* a patch
route between the two items' positions (with layer transitions as needed).
Runs under KiCad python; calls kicad-cli itself.
"""
import sys, json, math, subprocess, os
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"
PRO = os.path.splitext(BOARD)[0] + ".kicad_pro"


def run_drc():
    out = BOARD + ".drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json",
                    "-o", out, BOARD], capture_output=True, check=True)
    return json.load(open(out))


def items_at(board, r):
    """Map (rounded x, y, layer-ish) -> list of copper items, and pad/via/track lookup."""
    tracks, vias, pads = [], [], []
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            tracks.append({"net": net, "li": 0 if t.GetLayer() == F else 1,
                           "x1": s.x / 1e6, "y1": s.y / 1e6, "x2": e.x / 1e6, "y2": e.y / 1e6,
                           "w": t.GetWidth() / 1e6})
        elif t.Type() == pcbnew.PCB_VIA_T:
            p = t.GetPosition()
            vias.append({"net": net, "x": p.x / 1e6, "y": p.y / 1e6, "w": 0.6})
    for fp in board.GetFootprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if not n or n.startswith("unconnected"):
                continue
            pos = p.GetPosition()
            pads.append({"net": n, "ref": fp.GetReference(), "num": p.GetNumber(),
                         "x": pos.x / 1e6, "y": pos.y / 1e6,
                         "li": None, "tht": int(p.GetAttribute()) == 0})
    return tracks, vias, pads


def nearest_copper(net, px, py, li, tracks, vias, pads):
    """Find a same-net copper point near (px,py) on given layer; returns (x, y, layer)."""
    best = None

    def consider(x, y, layer, d):
        nonlocal best
        if best is None or d < best[0]:
            best = (d, x, y, layer)

    for t in tracks:
        if t["net"] != net or t["li"] != li:
            continue
        dx, dy = t["x2"] - t["x1"], t["y2"] - t["y1"]
        L2 = dx * dx + dy * dy
        tt = 0 if L2 == 0 else max(0, min(1, ((px - t["x1"]) * dx + (py - t["y1"]) * dy) / L2))
        qx, qy = t["x1"] + tt * dx, t["y1"] + tt * dy
        d = math.hypot(px - qx, py - qy)
        if d < 1.0:
            consider(qx, qy, li, d)
    for v in vias:
        if v["net"] != net:
            continue
        d = math.hypot(px - v["x"], py - v["y"])
        if d < 1.0:
            consider(v["x"], v["y"], li, d)
    for p in pads:
        if p["net"] != net:
            continue
        d = math.hypot(px - p["x"], py - p["y"])
        if d < 1.0 and (p["tht"] or p["li"] == li):
            consider(p["x"], p["y"], li, d)
    return best


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    for rnd in range(4):
        d = run_drc()
        unc = d.get("unconnected_items", [])
        print(f"round {rnd}: {len(unc)} unconnected")
        if not unc:
            break
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
        tracks, vias, pads_l = items_at(board, r)
        net_pads = DR.build_net_pads(pads)
        repaired = 0
        import re as _re
        for u in unc:
            items = u.get("items", [])
            if len(items) != 2:
                continue
            net = None
            for it in items:
                m = _re.search(r"\[([^\]]+)\]", it.get("description", ""))
                if m:
                    net = m.group(1)
                    break
            ends = []
            for it in items:
                p = it.get("pos", {})
                px, py = p.get("x"), p.get("y")
                desc = it.get("description", "")
                li = 0
                if "on B.Cu" in desc:
                    li = 1
                elif "on F.Cu" in desc:
                    li = 0
                else:
                    li = None  # pad or via: try both
                ends.append((px, py, li, desc))
            (ax, ay, ali, adesc), (bx, by, bli, bdesc) = ends
            if ax is None or bx is None:
                continue
            # snap to nearest same-net copper point on a definite layer
            aa = nearest_copper(net, ax, ay, ali if ali is not None else 0, tracks, vias, pads_l)
            bb = nearest_copper(net, bx, by, bli if bli is not None else 0, tracks, vias, pads_l)
            if not aa or not bb:
                continue
            _, ax2, ay2, _ = aa
            _, bx2, by2, _ = bb
            if math.hypot(ax2 - bx2, ay2 - by2) < 0.06:
                continue  # already touching; DRC stale or pad-shape corner case
            npads = net_pads.get(net, [])
            if not npads:
                continue
            DR.unblock_net(r, net, npads)
            ia, ja = r.cell(ax2, ay2)
            ib, jb = r.cell(bx2, by2)
            starts = {ali if ali is not None else 0: {(ia, ja)}}
            goals = {bli if bli is not None else 0: {(ib, jb)}}
            # also allow either layer start/goal if via-ish
            if "Via" in adesc:
                starts[1 - (ali or 0)] = {(ia, ja)}
            if "Via" in bdesc:
                goals[1 - (bli or 0)] = {(ib, jb)}
            wchain = DR.width_chain(net) if net not in ("GND", "+3V3") else [0.45, 0.3, 0.2]
            path = None
            for wtry in wchain:
                path = r.route(wtry, starts, goals, bmult=1.0)
                if path is not None:
                    break
            if path:
                r.emit(path, wtry, net, board, None, None)
                repaired += 1
                # refresh local caches with new copper
                tracks, vias, pads_l = items_at(board, r)
            DR.reblock_net(r, net, npads)
        pcbnew.SaveBoard(BOARD, board)
        print(f"  repaired {repaired}")
        if repaired == 0:
            break
    # final count
    d = run_drc()
    print("final unconnected:", len(d.get("unconnected_items", [])))
    print("final violations:", len(d.get("violations", [])))


if __name__ == "__main__":
    main()
