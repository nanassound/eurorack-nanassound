#!/usr/bin/env python3
"""Generate the EuroPlatvorm stack-reference symbol + footprint pair.

Deliverables
------------
- Symbol  `EuroPlatvorm`            -> appended to platvorm.kicad_sym
- Footprint `EuroPlatvorm_Daughter` -> footprints/platvorm_custom.pretty/

The footprint is the *mating field* for the two 1x14 2.54 mm back-side
headers (platform J3/J4) plus the platform board outline as a mechanical
reference on Dwgs.User, so I/O daughter-board designers can place the
platform in their schematic and PCB.

Frames
------
Platform KiCad frame (front view):  x right, y down.
J3 at (137.22, 71.5) LEFT  (power + GPIO0-7 + USB), pins 1..14 running DOWN.
J4 at (149.9,  71.5) RIGHT (GPIO23..8),               pins 1..14 running DOWN.
Headers are THT on the platform BACK (B.Cu) -> a daughter board stacks
back-to-back.  The daughter's KiCad front view equals the platform seen
from behind, i.e. mirrored about the vertical axis, y preserved:

    x_d = 143.56 - x_p        (143.56 = midpoint of the two pin-1 positions)
    y_d = y_p   - 71.5

Footprint origin = midpoint between the rows on the pin-1 line:
    J4 row (platform) at x = -6.34   (LEFT  in daughter view)
    J3 row (platform) at x = +6.34   (RIGHT in daughter view)
    pin k at y = (k-1)*2.54, pin 1 at TOP (y=0), pin 14 at y=33.02.

Every coordinate below is derived from EuroPlatvorm.kicad_pcb and asserted
against the raw pad positions before anything is written.
"""

import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
while not (ROOT / "EuroPlatvorm.kicad_pcb").exists():
    if ROOT == ROOT.parent:
        raise SystemExit("EuroPlatvorm.kicad_pcb not found upward from script")
    ROOT = ROOT.parent
PCB = ROOT / "EuroPlatvorm.kicad_pcb"
SYM_LIB = ROOT / "platvorm.kicad_sym"
FP_DIR = ROOT / "footprints" / "platvorm_custom.pretty"
FP_FILE = FP_DIR / "EuroPlatvorm_Daughter.kicad_mod"

NS = uuid.UUID("d5f0f001-0000-4000-8000-00e1b2c3d4f5")


def u(seed: str) -> str:
    return str(uuid.uuid5(NS, "europlatvorm-daughter/" + seed))


