#!/usr/bin/env python3
"""Step 7: mirror the routed design rules into the GUI project file:
Power netclass (0.5 mm tracks) assigned to the 11 power nets, 0.7 mm default via.
Run AFTER layout_build.py (which resets the project file on save)."""
import json
import os

PRJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pro = os.path.join(PRJ, "Platvorm.kicad_pro")
j = json.load(open(pro))

classes = j["net_settings"]["classes"]
if isinstance(classes, dict):
    default = classes["Default"]
else:
    default = next(c for c in classes if c.get("name") == "Default")
power = {
    "bus_width": default.get("bus_width", 12),
    "clearance": 0.2,
    "diff_pair_gap": default.get("diff_pair_gap", 0.25),
    "diff_pair_via_gap": default.get("diff_pair_via_gap", 0.25),
    "diff_pair_width": default.get("diff_pair_width", 0.2),
    "line_style": default.get("line_style", 0),
    "microvia_diameter": default.get("microvia_diameter", 0.3),
    "microvia_drill": default.get("microvia_drill", 0.1),
    "name": "Power",
    "pcb_color": default.get("pcb_color", "rgba(0, 0, 0, 0.000)"),
    "priority": 0,
    "schematic_color": default.get("schematic_color", "rgba(0, 0, 0, 0.000)"),
    "track_width": 0.5,
    "tuning_profile": "",
    "via_diameter": 0.7,
    "via_drill": 0.3,
}
if isinstance(classes, dict):
    classes["Power"] = power
else:
    classes[:] = [c for c in classes if c.get("name") != "Power"] + [power]

j["net_settings"]["netclass_assignments"] = {
    "+12V": "Power", "+12V_RAW": "Power", "+3V3": "Power", "+5V": "Power",
    "+5V_EURO": "Power", "-12V": "Power", "-12V_RAW": "Power", "VBUS": "Power",
    "VIN_BUCK": "Power", "VOUT_PRE": "Power", "SW": "Power",
}
default["via_diameter"] = 0.7
default["via_drill"] = 0.3

ds = j["board"]["design_settings"]
ds["rules"]["min_track_width"] = 0.1             # freerouting necks at fine-pitch escapes (PCBWay min 0.1)
ds["rules"]["min_copper_edge_clearance"] = 0.3
ds["rules"]["min_via_annular_width"] = 0.0
sv = ds["rule_severities"]
for k in ("courtyards_overlap", "silk_overlap", "silk_over_copper",
          "silk_edge_clearance", "padstack", "net_conflict"):
    sv[k] = "ignore"

json.dump(j, open(pro, "w"), indent=2)
print("kicad_pro: Power class, 0.7mm vias, edge 0.3, waivers applied")
