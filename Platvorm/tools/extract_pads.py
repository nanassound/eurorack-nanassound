#!/usr/bin/env python3
"""Extract exact pad geometry (absolute coords) + board state from Platvorm.kicad_pcb."""
import json, math, sys
sys.path.insert(0, "/Users/asepbagja/.agents/skills/kicad/scripts")
from sexp_parser import parse_file, find_all, find_first, get_value

board = parse_file("Platvorm.kicad_pcb")

# --- net name -> code mapping from board's net declarations
net_ids = {}
# KiCad 10: pads/zones reference nets by name only — no numeric net table.

def xform(fp_at, fp_rot, pad_at, unlocked=False):
    """footprint (at x y rot), pad (at x y rot) -> absolute x,y and total pad rotation."""
    fx, fy, fr = fp_at
    px, py, pr = pad_at
    r = math.radians(fr)
    # KiCad footprint rotation is CCW-positive in file coords; pad offset rotates with it
    ax = fx + px * math.cos(r) + py * math.sin(r)
    ay = fy - px * math.sin(r) + py * math.cos(r)
    return round(ax, 4), round(ay, 4), (fr + pr) % 360

out = {"footprints": {}, "outline": []}
edge = []
for gr in find_all(board, "gr_line"):
    if find_first(gr, "layer") == "Edge.Cuts":
        s = find_first(gr, "start"); e = find_first(gr, "end")
        edge.append([float(s[1]), float(s[2]), float(e[1]), float(e[2])])
out["outline"] = edge

for fp in find_all(board, "footprint"):
    # (footprint LIB (layer X) (at x y rot) ... (pad ...) )
    at = find_first(fp, "at")
    fx, fy = float(at[1]), float(at[2])
    fr = float(at[3]) if len(at) > 3 and isinstance(at[3], (int, float)) else 0.0
    layer = find_first(fp, "layer")
    # reference
    ref = None
    for pr in find_all(fp, "property"):
        if pr[1] == "Reference":
            ref = pr[2]
    val = None
    for pr in find_all(fp, "property"):
        if pr[1] == "Value":
            val = pr[2]
    pads = []
    for pad in find_all(fp, "pad"):
        pat = find_first(pad, "at")
        px, py = float(pat[1]), float(pat[2])
        prr = float(pat[3]) if len(pat) > 3 and isinstance(pat[3], (int, float)) else 0.0
        unlocked = find_first(pad, "unlocked") is not None
        ax, ay, trot = (fx, fy, fr) if unlocked else xform((fx, fy, fr), fr, (px, py, prr))
        sz = find_first(pad, "size")
        w, h = float(sz[1]), float(sz[2])
        drill = find_first(pad, "drill")
        d = float(drill[1]) if drill and len(drill) > 1 and isinstance(drill[1], (int, float)) else 0.0
        net = find_first(pad, "net")
        netname = net[1] if net else None
        layers = find_first(pad, "layers")
        pad_layers = [l for l in layers[1:] if isinstance(l, str)] if layers else []
        # rect pad effective box after rotation (rot multiples of 90 for most)
        pads.append({
            "num": pad[1], "net": netname, "x": ax, "y": ay, "w": w, "h": h,
            "rot": trot, "drill": d, "shape": pad[2],
            "tht": "thru_hole" in pad[1] if isinstance(pad[1], str) else False,
            "layers": pad_layers,
        })
    # courtyard bbox
    cmin = [1e9, 1e9]; cmax = [-1e9, -1e9]
    for kind in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc"):
        for sh in find_all(fp, kind):
            if find_first(sh, "layer") != "F.CrtYd" and find_first(sh, "layer") != "B.CrtYd":
                continue
            pts = []
            for kw in ("start", "end", "mid", "center"):
                p = find_first(sh, kw)
                if p: pts.append((float(p[1]), float(p[2])))
            for it in find_all(sh, "pts"):
                for pt in it:
                    if isinstance(pt, list) and pt and pt[0] == "xy":
                        pts.append((float(pt[1]), float(pt[2])))
            for (x, y) in pts:
                # transform to absolute (rotation about fp origin)
                r = math.radians(fr)
                axx = fx + x * math.cos(r) + y * math.sin(r)
                ayy = fy - x * math.sin(r) + y * math.cos(r)
                cmin[0] = min(cmin[0], axx); cmin[1] = min(cmin[1], ayy)
                cmax[0] = max(cmax[0], axx); cmax[1] = max(cmax[1], ayy)
    out["footprints"][ref] = {
        "value": val, "x": fx, "y": fy, "rot": fr, "layer": layer,
        "courtyard": [cmin[0], cmin[1], cmax[0], cmax[1]] if cmin[0] < 1e8 else None,
        "pads": pads,
    }

json.dump(out, open("analysis/helpers/pads_abs.json", "w"), indent=1)
print(f"{len(out['footprints'])} footprints, {sum(len(f['pads']) for f in out['footprints'].values())} pads")
print("outline segments:", len(edge))

