#!/usr/bin/env python3
"""4-layer conversion + full re-route of Platvorm.kicad_pcb.

Run under KiCad's bundled Python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 tools/route4.py [stage]

Stages: rip | route | vias | fill   (default: all)
- rip:   4-layer conversion, rip up all copper, create In1 GND + In2 +3V3 planes
- route: grid A* router for all non-plane nets on F.Cu/B.Cu
- vias:  GND/+3V3 pad stitching, perimeter fence, transition-adjacent stitching
- fill:  zone refill + save
"""
import pcbnew, json, math, heapq, sys

NM = 1000000
BOARD = "Platvorm.kicad_pcb"
HELP = "analysis/helpers"

F, B, IN1, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu

# ---- design constants (strict-but-fab-safe; mirrored into .kicad_pro) ----
CLR = 0.20          # copper clearance
TRK_SIG = 0.25      # signal track width
VIA_D, VIA_DRILL = 0.6, 0.3
MARGIN = 0.05       # router safety margin
EDGE_KEEPIN = 0.6   # copper keep-in from board edge
GRID = 0.1          # router grid pitch (mm)

FAT_NETS = {        # power/switching nets -> fat widths (mm)
    "/Power Supply/VIN_BUCK": 1.2, "/Power Supply/SW": 1.2,
    "/Power Supply/VOUT_PRE": 1.2, "+5V": 1.0, "+12V": 1.0, "-12V": 1.0,
    "/Power Supply/+12V_RAW": 1.0, "/Power Supply/-12V_RAW": 1.0,
    "/Power Supply/+5V_EURO": 1.0, "VBUS": 0.8,
}
PLANES = {"GND": IN1, "+3V3": IN2}

# route order: coupled pair + buck first, then fat rails, then everything else
ROUTE_ORDER = [
    "/USB & UART Bridge/USB_DM", "/USB & UART Bridge/USB_DP",
    "/Power Supply/SW", "/Power Supply/VIN_BUCK", "/Power Supply/VOUT_PRE", "FB",
    "/Power Supply/+12V_RAW", "/Power Supply/-12V_RAW", "/Power Supply/+5V_EURO",
    "+12V", "-12V", "+5V", "VBUS",
    "/USB & UART Bridge/CC1", "/USB & UART Bridge/CC2",
]


def load():
    b = pcbnew.LoadBoard(BOARD)
    pads = json.load(open(f"{HELP}/pads_api.json"))
    return b, pads


def stage_rip(b, pads):
    """4-layer conversion: rip all tracks/vias/zones; add GND + 3V3 planes."""
    # snapshot zone refs while swig wrappers are valid (Remove() corrupts them)
    zones = [(z, z.GetIsRuleArea()) for z in list(b.Zones())]
    n = 0
    for t in list(b.GetTracks()):
        b.Remove(t); n += 1
    z = 0
    for zone, is_rule in zones:
        if is_rule:      # keep keepouts (e.g. antenna rule area)
            continue
        b.Remove(zone); z += 1
    print(f"ripped {n} tracks/vias, {z} zones")

    b.SetCopperLayerCount(4)
    b.SetLayerName(IN1, "In1.Cu"); b.SetLayerName(IN2, "In2.Cu")
    b.SetLayerType(IN1, pcbnew.LT_POWER); b.SetLayerType(IN2, pcbnew.LT_POWER)

    x0, y0, x1, y1 = pads["bbox"]
    ins = 0.4
    for netname, layer in (("GND", IN1), ("+3V3", IN2)):
        zone = pcbnew.ZONE(b)
        zone.SetLayer(layer)
        zone.SetNet(b.FindNet(netname))
        for (x, y) in ((x0+ins, y0+ins), (x1-ins, y0+ins), (x1-ins, y1-ins), (x0+ins, y1-ins)):
            zone.AppendCorner(pcbnew.VECTOR2I(int(round(x*NM)), int(round(y*NM))), -1)
        zone.SetMinThickness(int(0.2*NM))
        zone.SetLocalClearance(int(0.3*NM))
        zone.SetZoneName(f"{netname.replace('+','P').replace('/','_')}_PLANE")
        zone.SetAssignedPriority(1)
        b.Add(zone)
        print(f"zone {netname} on {pcbnew.LayerName(layer)}")
    pcbnew.SaveBoard(BOARD, b)


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    b, pads = load()
    if stage in ("rip", "all"):
        stage_rip(b, pads)
