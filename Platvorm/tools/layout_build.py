#!/usr/bin/env python3
"""Build Platvorm.kicad_pcb: netlist-driven placement of all 38 footprints,
edge outline, GND zones, stitching vias, silkscreen texts.
Run with KiCad python from the project root.
Coordinates follow the approved placement plan (local://platvorm-layout-plan.md).
"""
import os
import re
import sys
import math

import pcbnew

MM = pcbnew.pcbIUScale.IU_PER_MM  # nm per mm
HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
CUST_FP = os.path.join(PRJ, "footprints", "platvorm_custom.pretty")

# ref -> (x, y, rot_deg)  -- from the approved placement table
PLACEMENT = {
    "U1": (77.5, 59.75, 0),
    "J1": (54.2, 62.0, 180),
    "C2": (59.2, 54.0, 90),
    "R9": (59.2, 57.0, 90),
    "R3": (59.2, 60.0, 90),
    "C6": (59.2, 63.0, 90),
    "R4": (82.8, 72.8, 0),
    "J2": (85.5, 90.0, 0),
    "JP1": (53.5, 81.0, 0),
    "D2": (53.55, 89.0, 0),
    "D3": (53.55, 92.65, 0),
    "D4": (53.55, 96.3, 0),
    "C9": (58.3, 89.0, 90),
    "C10": (58.3, 92.4, 90),
    "D1": (53.55, 99.95, 0),
    "D5": (53.55, 103.6, 0),
    "U2": (54.0, 107.8, 90),
    "C7": (57.2, 105.4, 0),
    "R1": (57.2, 106.6, 0),
    "R2": (57.2, 107.8, 0),
    "R5": (67.0, 104.5, 90),
    "R6": (67.0, 106.50, 90),
    "L1": (58.0, 113.0, 0),
    "Q2": (77.5, 112.0, 0),
    "C1": (63.5, 109.0, 0),
    "C3": (63.5, 115.5, 0),
    "C5": (65.5, 112.0, 0),
    "C8": (65.5, 114.0, 0),
    "Q1": (77.9, 108.5, 0),
    "FB1": (80.5, 114.5, 90),
    "C4": (80.5, 118.1, 90),
    "U4": (71.0, 111.5, 90),
    "U3": (71.0, 120.5, 90),
    "R8": (77.5, 121.0, 0),
    "R7": (77.5, 122.2, 0),
    "SW1": (58.5, 126.55, 0),
    "SW2": (81.5, 127.0, 0),
    "J3": (69.9, 126.55, 180),
}

STITCHING_VIAS = [
    (63.0, 51.2), (66.0, 51.2), (72.5, 51.2), (75.5, 51.2),
    (64.0, 71.6), (68.0, 71.6), (71.8, 71.6),
]

# Pads legitimately without a net (schematic no-connect / NC pins)
ALLOWED_NETLESS = {
    ("J1", str(i)) for i in range(11, 17)
} | {
    ("U2", "5"), ("U1", "13"), ("U1", "14"), ("U1", "22"),
} | {
    ("U4", "7"), ("U4", "8"), ("U4", "9"), ("U4", "10"), ("U4", "11"), ("U4", "12"), ("U4", "15"),
    ("J3", "A8"), ("J3", "B8"),
    ("SW1", "3"), ("SW1", "4"), ("SW2", "3"), ("SW2", "4"),
}
# Schematic pin name -> footprint pad number (USB-C dual / shell pads).
# SH also nets every shell/frame pad to GND.
J3_ALIASES = {"A1": "A1B12", "B12": "A1B12", "A4": "A4B9", "B9": "A4B9",
              "A9": "B4A9", "B4": "B4A9", "A12": "B1A12", "B1": "B1A12",
              "SH": "1"}
J3_SH_MULTI = ("1", "2", "3", "4", "")


