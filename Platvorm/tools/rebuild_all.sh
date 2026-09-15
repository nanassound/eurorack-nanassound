#!/bin/bash
set -e
cd "$(dirname "$0")/.."
KIPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
cp analysis/helpers/pre_drcfix.bak Platvorm.kicad_pcb
echo "=== rip+planes ==="
$KIPY - <<'EOF' 2>&1 | grep -vE "stdpbase|memory leak|Debug"
import sys; sys.path.insert(0, "tools")
import pcbnew, json
board = pcbnew.LoadBoard("Platvorm.kicad_pcb")
pads = json.load(open("analysis/helpers/pads_api.json"))
zones = [(z, z.GetIsRuleArea()) for z in list(board.Zones())]
n = 0
for t in [t for t in board.GetTracks()]:
    board.Remove(t); n += 1
z = 0
for zone, is_rule in zones:
    if not is_rule:
        board.Remove(zone); z += 1
print(f"ripped {n} tracks, {z} zones")
x0, y0, x1, y1 = pads["bbox"]
ins = 0.4
for netname, layer in (("GND", pcbnew.In1_Cu), ("+3V3", pcbnew.In2_Cu)):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(board.FindNet(netname))
    for (xx, yy) in ((x0+ins,y0+ins),(x1-ins,y0+ins),(x1-ins,y1-ins),(x0+ins,y1-ins)):
        zone.AppendCorner(pcbnew.VECTOR2I(int(round(xx*1e6)), int(round(yy*1e6))), -1)
    zone.SetMinThickness(int(0.2*1e6)); zone.SetLocalClearance(int(0.3*1e6))
    zone.SetZoneName(f"{netname.replace('+','P').replace('/','_')}_PLANE")
    zone.SetAssignedPriority(1); board.Add(zone)
pcbnew.SaveBoard("Platvorm.kicad_pcb", board)
print("planes ok")
EOF
echo "=== drive_route ==="
$KIPY tools/drive_route.py Platvorm.kicad_pcb 2>&1 | grep -vE "stdpbase|memory leak|Debug" | tail -2
echo "=== fix_fb_io4 ==="
$KIPY tools/fix_fb_io4.py Platvorm.kicad_pcb 2>&1 | grep -vE "stdpbase|memory leak|Debug" | tail -1
echo "=== drive_vias ==="
$KIPY tools/drive_vias.py Platvorm.kicad_pcb 2>&1 | grep -vE "stdpbase|memory leak|Debug|GetWidth" | tail -1
echo "=== fix P1 ==="
$KIPY tools/fix_drc2.py Platvorm.kicad_pcb P1 2>&1 | grep -vE "stdpbase|memory leak|Debug" | grep -E "\[P1\]"
echo "=== fix P2 ==="
$KIPY tools/fix_drc2.py Platvorm.kicad_pcb P2 2>&1 | grep -vE "stdpbase|memory leak|Debug" | grep -E "\[P2\]"
echo "=== fill ==="
$KIPY tools/fill_zones.py Platvorm.kicad_pcb 2>&1 | grep filled
echo "=== DRC ==="
kicad-cli pcb drc --severity-all --format json -o /tmp/drc/rebuild.json Platvorm.kicad_pcb 2>/dev/null
python3 -c "
import json, collections
d = json.load(open('/tmp/drc/rebuild.json'))
print('violations:', len(d['violations']), collections.Counter(v['type'] for v in d['violations']).most_common())
print('unconnected:', len(d.get('unconnected_items', [])))
"
