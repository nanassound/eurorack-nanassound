#!/usr/bin/env python3
"""Targeted rip-up: remove IO4 copper, route FB (R2.1 was sealed), re-route IO4."""
import sys, json
sys.path.insert(0, "tools")
import pcbnew
import router as R
import drive_route as DR

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = sys.argv[1] if len(sys.argv) > 1 else "/tmp/testroute.kicad_pcb"

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

# 1. rip IO4
DR.remove_net_copper(board, "IO4")
r.forget_net("IO4")
print("IO4 ripped")

# 2. route FB fully (escape first: R2.1 north now open)
snap = DR.unblock_net(r, "/Power Supply/FB", net_pads["/Power Supply/FB"])
fp = pads["footprints"]["R2"]
pad = [p for p in fp["pads"] if p["num"] == "1"][0]
ex, ey = pad["x"], pad["y"] - 1.8
if DR.seg_clear(r, 0, pad["x"], pad["y"], ex, ey):
    netcode = board.FindNet("/Power Supply/FB")
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(R.V(pad["x"], pad["y"])); t.SetEnd(R.V(ex, ey))
    t.SetWidth(int(0.2 * 1e6)); t.SetLayer(F)
    t.SetNet(netcode); board.Add(t)
    r.block_track(0, pad["x"], pad["y"], ex, ey, 0.2, "/Power Supply/FB")
    r.placed_tracks.append((0, pad["x"], pad["y"], ex, ey, 0.2, "/Power Supply/FB"))
    print("FB escape placed")
else:
    print("!! FB escape still blocked")
DR.reblock_net(r, "/Power Supply/FB", net_pads["/Power Supply/FB"], snap)
ok, fails = DR.route_net(r, board, "/Power Supply/FB", net_pads["/Power Supply/FB"])
print("FB:", ok, "/", len(net_pads["/Power Supply/FB"]), fails)

# 3. re-route IO4 (with B bias)
ok, fails = DR.route_net(r, board, "IO4", net_pads["IO4"], bmult=0.5)
print("IO4:", ok, "/", len(net_pads["IO4"]), fails)

pcbnew.SaveBoard(BOARD, board)
print("saved")