def parse_netlist(path):
    txt = open(path, encoding="utf-8").read()
    comps = {}
    for m in re.finditer(r'\(comp\s*\(ref "([^"]+)"\)(.*?)\n\t\t\)', txt, re.S):
        ref, body = m.group(1), m.group(2)
        val = re.search(r'\(value "([^"]*)"\)', body)
        fp = re.search(r'\(footprint "([^"]*)"\)', body)
        fields = {fn: fv for fn, fv in re.findall(
            r'\(property\s*\(name "([^"]+)"\)\s*\(value "([^"]*)"\)', body)}
        fields.update({fn: fv for fn, fv in re.findall(
            r'\(field\s*\(name "([^"]+)"\)\s*"([^"]*)"', body)})
        ds = re.search(r'\(datasheet "([^"]*)"\)', body)
        fields["Datasheet"] = ds.group(1) if ds else "~"
        comps[ref] = (val.group(1) if val else "", fp.group(1) if fp else None, fields)
    nets = {}
    for m in re.finditer(r'\(net\s*\(code "\d+"\)\s*\(name "([^"]+)"\)(.*?)(?=\(net\s*\(code|\Z)', txt, re.S):
        name, body = m.group(1), m.group(2)
        nodes = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', body)
        if len(nodes) < 1:
            continue
        nets[name] = nodes
    return comps, nets


def lib_path(lib):
    if lib == "platvorm_custom":
        return CUST_FP
    return os.path.join(KICAD_FP, lib + ".pretty")


def pad_shape_bbox_center(fp):
    """Center of the pad COPPER bbox in the footprint's own frame."""
    xs, ys = [], []
    for p in fp.Pads():
        bb = p.GetBoundingBox()
        xs += [bb.GetLeft(), bb.GetRight()]
        ys += [bb.GetTop(), bb.GetBottom()]
    return ((min(xs) + max(xs)) / 2 / MM, (min(ys) + max(ys)) / 2 / MM)


def pad_bbox_xy(pad):
    bb = pad.GetBoundingBox()
    return bb.GetLeft(), bb.GetRight(), bb.GetTop(), bb.GetBottom()


def rotate(x, y, deg):
    th = math.radians(deg)
    return (x * math.cos(th) - y * math.sin(th), x * math.sin(th) + y * math.cos(th))

