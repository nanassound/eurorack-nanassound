#!/usr/bin/env python3
"""Dump exact pad geometry + net map via pcbnew API (run under KiCad python)."""
import pcbnew, json, sys

b = pcbnew.LoadBoard("Platvorm.kicad_pcb")
out = {"footprints": {}, "outline": []}

# board outline
bbox = b.GetBoardEdgesBoundingBox()
out["bbox"] = [bbox.GetX() / 1e6, bbox.GetY() / 1e6,
               (bbox.GetX() + bbox.GetWidth()) / 1e6,
               (bbox.GetY() + bbox.GetHeight()) / 1e6]

for fp in b.GetFootprints():
    ref = fp.GetReference()
    pads = []
    for p in fp.Pads():
        pos = p.GetPosition(); sz = p.GetSize()
        bb = p.GetBoundingBox()  # includes custom-shape primitives, board frame
        pads.append({
            "num": p.GetNumber(),
            "net": p.GetNetname(),
            "x": pos.x / 1e6, "y": pos.y / 1e6,
            "w": bb.GetWidth() / 1e6, "h": bb.GetHeight() / 1e6,
            "rot": 0.0,  # bbox already in board frame
            "drill": (p.GetDrillSize().x / 1e6) if p.GetDrillSize().x else 0.0,
            "attr": int(p.GetAttribute()),
            "shape": int(p.GetShape()),
            "layers": [],
        })
        for lay in ("F.Cu", "B.Cu"):
            lid = pcbnew.B_Cu if lay == "B.Cu" else pcbnew.F_Cu
            if p.IsOnLayer(lid): pads[-1]["layers"].append(lay)
    out["footprints"][ref] = {
        "value": fp.GetValue(),
        "x": fp.GetPosition().x / 1e6, "y": fp.GetPosition().y / 1e6,
        "layer": "F.Cu" if fp.GetLayer() == pcbnew.F_Cu else "B.Cu",
        "courtyard": [c / 1e6 for c in (
            fp.GetCourtyard(pcbnew.F_CrtYd).GetX(),
            fp.GetCourtyard(pcbnew.F_CrtYd).GetY(),
            fp.GetCourtyard(pcbnew.F_CrtYd).GetRight(),
            fp.GetCourtyard(pcbnew.F_CrtYd).GetBottom())] if fp.GetCourtyard(pcbnew.F_CrtYd).GetWidth() > 0 else None,
        "pads": pads,
    }

# net -> physical pad list (exclude unconnected)
nets = {}
for ref, f in out["footprints"].items():
    for p in f["pads"]:
        n = p["net"]
        if not n or n.startswith("unconnected"): continue
        nets.setdefault(n, []).append(f"{ref}.{p['num']}")
out["nets"] = nets
json.dump(out, open("analysis/helpers/pads_api.json", "w"), indent=1)
print("footprints:", len(out["footprints"]), "nets:", len(nets))
print("bbox:", out["bbox"])
