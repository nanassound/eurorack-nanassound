#!/usr/bin/env python3
"""Restore strict (fab-safe) DRC rules in Platvorm.kicad_pro — un-do the loosening."""
import json

P = "Platvorm.kicad_pro"
d = json.load(open(P))
rules = d["board"]["design_settings"]["rules"]
rules.update({
    "min_clearance": 0.2,
    "min_track_width": 0.2,
    "min_through_hole_diameter": 0.3,
    "min_via_diameter": 0.6,
    "min_via_annular_width": 0.15,
    "min_annular_width": 0.15,
    "min_connection": 0.2,
    "min_hole_clearance": 0.25,
    "min_hole_to_hole": 0.25,
    "min_copper_edge_clearance": 0.3,
    "min_silk_clearance": 0.0,
    "min_resolved_spokes": 2,
})
d["board"]["design_settings"]["defaults"]["zones"]["min_clearance"] = 0.3
json.dump(d, open(P, "w"), indent=2)
print("rules restored:", {k: rules[k] for k in
      ("min_clearance", "min_track_width", "min_via_diameter", "min_copper_edge_clearance")})