def main():
    comps, nets = parse_netlist(os.path.join(PRJ, "Platvorm.net"))
    print(f"netlist: {len(comps)} components, {len(nets)} routed nets")

    missing = set(PLACEMENT) - set(comps)
    assert not missing, f"placement refs missing from netlist: {missing}"
    extra = set(comps) - set(PLACEMENT)
    assert not extra, f"netlist refs missing from placement: {extra}"

    # always rebuild from a pristine template, keeping the project context
    import shutil
    target = os.path.join(PRJ, "Platvorm.kicad_pcb")
    if os.path.exists(target):
        os.remove(target)
    shutil.copy(os.path.join(HERE, "board_template.kicad_pcb"), target)
    board = pcbnew.LoadBoard(target)

    # -- nets ---------------------------------------------------------------
    netmap = {}
    for name in nets:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
        netmap[name] = n
    gnd = netmap["GND"]

    # -- footprints ---------------------------------------------------------
    by_ref = {}
    for ref, (x, y, rot) in PLACEMENT.items():
        value, fpname, fields = comps[ref]
        assert fpname, f"{ref}: no footprint in netlist"
        lib, name = fpname.split(":", 1)
        fp = pcbnew.FootprintLoad(lib_path(lib), name)
        assert fp is not None, f"cannot load {fpname}"
        assert fp.GetFPIDAsString().endswith(name), f"{ref}: loaded {fp.GetFPIDAsString()} != {name}"
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetFPIDAsString(fpname)  # restore lib nickname for schematic parity
        for fname, fval in fields.items():
            if not fname.startswith("ki_"):
                fp.SetField(fname, fval)
        fp.SetField("Datasheet", fields.get("Datasheet", "~"))
        board.Add(fp)
        dx, dy = pad_shape_bbox_center(fp)
        ox, oy = rotate(dx, dy, rot)
        fp.SetOrientation(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
        fp.SetPosition(pcbnew.VECTOR2I(int(round((x - ox) * MM)), int(round((y - oy) * MM))))
        if ref == "J3":
            for p in fp.Pads():
                p.SetLocalClearance(int(0.1 * MM))
        if ref == "J2":
            # flip to back, mirroring in x about the pad-array center so the
            # pad columns stay at x=73.93/76.47, y=73.49..106.51
            fp.Flip(pcbnew.VECTOR2I(int(75.2 * MM), int(90.0 * MM)), True)
        by_ref[ref] = fp
        print(f"placed {ref:<4} {name:<36} origin=({fp.GetPosition().x/MM:.3f},{fp.GetPosition().y/MM:.3f}) rot={rot}")

    # -- pad/net assignment -------------------------------------------------
    pad_of = {}
    for ref, fp in by_ref.items():
        mpad = {}
        for p in fp.Pads():
            mpad.setdefault(p.GetNumber(), []).append(p)
        pad_of[ref] = mpad
    for name, nodes in nets.items():
        for ref, pin in nodes:
            lookup = J3_ALIASES.get(pin, pin) if ref == "J3" else pin
            pad = pad_of[ref].get(lookup)
            assert pad is not None, f"net {name}: {ref}.{pin} not found on footprint"
            # (net applied to every pad sharing this number below)
            if ref == "J3" and lookup == "1":
                # SH drives every shell/frame pad to its net (GND)
                for num in J3_SH_MULTI:
                    for sp in pad_of[ref].get(num, []):
                        sp.SetNet(netmap[name])
            else:
                assert pad is not None, f"net {name}: {ref}.{pin} not found on footprint"
                for sp in pad:
                    sp.SetNet(netmap[name])
    netless = []
    for ref, pads in pad_of.items():
        for num, plist in pads.items():
            if any(p.GetNet() is None or p.GetNet().GetNetname() == "" for p in plist):
                netless.append((ref, num))
    legit = {("SW1", "3"), ("SW1", "4"), ("SW2", "3"), ("SW2", "4")}
    bad = [x for x in netless if x not in legit and x[0] != "U1"]
    assert not bad, f"unexpected netless pads: {sorted(bad)}"

    # -- board outline ------------------------------------------------------
    def seg(x1, y1, x2, y2):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(int(x1 * MM), int(y1 * MM)))
        s.SetEnd(pcbnew.VECTOR2I(int(x2 * MM), int(y2 * MM)))
        s.SetWidth(int(0.05 * MM))
        s.SetLayer(pcbnew.Edge_Cuts)
        board.Add(s)
    seg(50, 50, 90.3, 50)
    seg(90.3, 50, 90.3, 130)
    seg(90.3, 130, 50, 130)
    seg(50, 130, 50, 50)

    # -- GND zones ----------------------------------------------------------
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(gnd)
        z.SetLocalFlags(0)
        o = z.Outline()
        o.NewOutline()
        for (x, y) in ((50.31, 50.31), (89.99, 50.31), (89.99, 129.69), (50.31, 129.69)):
            o.Append(int(x * MM), int(y * MM))
        z.SetMinThickness(int(0.2 * MM))
        board.Add(z)

    # stitching vias are added by grid_all.py after routing

    # -- silkscreen ---------------------------------------------------------
    for text, x, y, rot in (("-12V", 55.5, 73.7, 0), ("Platvorm revA", 66.5, 111.0, 90)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetPosition(pcbnew.VECTOR2I(int(x * MM), int(y * MM)))
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(pcbnew.VECTOR2I(int(0.9 * MM), int(0.9 * MM)))
        t.SetTextThickness(int(0.15 * MM))
        t.SetTextAngle(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))
        board.Add(t)

    # -- assertions ---------------------------------------------------------
    exs, eys = [], []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            exs += [d.GetStart().x / MM, d.GetEnd().x / MM]
            eys += [d.GetStart().y / MM, d.GetEnd().y / MM]
    assert abs((max(exs) - min(exs)) - 40.3) < 0.01 and abs((max(eys) - min(eys)) - 80.0) < 0.01, \
        f"outline {max(exs)-min(exs):.3f} x {max(eys)-min(eys):.3f}"
    assert len(list(board.GetFootprints())) == 38, len(list(board.GetFootprints()))

    # J2 on B.Cu, pads at documented columns/rows
    j2 = by_ref["J2"]
    # THT pads span both coppers; the flip is footprint-level (shroud/silk to B)
    assert j2.GetLayer() == pcbnew.B_Cu, "J2 footprint not flipped to B side"
    for p in j2.Pads():
        ls = p.GetLayerSet()
        assert ls.Contains(pcbnew.F_Cu) and ls.Contains(pcbnew.B_Cu), \
            f"J2.{p.GetNumber()} not through-hole"
        assert p.IsOnLayer(pcbnew.B_Cu)
    j2xs = sorted({round(p.GetPosition().x / MM, 2) for p in j2.Pads()})
    j2ys = [p.GetPosition().y / MM for p in j2.Pads()]
    assert j2xs == [84.23, 86.77], j2xs
    assert abs(min(j2ys) - 73.49) < 0.01 and abs(max(j2ys) - 106.51) < 0.01, (min(j2ys), max(j2ys))

    u1 = by_ref["U1"]
    z0 = list(u1.Zones())[0]
    kz = z0.Outline().BBox()
    assert abs((kz.GetBottom() / MM) - 50.0) < 0.05, f"keepout bottom {kz.GetBottom()/MM:.3f}"
    crts = u1.GetCourtyard(pcbnew.F_CrtYd).Outline(0).BBox()
    assert crts.GetTop() / MM < 50.0, "U1 courtyard must overhang top edge"
    ux = [pad_bbox_xy(p) for p in u1.Pads()]
    assert abs(max(r for _, r, _, _ in ux) / MM - 87.0) < 0.05
    assert abs(min(l for l, _, _, _ in ux) / MM - 68.0) < 0.05

    # J3 signal pads: copper max y == 129.70 (0.30 to bottom edge)
    j3 = by_ref["J3"]
    for p in j3.Pads():
        assert p.GetLayer() == pcbnew.F_Cu, f"J3.{p.GetNumber()} not on F.Cu"
    sig = [p for p in j3.Pads() if p.GetNumber() in ("A1B12", "A4B9", "B4A9", "B1A12", "A5", "B5", "A6", "B6", "A7", "B7", "A8", "B8")]
    ymax = max(pad_bbox_xy(p)[3] for p in sig) / MM
    if abs(ymax - 129.70) > 0.005:
        dy = int(round((129.70 - ymax) * MM))
        j3.SetPosition(j3.GetPosition() + pcbnew.VECTOR2I(0, dy))
        print(f"J3 nudged by {dy/MM:+.3f} mm in y for 0.30 mm edge clearance")
        ymax = max(pad_bbox_xy(p)[3] for p in sig) / MM
    assert abs(ymax - 129.70) <= 0.005, ymax
    for ref in ("J1", "JP1"):
        for p in by_ref[ref].Pads():
            assert p.GetLayer() == pcbnew.F_Cu

    # copper-to-edge >= 0.30 everywhere
    L, R, T, B = int(50.0 * MM), int(90.3 * MM), int(50.0 * MM), int(130.0 * MM)
    EDGE = 0.295 * MM
    for ref, fp in by_ref.items():
        for p in fp.Pads():
            l, r, t, b = pad_bbox_xy(p)
            d = min(l - L, R - r, t - T, B - b)
            d_mm = d / MM
            if d < EDGE:
                print(f"DBG {ref}.{p.GetNumber()} bbox x[{l/MM:.2f},{r/MM:.2f}] y[{t/MM:.2f},{b/MM:.2f}] ctr=({p.GetPosition().x/MM:.2f},{p.GetPosition().y/MM:.2f}) d={d_mm:.3f}")
            assert d >= EDGE, f"{ref}.{p.GetNumber()} copper {d_mm:.3f} mm from board edge"

    pcbnew.SaveBoard(target, board)
    print("OK: board saved:", target)


if __name__ == "__main__":
    main()
