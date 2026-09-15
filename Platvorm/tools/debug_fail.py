#!/usr/bin/env python3
"""Debug failed pads: ASCII map of obstacle grids around each failure (KiCad python)."""
import sys, json, math
sys.path.insert(0, "tools")
import pcbnew
import router as R

F, B = pcbnew.F_Cu, pcbnew.B_Cu
BOARD = "/tmp/testroute.kicad_pcb"

FAILED = [
    ("VBUS", "J3", "B4A9"), ("VBUS", "U3", "5"), ("VBUS", "D1", "2"), ("VBUS", "C10", "1"),
    ("IO21", "J2", "20"), ("IO19", "J2", "18"), ("IO20", "J2", "19"), ("IO22", "J2", "21"),
    ("IO23", "U1", "21"), ("IO18", "U1", "16"),
    ("/Power Supply/FB", "R2", "1"),
]


def main():
    board = pcbnew.LoadBoard(BOARD)
    pads = json.load(open("analysis/helpers/pads_api.json"))
    r = R.Router(pads)
    # replay placed copper from board
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_TRACE_T:
            s, e = t.GetStart(), t.GetEnd()
            li = 0 if t.GetLayer() == F else 1
            r.block_track(li, s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6,
                          t.GetWidth() / 1e6, net)
            r.placed_tracks.append((li, s.x / 1e6, s.y / 1e6, e.x / 1e6, e.y / 1e6,
                                    t.GetWidth() / 1e6, net))
        elif t.Type() == pcbnew.PCB_VIA_T:
            pos = t.GetPosition()
            r.block_via(pos.x / 1e6, pos.y / 1e6)
            r.vias.append((pos.x / 1e6, pos.y / 1e6, net))

    for (net, ref, padnum) in FAILED:
        fp = pads["footprints"][ref]
        pad = [p for p in fp["pads"] if p["num"] == padnum][0]
        w = R.FAT_NETS.get(net, R.TRK_SIG)
        if w <= R.TRK_SIG + 0.01:
            cls = "sig"
        elif w >= 1.1:
            cls = "fat12"
        elif w >= 0.9:
            cls = "fat10"
        else:
            cls = "fat08"
        print(f"\n=== {net} {ref}.{padnum} at ({pad['x']:.2f},{pad['y']:.2f}) w={w} cls={cls} ===")
        S = 3.5  # half window mm
        i0, j0 = r.cell(pad["x"] - S, pad["y"] - S)
        i1, j1 = r.cell(pad["x"] + S, pad["y"] + S)
        # map layer: SMD -> its layer; show both if THT
        lays = (0, 1) if pad["attr"] == 3 else (0 if fp["layer"] == "F.Cu" else 1,)
        # unblock own net to see what a retry would see
        net_pads = []
        for ref2, fp2 in pads["footprints"].items():
            for p2 in fp2["pads"]:
                if p2["net"] == net:
                    net_pads.append((ref2, fp2, p2))
        import drive_route as DR
        DR.unblock_net(r, net, net_pads)
        for li in lays[:1]:  # first relevant layer only, keep output compact
            g = r.g[li][cls]
            print(f"layer {'F' if li==0 else 'B'}, '{cls}' obstacles (+ foreign block, . free, O own pad, # own copper):")
            for j in range(j1, j0 - 1, -4):  # 0.2mm rows
                row = []
                for i in range(i0, i1 + 1, 2):  # 0.1mm cols
                    if not r.inb(i, j):
                        row.append(" ")
                        continue
                    x, y = r.xy(i, j)
                    ch = "."
                    if g[j * r.nx + i]:
                        ch = "+"
                    # own pad?
                    for (ref2, fp2, p2) in net_pads:
                        w2, h2 = R.aabb_pad(p2)
                        if abs(x - p2["x"]) <= w2 / 2 + 0.1 and abs(y - p2["y"]) <= h2 / 2 + 0.1:
                            ch = "O"
                            break
                    if ch != "O" and (i, j) in r.net_cells.get(net, set()):
                        ch = "#"
                    if abs(x - pad["x"]) < 0.1 and abs(y - pad["y"]) < 0.1:
                        ch = "T"
                    row.append(ch)
                print("".join(row))
        DR.reblock_net(r, net, net_pads)


if __name__ == "__main__":
    main()
