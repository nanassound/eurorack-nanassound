#!/usr/bin/env python3
"""Finisher: DRC-driven pad reconnection using connect_pad (proper goals).

For each DRC unconnected pair, extract the footprint pad(s) involved and
re-run a dedicated A* connection into the net's existing copper.
"""
import sys, json, re, subprocess, math
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"


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


def drc_unc():
    out = "/tmp/drc/finish.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json",
                    "-o", out, BOARD], capture_output=True, check=True)
    d = json.load(open(out))
    return d.get("unconnected_items", [])


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    net_pads = DR.build_net_pads(pads)

    for rnd in range(4):
        unc = drc_unc()
        print(f"round {rnd}: {len(unc)} unconnected")
        if not unc:
            break
        # collect (net, ref, num) pads to reconnect
        todo = {}
        for u in unc:
            descs = [it.get("description", "") for it in u.get("items", [])]
            net = None
            for dd in descs:
                m = re.search(r"\[([^\]]+)\]", dd)
                if m:
                    net = m.group(1); break
            if not net:
                continue
            for dd in descs:
                m = re.search(r"Pad (\S+).* of (\w+)", dd)
                if m and m.group(2) in pads["footprints"]:
                    num, ref = m.group(1), m.group(2)
                    fp = pads["footprints"][ref]
                    if any(p["num"] == num for p in fp["pads"]):
                        todo[(net, ref, num)] = True
        if not todo:
            print("  no pad targets identified")
            break
        # collect PAD PAIRS from each DRC pair: bridge island to island
        pairs = []
        for u in unc:
            descs = [it.get("description", "") for it in u.get("items", [])]
            net = None
            for dd in descs:
                m = re.search(r"\[([^\]]+)\]", dd)
                if m:
                    net = m.group(1); break
            if not net or net in ("GND", "+3V3"):
                continue
            ppads = []
            for dd in descs:
                m = re.search(r"Pad (\S+).* of (\w+)", dd)
                if m and m.group(2) in pads["footprints"]:
                    num, ref = m.group(1), m.group(2)
                    fp = pads["footprints"][ref]
                    if any(p["num"] == num for p in fp["pads"]):
                        ppads.append((ref, num))
            # if fewer than 2 pads named, map each side to its nearest same-net pad
            if len(ppads) < 2:
                for dd in descs:
                    pos = None
                    for it in u.get("items", []):
                        if dd == it.get("description", ""):
                            pos = it.get("pos")
                    if not pos:
                        continue
                    best = None
                    for (r2, f2, p2) in net_pads.get(net, []):
                        dd2 = math.hypot(p2["x"] - pos.get("x", 0), p2["y"] - pos.get("y", 0))
                        if best is None or dd2 < best[0]:
                            best = (dd2, r2, str(p2["num"]))
                    if best and (best[1], best[2]) not in ppads:
                        ppads.append((best[1], best[2]))
            if len(ppads) >= 2 and ppads[0] != ppads[1]:
                pairs.append((net, ppads[0], ppads[1]))
        seen = set()
        uniq = [p for p in pairs if not (p in seen or seen.add(p))]
        r = replay(board, pads)
        DR.mark_static_vias(r)
        fixed = 0
        for (net, (r1, n1), (r2, n2)) in uniq[:14]:
            npads = net_pads.get(net)
            if not npads:
                continue
            e1 = [t for t in npads if t[0] == r1 and str(t[2]["num"]) == str(n1)]
            e2 = [t for t in npads if t[0] == r2 and str(t[2]["num"]) == str(n2)]
            if not e1 or not e2:
                continue
            _, fp1, pad1 = e1[0]
            _, fp2, pad2 = e2[0]
            DR.unblock_net(r, net, npads)
            starts = DR.pad_core_cells(r, pad1, fp1)
            goals = DR.pad_core_cells(r, pad2, fp2)
            path = None
            for wtry in DR.width_chain(net):
                path = r.route(wtry, starts, goals, bmult=1.0)
                if path is not None:
                    break
            if path:
                r.emit(path, wtry, net, board, {"x": pad1["x"], "y": pad1["y"]}, {"x": pad2["x"], "y": pad2["y"]})
                fixed += 1
                print(f"  bridged {net}: {r1}.{n1} <-> {r2}.{n2}")
            else:
                print(f"  !! no bridge {net}: {r1}.{n1} <-> {r2}.{n2}")
            DR.reblock_net(r, net, npads)
        pcbnew.SaveBoard(BOARD, board)
        print(f"  fixed {fixed}/{len(todo)}")
        if fixed == 0:
            break
    unc = drc_unc()
    print("final unconnected:", len(unc))
    for u in unc[:6]:
        print("  ", [it.get("description", "")[:60] for it in u.get("items", [])])


if __name__ == "__main__":
    main()