def f(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s

# ---------------------------------------------------------------- ground truth
# Platform J3/J4 pinout, taken from the PCB pad net assignments.
J3_NETS = ["+3V3", "+12V", "-12V", "GPIO0", "GPIO1", "GPIO2", "GPIO3",
           "GPIO4", "GPIO5", "GPIO6", "GPIO7", "USB_DP", "USB_DM", "GND"]
J4_NETS = ["GPIO23", "GPIO22", "GPIO21", "GPIO20", "GPIO19", "GPIO18",
           "GPIO17", "GPIO16", "GPIO15", "GPIO11", "GPIO10", "GPIO9",
           "GPIO8", "GND"]

J3_POS = (137.22, 71.5)   # footprint origin, 180 deg, B.Cu
J4_POS = (149.9, 71.5)
ROW_DX = 12.68            # J4.x - J3.x  (deliberately NOT 12.70)
PITCH = 2.54
OUTLINE = (132.7, 47.75, 154.4, 137.5)   # Edge.Cuts rect x1 y1 x2 y2
MODULE_CRTYD_TOP_YP = 41.6               # U4 courtyard top (antenna end)
MODULE_X_P = (135.01, 153.01)            # U4 18 mm module x extent
USBC_POS = (143.73, 133.28)              # platform J2

# daughter frame helpers
CX = (J3_POS[0] + J4_POS[0]) / 2.0       # 143.56
def xd(xp): return CX - xp
def yd(yp): return yp - J3_POS[1]

ROW_J3 = +ROW_DX / 2.0                   # +6.34  right bank
ROW_J4 = -ROW_DX / 2.0                   # -6.34  left bank
OUTL_D = (xd(OUTLINE[2]), yd(OUTLINE[1]), xd(OUTLINE[0]), yd(OUTLINE[3]))
ANT_X1, ANT_X2 = xd(MODULE_X_P[1]), xd(MODULE_X_P[0])
ANT_Y1 = yd(MODULE_CRTYD_TOP_YP)   # module courtyard top  -> -29.9
ANT_Y2 = yd(49.39)                 # first U4 pad row y_p  -> -22.11

# ------------------------------------------------- parse + verify from the PCB
def pcb_footprint_chunks(txt):
    """Split the PCB text into per-footprint chunks.

    Each chunk starts at a top-level ``(footprint "..."`` boundary and runs
    to the next boundary; trailing non-footprint items (gr_*, zones) carry
    no pads and never precede the chunk's own footprint content.
    """
    for chunk in txt.split('\n\t(footprint "')[1:]:
        yield chunk

def pcb_pad_map(txt, ref):
    for chunk in pcb_footprint_chunks(txt):
        mref = re.search(r'\(property "Reference" "' + ref + r'"', chunk)
        if not mref:
            continue
        head = chunk[: mref.start()]
        assert '(layer "B.Cu")' in head[:200], f"{ref}: not a B.Cu footprint"
        at = re.search(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)', chunk)
        fx, fy = float(at.group(1)), float(at.group(2))
        rot = float(at.group(3) or 0)
        assert abs(rot - 180) < 1e-9, f"{ref}: unexpected rotation {rot}"
        pads = {}
        for num, px, py, net in re.findall(
                r'\(pad "(\d+)" thru_hole \w+[\s\S]{0,60}?\(at ([\d.\-]+) ([\d.\-]+)[\s\S]{0,220}?\(net "([^"]+)"\)', chunk):
            pads[int(num)] = (float(px), float(py), net)
        assert len(pads) == 14, f"{ref}: expected 14 pads, got {len(pads)}"
        return fx, fy, pads
    raise AssertionError(f"{ref}: footprint not found")

def main():
    txt = PCB.read_text()
    j3x, j3y, j3pads = pcb_pad_map(txt, "J3")
    j4x, j4y, j4pads = pcb_pad_map(txt, "J4")
    assert (j3x, j3y) == J3_POS and (j4x, j4y) == J4_POS, "J3/J4 origin moved"
    assert abs((j4x - j3x) - ROW_DX) < 1e-9
    for k in range(1, 15):
        assert j3pads[k][2].lstrip("/") == J3_NETS[k - 1], f"J3.{k}: {j3pads[k][2]} != {J3_NETS[k-1]}"
        assert j4pads[k][2].lstrip("/") == J4_NETS[k - 1], f"J4.{k}: {j4pads[k][2]} != {J4_NETS[k-1]}"
        # platform pad k local (0, -(k-1)*2.54) at rot 180 -> global (x, y + (k-1)*2.54)
        exp_j3 = (j3x, j3y + (k - 1) * PITCH)
        exp_j4 = (j4x, j4y + (k - 1) * PITCH)
        got_j3 = (j3x - j3pads[k][0], j3y - j3pads[k][1])   # footprint rot 180
        got_j4 = (j4x - j4pads[k][0], j4y - j4pads[k][1])
        assert all(abs(a - b) < 1e-6 for a, b in zip(got_j3, exp_j3)), f"J3 pad {k} unexpected"
        assert all(abs(a - b) < 1e-6 for a, b in zip(got_j4, exp_j4)), f"J4 pad {k} unexpected"

    # daughter-frame expected pad centres for our footprint
    exp = {}   # pad number -> (x, y)
    for k in range(1, 15):
        exp[k] = (ROW_J3, (k - 1) * PITCH)          # symbol pins 1..14  = platform J3
        exp[14 + k] = (ROW_J4, (k - 1) * PITCH)     # symbol pins 15..28 = platform J4
    # cross-check against mirrored platform coords
    for k in range(1, 15):
        pj3 = (j3x, j3y + (k - 1) * PITCH)
        pj4 = (j4x, j4y + (k - 1) * PITCH)
        for got, want in ((exp[k], (xd(pj3[0]), yd(pj3[1]))),
                          (exp[14 + k], (xd(pj4[0]), yd(pj4[1])))):
            assert all(abs(a - b) < 1e-6 for a, b in zip(got, want)), (got, want)

    fp = gen_footprint(exp)
    FP_FILE.write_text(fp)

    sym = gen_symbol()
    lib = SYM_LIB.read_text()
    if '(symbol "EuroPlatvorm"' in lib:
        lib = re.sub(r'\t\(symbol "EuroPlatvorm"[\s\S]*?\n\t\)\n', "", lib, count=1)
    lib = lib.rstrip()
    assert lib.endswith(")")
    lib = lib[:-1].rstrip() + "\n" + sym + ")\n"
    SYM_LIB.write_text(lib)

    print(f"footprint: {FP_FILE.relative_to(ROOT)} ({len(fp)} bytes)")
    print(f"symbol:    {SYM_LIB.relative_to(ROOT)} (EuroPlatvorm)")
    print(f"outline in daughter frame: x [{f(OUTL_D[0])}, {f(OUTL_D[2])}]  y [{f(OUTL_D[1])}, {f(OUTL_D[3])}]")
    print(f"antenna zone: x [{f(ANT_X1)}, {f(ANT_X2)}]  y [{f(ANT_Y1)}, {f(ANT_Y2)}]")

# ------------------------------------------------------------------ footprint
def silk_label(net):
    short = {"+3V3": "3V3", "+12V": "+12", "-12V": "-12", "USB_DP": "DP",
             "USB_DM": "DM", "GND": "GND"}
    return short.get(net, "G" + net[4:])

def line(l, x1, y1, x2, y2, w, layer, seed):
    return (f"\t(fp_line\n\t\t(start {f(x1)} {f(y1)})\n\t\t(end {f(x2)} {f(y2)})\n"
            f"\t\t(stroke\n\t\t\t(width {f(w)})\n\t\t\t(type solid)\n\t\t)\n"
            f'\t\t(layer "{layer}")\n\t\t(uuid "{u(seed)}")\n\t)\n')

def rect(x1, y1, x2, y2, w, layer, seed):
    return (f"\t(fp_rect\n\t\t(start {f(x1)} {f(y1)})\n\t\t(end {f(x2)} {f(y2)})\n"
            f"\t\t(stroke\n\t\t\t(width {f(w)})\n\t\t\t(type solid)\n\t\t)\n"
            f'\t\t(fill no)\n\t\t(layer "{layer}")\n\t\t(uuid "{u(seed)}")\n\t)\n')

def text(kind, s, x, y, rot, layer, size, thick, seed, justify=None, hide=False):
    j = f"\n\t\t\t(justify {justify})" if justify else ""
    hide_s = "\n\t\t(hide yes)" if hide else ""
    return (f'\t(fp_text {kind} "{s}"\n\t\t(at {f(x)} {f(y)}{f" {rot}" if rot else ""})'
            f'{hide_s}\n\t\t(layer "{layer}")\n\t\t(uuid "{u(seed)}")\n'
            f"\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {f(size)} {f(size)})\n"
            f"\t\t\t\t(thickness {f(thick)})\n\t\t\t){j}\n\t\t)\n\t)\n")

def pad(num, x, y, shape, fn, seed):
    st = "\t\t(pinfunction \"%s\")\n" % fn
    return (f'\t(pad "{num}" thru_hole {shape}\n\t\t(at {f(x)} {f(y)})\n'
            f"\t\t(size 1.7 1.7)\n\t\t(drill 1)\n\t\t(layers \"*.Cu\" \"*.Mask\")\n"
            f"\t\t(remove_unused_layers no)\n{st}"
            f'\t\t(uuid "{u(seed)}")\n\t)\n')


def gen_footprint(exp):
    o = []
    o.append('(footprint "EuroPlatvorm_Daughter"\n\t(version 20260206)\n'
             '\t(generator "kicad-footprint-generator")\n\t(generator_version "10.0")\n'
             '\t(layer "F.Cu")\n'
             '\t(descr "EuroPlatvorm carrier stack reference for I/O daughter boards. '
             'Mating field for the two platform back-side 1x14 2.54mm headers: right bank = platform J3 '
             '(+3V3, +12V, -12V, GPIO0-7, USB_DP/DM, GND), left bank = platform J4 (GPIO23-8, GND). '
             'Row spacing 12.68mm (matches platform exactly). Platform outline (21.7x89.75mm) shown on '
             'Dwgs.User; stack back-to-back, daughter B.Cu facing platform B.Cu.")\n'
             '\t(tags "eurorack platvorm europlatvorm carrier daughter shield stack reference esp32-c6")\n')
    # --- properties
    o.append('\t(property "Reference" "REF**"\n\t\t(at 0 -3.5 0)\n\t\t(layer "F.SilkS")\n'
             f'\t\t(uuid "{u("ref")}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n'
             "\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n")
    o.append('\t(property "Value" "EuroPlatvorm_Daughter"\n\t\t(at 0 37 0)\n\t\t(layer "F.Fab")\n'
             f'\t\t(uuid "{u("val")}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n'
             "\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n")
    o.append('\t(property "Datasheet" ""\n\t\t(at 0 0 0)\n\t\t(layer "F.Fab")\n\t\t(hide yes)\n'
             f'\t\t(uuid "{u("ds")}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
             "\t\t\t)\n\t\t)\n\t)\n")
    o.append('\t(property "Description" "EuroPlatvorm stack reference - place on I/O daughter board. '
             '2x1x14 2.54mm socket field, 12.68mm row spacing; platform outline on Dwgs.User."\n'
             '\t\t(at 0 0 0)\n\t\t(layer "F.Fab")\n\t\t(hide yes)\n'
             f'\t\t(uuid "{u("descr")}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
             "\t\t\t)\n\t\t)\n\t)\n")
    o.append("\t(attr through_hole)\n\t(duplicate_pad_numbers_are_jumpers no)\n")

    # --- silkscreen: per-row boxes, column titles, pin labels
    for cx, tag in ((ROW_J4, "J4"), (ROW_J3, "J3")):
        o.append(line("", cx - 1.38, -1.38, cx + 1.38, -1.38, 0.12, "F.SilkS", f"silk-top-{tag}"))
        o.append(line("", cx + 1.38, -1.38, cx + 1.38, 34.4, 0.12, "F.SilkS", f"silk-r-{tag}"))
        o.append(line("", cx - 1.38, 0, cx - 1.38, -1.38, 0.12, "F.SilkS", f"silk-ch1-{tag}"))
        o.append(line("", cx - 1.38, 0, cx - 1.38, 34.4, 0.12, "F.SilkS", f"silk-l-{tag}"))
        o.append(line("", cx - 1.38, 34.4, cx + 1.38, 34.4, 0.12, "F.SilkS", f"silk-bot-{tag}"))
        o.append(text("user", tag, cx, -2.9, 0, "F.SilkS", 1.0, 0.15, f"title-{tag}"))
    for k, net in enumerate(J3_NETS, 1):
        o.append(text("user", silk_label(net), 8.5, (k - 1) * PITCH, 0, "F.SilkS",
                      0.9, 0.12, f"lbl-j3-{k}", justify="left"))
    for k, net in enumerate(J4_NETS, 1):
        o.append(text("user", silk_label(net), -8.5, (k - 1) * PITCH, 0, "F.SilkS",
                      0.9, 0.12, f"lbl-j4-{k}", justify="right"))

    # --- fab: per-row outlines with pin-1 chamfer + reference
    for cx, tag in ((ROW_J4, "J4"), (ROW_J3, "J3")):
        o.append(line("", cx + 1.27, -1.27, cx + 1.27, 34.29, 0.1, "F.Fab", f"fab-r-{tag}"))
        o.append(line("", cx + 1.27, 34.29, cx - 1.27, 34.29, 0.1, "F.Fab", f"fab-bot-{tag}"))
        o.append(line("", cx - 0.635, -1.27, cx + 1.27, -1.27, 0.1, "F.Fab", f"fab-top-{tag}"))
        o.append(line("", cx - 1.27, -0.635, cx - 0.635, -1.27, 0.1, "F.Fab", f"fab-ch-{tag}"))
        o.append(line("", cx - 1.27, 34.29, cx - 1.27, -0.635, 0.1, "F.Fab", f"fab-l-{tag}"))
    o.append(text("user", "${REFERENCE}", 0, 16.51, 90, "F.Fab", 1.0, 0.15, "fab-ref"))

    # --- courtyard: connectors only (whole-platform courtyard would false-positive DRC)
    o.append(rect(-8.11, -1.78, 8.11, 34.8, 0.05, "F.CrtYd", "crtyd"))

    # --- Dwgs.User: platform mechanical reference
    o.append(rect(OUTL_D[0], OUTL_D[1], OUTL_D[2], OUTL_D[3], 0.15, "Dwgs.User", "plat-outline"))
    o.append(text("user", "EUROPLATVORM 21.7x89.75 OUTLINE (platform behind this board)",
                  0, -25.5, 0, "Dwgs.User", 1.0, 0.15, "note-outline"))
    o.append(rect(ANT_X1, ANT_Y1, ANT_X2, ANT_Y2, 0.15, "Dwgs.User", "ant-zone"))
    o.append(text("user", "ESP32-C6 ANTENNA - keep copper clear", 0, -31.5, 0, "Dwgs.User",
                  1.0, 0.15, "note-ant"))
    o.append(text("user", "platform USB-C below", xd(USBC_POS[0]), 64.5, 0, "Dwgs.User",
                  0.9, 0.15, "note-usbc"))
    o.append(text("user", "stack: daughter B.Cu faces platform B.Cu (back-to-back)",
                  0, 68, 0, "Dwgs.User", 1.0, 0.15, "note-stack"))

    # --- pads
    for k, net in enumerate(J3_NETS, 1):
        o.append(pad(k, exp[k][0], exp[k][1], "rect" if k == 1 else "circle", net, f"pad-{k}"))
    for k, net in enumerate(J4_NETS, 1):
        o.append(pad(14 + k, exp[14 + k][0], exp[14 + k][1],
                     "rect" if k == 1 else "circle", net, f"pad-{14+k}"))

    o.append("\t(embedded_fonts no)\n)\n")
    return "".join(o)

# --------------------------------------------------------------------- symbol
def etype(net):
    if net in ("+3V3", "+12V", "-12V", "GND"):
        return "power_out"
    return "bidirectional"

def pin(num, net, x, y, ang):
    return (f'\t\t(pin {etype(net)} line\n\t\t\t(at {f(x)} {f(y)} {ang})\n'
            f"\t\t\t(length 2.54)\n"
            f'\t\t\t(name "{net}"\n\t\t\t\t(effects\n\t\t\t\t\t(font (size 1.27 1.27)))\n\t\t\t\t)\n'
            f'\t\t\t(number "{num}"\n\t\t\t\t(effects\n\t\t\t\t\t(font (size 1.27 1.27)))\n\t\t\t\t)\n'
            "\t\t)\n")

def prop(name, val, x, y, hide=False, extra=""):
    h = "\n\t\t(hide yes)" if hide else ""
    return (f'\t\t(property "{name}" "{val}"\n\t\t\t(at {f(x)} {f(y)} 0){h}\n'
            f"\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n"
            f"\t\t\t(effects{extra}\n\t\t\t\t(font (size 1.27 1.27))\n\t\t\t)\n\t\t)\n")

def gen_symbol():
    o = []
    o.append('\t(symbol "EuroPlatvorm"\n'
             "\t\t(pin_names\n\t\t\t(offset 1.016)\n\t\t)\n"
             "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n")
    o.append(prop("Reference", "J", 0, 41.91))
    o.append(prop("Value", "EuroPlatvorm", 0, -6.35))
    o.append(prop("Footprint", "platvorm_custom:EuroPlatvorm_Daughter", 0, 0, hide=True))
    o.append(prop("Datasheet", "", 0, 0, hide=True))
    o.append(prop("Description",
                  "EuroPlatvorm carrier stack reference (ESP32-C6 eurorack platform). "
                  "Place on I/O daughter boards. Right bank = platform J3: +3V3/+12V/-12V, GPIO0-7, "
                  "USB_DP/USB_DM (native USB), GND. Left bank = platform J4: GPIO23..GPIO8, GND. "
                  "GPIO8/GPIO9 are boot strapping pins. Mates with 2x 1x14 2.54mm sockets, "
                  "12.68mm row spacing, platform back-to-back behind the daughter board.", 0, 0, hide=True))
    o.append(prop("ki_keywords", "eurorack platvorm europlatvorm carrier daughter shield esp32-c6", 0, 0, hide=True))
    o.append(prop("ki_fp_filters", "platvorm_custom:EuroPlatvorm*", 0, 0, hide=True))

    o.append('\t\t(symbol "EuroPlatvorm_0_1"\n'
             "\t\t\t(rectangle\n\t\t\t\t(start -7.62 -2.54)\n\t\t\t\t(end 7.62 38.1)\n"
             "\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n"
             "\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n"
             '\t\t\t(text "J4"\n\t\t\t\t(at -3.81 35.56 0)\n'
             "\t\t\t\t(effects\n\t\t\t\t\t(font (size 1.27 1.27))\n\t\t\t\t)\n\t\t\t)\n"
             '\t\t\t(text "J3"\n\t\t\t\t(at 3.81 35.56 0)\n'
             "\t\t\t\t(effects\n\t\t\t\t\t(font (size 1.27 1.27))\n\t\t\t\t)\n\t\t\t)\n"
             "\t\t)\n")

    o.append('\t\t(symbol "EuroPlatvorm_1_1"\n')
    for k in range(1, 15):   # right column = platform J3
        y = 33.02 - (k - 1) * PITCH
        o.append(pin(k, J3_NETS[k - 1], 10.16, y, 0))
    for k in range(1, 15):   # left column = platform J4
        y = 33.02 - (k - 1) * PITCH
        o.append(pin(14 + k, J4_NETS[k - 1], -10.16, y, 180))
    o.append("\t\t)\n\t\t(embedded_fonts no)\n\t)\n")
    return "".join(o)

if __name__ == "__main__":
    main()
