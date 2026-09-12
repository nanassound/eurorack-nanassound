#!/usr/bin/env python3
"""
Generate the Platvorm ESP32-C6 Eurorack Motherboard hierarchical schematic (KiCad 10).

Sheets:
  Platvorm.kicad_sch (root) -> power.kicad_sch, usb_uart.kicad_sch, esp32.kicad_sch, gpio.kicad_sch

Connection style: every pin gets a 2.54 mm stub; nets are joined by labels
(local, hierarchical) or power symbols. No trunk wiring, no junctions.

Usage: python3 tools/gen_schematic.py [--emit]   # default: dry-run checks
"""
import os, re, sys, uuid as uuidlib

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS = os.environ.get("KICAD_SYMBOL_DIR",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
ROOT_UUID = "f79e860c-3d6a-4d51-9bda-7bb8cbb8a9ec"
PROJECT = "Platvorm"
VERSION = "20260306"
GENVER = "10.0"

def U(): return str(uuidlib.uuid4())

# ---------------------------------------------------------------- lib symbols
_sym_cache = {}
PCM_SYMBOLS = os.path.expanduser(
    "~/Documents/KiCad/10.0/3rdparty/symbols/com_github_espressif_kicad-libraries")

def extract_symbol(lib, name):
    """Return raw text of a top-level symbol def from a .kicad_sym library."""
    key = (lib, name)
    if key in _sym_cache: return _sym_cache[key]
    path = os.path.join(LIBS, lib + ".kicad_sym")
    if not os.path.exists(path):
        candidates = [os.path.join(PCM_SYMBOLS, lib + ".kicad_sym"),
                      os.path.join(PCM_SYMBOLS, lib.replace("PCM_", "") + ".kicad_sym")]
        path = next((c for c in candidates if os.path.exists(c)), candidates[0])
    txt = open(path).read()
    i = txt.find(f'(symbol "{name}"')
    if i < 0: raise KeyError(f"{lib}:{name} not found")
    depth = 0
    for j in range(i, len(txt)):
        if txt[j] == '(': depth += 1
        elif txt[j] == ')':
            depth -= 1
            if depth == 0:
                out = txt[i:j+1]
                _sym_cache[key] = out
                return out
    raise RuntimeError("unbalanced parens in " + lib)

def parse_pins(symtext):
    """[(number, name, x, y, angle, etype)] — pin (at) is the connection point."""
    pins, seen = [], set()
    for m in re.finditer(r'\(pin\s+(\w+)\s+(\w+)', symtext):
        depth, i = 0, m.start()
        for j in range(i, len(symtext)):
            if symtext[j] == '(': depth += 1
            elif symtext[j] == ')':
                depth -= 1
                if depth == 0: break
        block = symtext[i:j+1]
        at = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)', block)
        nm = re.search(r'\(name\s+"([^"]*)"', block)
        num = re.search(r'\(number\s+"([^"]*)"', block)
        if not (at and num): continue
        n = num.group(1)
        if n in seen: continue
        seen.add(n)
        pins.append(dict(number=n, name=(nm.group(1) if nm else ""),
                         x=float(at.group(1)), y=float(at.group(2)),
                         a=int(at.group(3)), etype=m.group(1)))
    return pins

def qualify(symtext, lib, name):
    """Rename root node of extracted def to lib-qualified name (first occurrence)."""
    return symtext.replace(f'(symbol "{name}"', f'(symbol "{lib}:{name}"', 1)

def resolve_pinmap(pins, pinmap):
    """Expand pin keys to every matching pin (by number or by name). -> {number: spec}"""
    out = {}
    for key, spec in pinmap.items():
        matches = [p for p in pins if p["number"] == key or p["name"] == key]
        if not matches:
            raise KeyError(f"pin {key!r} not found; have {[(p['number'], p['name']) for p in pins]}")
        for p in matches:
            out[p["number"]] = spec
    return out

# ------------------------------------------------------------- ESP32 symbol
ESP32_PINS_RIGHT = [("IO0","8"),("IO1","9"),("IO2","27"),("IO3","26"),("IO4","4"),
    ("IO5","5"),("IO6","6"),("IO7","7"),("IO10","11"),("IO11","12"),("IO15","23"),
    ("IO18","16"),("IO19","17"),("IO20","18"),("IO21","19"),("IO22","20"),("IO23","21")]
ESP32_PINS_LEFT = [("EN","3"),("IO8","10"),("IO9","15"),("IO12","13"),("IO13","14"),
    ("RXD0","24"),("TXD0","25")]

def esp32_symbol_def():
    half = 22.86          # body half height (mm)
    wid = 11.43           # body half width
    n = len(ESP32_PINS_RIGHT)
    y0 = -((n - 1) * 2.54) / 2.0          # -20.32
    pins = []
    for k, (nm, num) in enumerate(ESP32_PINS_RIGHT):
        y = y0 + k * 2.54
        pins.append(f'\t\t\t(pin bidirectional line (at 15.24 {y} 180) (length 2.54)\n'
                    f'\t\t\t\t(name "{nm}" (effects (font (size 1.27 1.27))))\n'
                    f'\t\t\t\t(number "{num}" (effects (font (size 1.27 1.27)))))')
    ly = [-7.62, -5.08, -2.54, 0.0, 2.54, 5.08, 7.62]
    for (nm, num), y in zip(ESP32_PINS_LEFT, ly):
        pins.append(f'\t\t\t(pin bidirectional line (at -15.24 {y} 0) (length 2.54)\n'
                    f'\t\t\t\t(name "{nm}" (effects (font (size 1.27 1.27))))\n'
                    f'\t\t\t\t(number "{num}" (effects (font (size 1.27 1.27)))))')
    pins.append('\t\t\t(pin power_in line (at 0 25.4 270) (length 2.54)\n'
                '\t\t\t\t(name "3V3" (effects (font (size 1.27 1.27))))\n'
                '\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))')
    for x, num in [(-5.08, "1"), (0.0, "28"), (5.08, "29")]:
        pins.append(f'\t\t\t(pin power_in line (at {x} -25.4 90) (length 2.54)\n'
                    f'\t\t\t\t(name "GND" (effects (font (size 1.27 1.27))))\n'
                    f'\t\t\t\t(number "{num}" (effects (font (size 1.27 1.27)))))')
    pins_s = "\n".join(pins)
    return f'''\t\t(symbol "platvorm:ESP32-C6-WROOM-1"
\t\t\t(pin_names (offset 1.016))
\t\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)
\t\t\t(property "Reference" "U" (at 0 -24.13 0) (effects (font (size 1.27 1.27))))
\t\t\t(property "Value" "ESP32-C6-WROOM-1" (at 0 24.13 0) (effects (font (size 1.27 1.27))))
\t\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t\t(property "Datasheet" "https://www.espressif.com/sites/default/files/documentation/esp32-c6-wroom-1_wroom-1u_datasheet_en.pdf" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t\t(property "Description" "WiFi 6 / BLE 5 / 802.15.4 module, ESP32-C6, 8 MB flash" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t\t(symbol "ESP32-C6-WROOM-1_0_1"
\t\t\t\t(rectangle (start -{wid} {half}) (end {wid} -{half})
\t\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t\t(fill (type background))
\t\t\t\t)
\t\t\t)
\t\t\t(symbol "ESP32-C6-WROOM-1_1_1"
{pins_s}
\t\t\t)
\t\t)'''

VBUS_DEF = None  # built lazily from power:+5V

def vbus_symbol_def():
    global VBUS_DEF
    if VBUS_DEF is None:
        d = extract_symbol("power", "+5V")
        d = d.replace('+5V', 'VBUS')
        VBUS_DEF = d
    return VBUS_DEF

# ------------------------------------------------------------------- builder
class Sheet:
    def __init__(self, name, page, parent_path):
        self.name, self.page, self.parent_path = name, page, parent_path
        self.uuid = U()
        self.items = []            # s-expr lines
        self.libs = {}             # (lib,name) -> text
        self.hlabels = {}          # net -> shape
        self._pwr_n = 100

    def need(self, lib, name):
        if (lib, name) not in self.libs:
            src = esp32_symbol_def() if (lib, name) == ("platvorm", "ESP32-C6-WROOM-1") \
                else vbus_symbol_def() if (lib, name) == ("power", "VBUS") \
                else extract_symbol(lib, name)
            src = qualify(src, lib, name)
            m = re.search(r'\(extends "([^"]+)"\)', src)
            if m:
                parent = m.group(1)
                self.need(lib, parent)   # embed qualified parent first
                src = src.replace(f'(extends "{parent}"', f'(extends "{lib}:{parent}"', 1)
            self.libs[(lib, name)] = src
        return self.libs[(lib, name)]

    def add(self, s): self.items.append(s)

    def wire(self, x1, y1, x2, y2):
        x1, y1, x2, y2 = [round(v, 4) for v in (x1, y1, x2, y2)]
        self.add(f'\t(wire (pts (xy {x1} {y1}) (xy {x2} {y2})) (stroke (width 0) (type default)) (uuid "{U()}"))')

    def label(self, net, x, y, angle=0):
        x, y = round(x, 4), round(y, 4)
        just = "left bottom" if angle == 0 else "right bottom"
        self.add(f'\t(label "{net}" (at {x} {y} {angle}) (effects (font (size 1.27 1.27)) (justify {just})) (uuid "{U()}"))')
    def glabel(self, net, x, y, angle=0):
        x, y = round(x, 4), round(y, 4)
        just = "left" if angle == 0 else "right"
        self.add(f'\t(global_label "{net}" (shape passive) (at {x} {y} {angle}) '
                 f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{U()}"))')

    def hlabel(self, net, x, y, angle=0, shape="passive"):
        x, y = round(x, 4), round(y, 4)
        self.hlabels.setdefault(net, shape)
        just = "left bottom" if angle == 0 else "right bottom"
        self.add(f'\t(hierarchical_label "{net}" (shape {shape}) (at {x} {y} {angle}) (effects (font (size 1.27 1.27)) (justify {just})) (uuid "{U()}"))')

    def nconnect(self, x, y):
        x, y = round(x, 4), round(y, 4)
        self.add(f'\t(no_connect (at {x} {y}) (uuid "{U()}"))')


    def text(self, s, x, y, size=3.5):
        x, y = round(x, 4), round(y, 4)
        self.add(f'\t(text "{s}" (exclude_from_sim no) (at {x} {y} 0) (effects (font (size {size} {size}) (bold yes)) (justify left bottom)) (uuid "{U()}"))')

    def next_pwr(self):
        self._pwr_n += 1
        return f"#PWR0{self._pwr_n}"

    def psym(self, net, x, y, rot=0, flag=False):
        """Power symbol; always rot 0. Rail value above arrow, GND value hidden."""
        x, y = round(x, 4), round(y, 4)
        self.need("power", net)
        ref = self.next_pwr()
        is_gnd = net == "GND"
        val_y = y + 3.81 if is_gnd else y - 3.81
        val_vis = " (hide yes)" if is_gnd else ""
        self.add(f'\t(symbol (lib_id "power:{net}") (at {x} {y} 0) (unit 1)\n'
                 f'\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
                 f'\t\t(uuid "{U()}")\n'
                 f'\t\t(property "Reference" "{ref}" (at {x} {val_y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(property "Value" "{net}" (at {x} {val_y} 0) (effects (font (size 1.27 1.27)) (justify left){val_vis}))\n'
                 f'\t\t(property "Footprint" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(property "Datasheet" "~" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(property "Description" "Power symbol" (at {x} {y} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(instances (project "{PROJECT}" (path "{self.parent_path}" (reference "{ref}") (unit 1))))\n'
                 f'\t)')

    def pwr_flag(self, x, y):
        x, y = round(x, 4), round(y, 4)
        """PWR_FLAG whose pin connects at (x,y): wire up 2.54, flag above."""
        self.need("power", "PWR_FLAG")
        ref = self.next_pwr()
        self.wire(x, y, x, y - 2.54)
        self.add(f'\t(symbol (lib_id "power:PWR_FLAG") (at {x} {y - 2.54} 0) (unit 1)\n'
                 f'\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
                 f'\t\t(uuid "{U()}")\n'
                 f'\t\t(property "Reference" "{ref}" (at {x} {y - 6.35} 0) (effects (font (size 1.27 1.27)) (justify left) (hide yes)))\n'
                 f'\t\t(property "Value" "PWR_FLAG" (at {x} {y + 0.0} 0) (effects (font (size 1.27 1.27)) (justify left) (hide yes)))\n'
                 f'\t\t(property "Footprint" "" (at {x} {y - 2.54} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(property "Datasheet" "~" (at {x} {y - 2.54} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(property "Description" "Power flag" (at {x} {y - 2.54} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
                 f'\t\t(instances (project "{PROJECT}" (path "{self.parent_path}" (reference "{ref}") (unit 1))))\n'
                 f'\t)')

    def place(self, ref, lib, name, at, value, fp, mpn, lcsc, pinmap, datasheet="~", desc="",
              ref_off=None, val_off=None):
        deftxt = self.need(lib, name)
        pins = parse_pins(deftxt)
        if not pins:
            m = re.search(r'\(extends "([^"]+)"\)', deftxt)
            if m:
                parent = m.group(1).split(":")[-1]
                pins = parse_pins(self.need(lib, parent))
        x0 = round(round(at[0] / 1.27) * 1.27, 4)
        y0 = round(round(at[1] / 1.27) * 1.27, 4)
        rot = at[2]
        resolved = resolve_pinmap(pins, pinmap)
        bynum = {p["number"]: p for p in pins}
        props = [
            ("Reference", ref, f'(at {round(x0 + (ref_off or (0, -3.81))[0],4)} {round(y0 + (ref_off or (0, -3.81))[1],4)} 0)', '(effects (font (size 1.27 1.27)))'),
            ("Value", value, f'(at {round(x0 + (val_off or (0, 3.81))[0],4)} {round(y0 + (val_off or (0, 3.81))[1],4)} 0)', '(effects (font (size 1.27 1.27)))'),
            ("Footprint", fp, f'(at {x0} {y0} 0)', '(effects (font (size 1.27 1.27)) (hide yes))'),
            ("Datasheet", datasheet, f'(at {x0} {y0} 0)', '(effects (font (size 1.27 1.27)) (hide yes))'),
            ("Description", desc, f'(at {x0} {y0} 0)', '(effects (font (size 1.27 1.27)) (hide yes))'),
            ("MPN", mpn, f'(at {x0} {y0} 0)', '(effects (font (size 1.27 1.27)) (hide yes))'),
            ("LCSC", lcsc, f'(at {x0} {y0} 0)', '(effects (font (size 1.27 1.27)) (hide yes))'),
        ]
        prop_s = "\n".join(
            f'\t\t(property "{k}" "{v}" {p} {e})' for k, v, p, e in props)
        pin_uuids = "\n".join(f'\t\t(pin "{p["number"]}" (uuid "{U()}"))' for p in pins)
        inst = f'\t\t(instances (project "{PROJECT}" (path "{self.parent_path}" (reference "{ref}") (unit 1))))'
        self.add(f'\t(symbol (lib_id "{lib}:{name}") (at {x0} {y0} {rot}) (unit 1)\n'
                 f'\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
                 f'\t\t(uuid "{U()}")\n{prop_s}\n{pin_uuids}\n{inst}\n\t)')
        # stubs + connections; axis-aligned from the pin angle.
        # symbol-lib y is UP, schematic y is DOWN: negate y on both position and direction.
        OUT = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}
        self.psym_spots = getattr(self, "psym_spots", [])
        r = rot % 360
        def xform(v):
            vx, vy = v
            if r == 90:  return -vy, vx
            if r == 180: return -vx, -vy
            if r == 270: return vy, -vx
            return vx, vy
        for num, spec in resolved.items():
            p = bynum[num]
            ex, ey = xform(OUT.get(p["a"] % 360, (0, -1)))
            xf = xform((p["x"], p["y"]))
            dx, dy = xf[0], -xf[1]
            px, py = x0 + dx, y0 + dy
            if spec == "X":
                self.nconnect(px, py)   # marker directly on the pin, no stub
                continue
            sx, sy = px + 2.54 * ex, py + 2.54 * ey
            self.wire(px, py, sx, sy)
            ang = 0 if ex > 0 else 180 if ex < 0 else (0 if ey < 0 else 180)
            if spec == "X":
                self.nconnect(sx, sy)
            elif spec.startswith("L:"):
                self.label(spec[2:], sx, sy, ang)
            elif spec.startswith("H:"):
                self.glabel(spec[2:], sx, sy, ang)
            elif spec.startswith("P:"):
                net = spec[2:]
                # rot-0 symbol at the stub end: arrows point up, GND hangs down,
                # so graphics never overlap horizontal or vertical stub wires
                self.psym(net, sx, sy, 0)
                self.psym_spots.append((net, sx, sy))
            elif spec.startswith("E:"):
                # extended-stub rail: 2.54 stub + 2.54 more outward, then rot-0 symbol
                net = spec[2:]
                ex2, ey2 = round(2.54 * ex, 4), round(2.54 * ey, 4)
                self.wire(sx, sy, sx + ex2, sy + ey2)
                self.psym(net, sx + ex2, sy + ey2, 0)
                self.psym_spots.append((net, sx + ex2, sy + ey2))
            elif spec.startswith("F:"):
                self.label(spec[2:], sx, sy, ang)
                self.f_spots = getattr(self, "f_spots", [])
                self.f_spots.append((spec[2:], sx, sy))
            else:
                raise ValueError(spec)
        return pins

    def render(self):
        libs = "\n".join(self.libs.values())
        return f'''(kicad_sch
\t(version {VERSION})
\t(generator "eeschema")
\t(generator_version "{GENVER}")
\t(uuid "{self.uuid}")
\t(paper "A4")
\t(title_block
\t\t(title "Platvorm - {self.name}")
\t\t(date "2026-09-12")
\t\t(rev "A")
\t\t(company "nanassound")
\t)
\t(lib_symbols
{libs}
\t)
{chr(10).join(self.items)}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "{self.page}")
\t\t)
\t)
\t(embedded_fonts no)
)
'''


def build_root(sheets):
    """Root sheet with 4 pinless sheet boxes (signals cross sheets via global labels)."""
    root_items = []
    boxes = [
        ("power", "Power Supply", 25, 40, 115, 55),
        ("usb_uart", "USB & UART Bridge", 160, 40, 115, 55),
        ("esp32", "ESP32-C6 Module", 25, 115, 115, 55),
        ("gpio", "GPIO Header", 160, 115, 115, 55),
    ]
    page = 2
    for fname, title, x, y, w, h in boxes:
        sh = next(s for s in sheets if SLUG[s.name] == fname)
        root_items.append(f'''\t(sheet (at {x} {y}) (size {w} {h})
\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
\t\t(fields_autoplaced yes)
\t\t(stroke (width 0.1524) (type solid))
\t\t(fill (color 0 0 0 0.0000))
\t\t(uuid "{sh.uuid}")
\t\t(property "Sheetname" "{title}" (at {x} {y - 1.27} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
\t\t(property "Sheetfile" "{fname}.kicad_sch" (at {x} {y + h + 1.27} 0) (effects (font (size 1.27 1.27)) (justify left top)))
\t\t(instances (project "{PROJECT}" (path "/" (page "{page}"))))
\t)''')
        page += 1
    body = "\n".join(root_items)
    return f'''(kicad_sch
\t(version {VERSION})
\t(generator "eeschema")
\t(generator_version "{GENVER}")
\t(uuid "{ROOT_UUID}")
\t(paper "A4")
\t(title_block
\t\t(title "Platvorm - ESP32-C6 Eurorack Motherboard")
\t\t(date "2026-09-12")
\t\t(rev "A")
\t\t(company "nanassound")
\t\t(comment 1 "Daughter-board platform: USB-C or Eurorack power, CH340C programming, 2x14 GPIO header")
\t)
\t(lib_symbols)
{body}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
\t(embedded_fonts no)
)
'''

# pin lists used on root sheet boxes (order = display order)
usb_sheet_pins = ["EN", "IO9", "U0RXD", "U0TXD"]
esp_sheet_pins = ["EN", "IO9", "U0RXD", "U0TXD"] + \
    [f"IO{i}" for i in [0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 15, 18, 19, 20, 21, 22, 23]]
gpio_sheet_pins = [f"IO{i}" for i in [0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 15, 18, 19, 20, 21, 22, 23]] + ["IO9"]

# ------------------------------------------------------------------- sheets
def sheet_power():
    s = Sheet("Power Supply", 2, "/" + ROOT_UUID)
    s.text("EURORACK + USB POWER - TPS54202 BUCK 3.3V", 25, 25)
    # Eurorack header J1: row-major top->bottom (pin1 top-left, stripe side)
    j1_map = {}
    rows = ["-12V_RAW", "-12V_RAW", "GND", "GND", "GND", "GND",
            "+12V_RAW", "+12V_RAW", "+5V_EURO", "+5V_EURO", "NC", "NC",
            "NC", "NC", "NC", "NC"]
    # Conn_02x08_Odd_Even: pins 1,2 = row1 L/R ... will assert numbering first
    for i, net in enumerate(rows, start=1):
        j1_map[str(i)] = "X" if net == "NC" else ("P:GND" if net == "GND" else f"F:{net}")
    s.place("J1", "Connector_Generic", "Conn_02x08_Odd_Even", (55, 105, 0),
            "Power Header 2x8", "Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical",
            "PZ254V-12-16P", "C492425", j1_map,
            desc="Eurorack power header, pin1 = -12V (red stripe)",
            ref_off=(0, -13.4), val_off=(0, 16.9))
    # protection / ORing diodes: pin1=K, pin2=A on D_Schottky
    s.place("D2", "Device", "D_Schottky", (105, 80, 180), "SS34", "Diode_SMD:D_SMA",
            "SS34", "C8678", {"1": "P:+12V", "2": "L:+12V_RAW"},
            desc="+12V series protection")
    s.place("D3", "Device", "D_Schottky", (105, 52, 180), "SS34", "Diode_SMD:D_SMA",
            "SS34", "C8678", {"1": "P:-12V", "2": "L:-12V_RAW"},
            desc="-12V series protection (reversed)")
    s.place("D4", "Device", "D_Schottky", (105, 108, 180), "SS34", "Diode_SMD:D_SMA",
            "SS34", "C8678", {"1": "P:+5V", "2": "L:+5V_EURO"},
            desc="Eurorack +5V to +5V rail")
    s.place("D1", "Device", "D_Schottky", (105, 140, 180), "SS34", "Diode_SMD:D_SMA",
            "SS34", "C8678", {"1": "P:+5V", "2": "P:VBUS"},
            desc="USB VBUS to +5V rail")
    s.place("D5", "Device", "D_Schottky", (152, 94, 180), "SS34", "Diode_SMD:D_SMA",
            "SS34", "C8678", {"1": "L:VIN_BUCK", "2": "P:+5V"},
            desc="+5V keeps board alive when JP1=12V and rack absent")
    # source-select jumper
    s.place("JP1", "Connector_Generic", "Conn_01x03", (135, 66, 0), "PSRC Select",
            "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
            "DZ254R-11-03-63", "C2935909",
            {"1": "P:+12V", "2": "L:VIN_BUCK", "3": "P:+5V"},
            desc="Buck source: pin1-2 = 12V, pin2-3 = 5V")
    # bulk caps
    s.place("C9", "Device", "C", (80, 160, 0), "10u", "Capacitor_SMD:C_0805_2012Metric",
            "CL21A106KAYNNNE", "C15850", {"1": "P:+12V", "2": "P:GND"}, desc="+12V rail bulk")
    s.place("C10", "Device", "C", (55, 160, 0), "10u", "Capacitor_SMD:C_0805_2012Metric",
            "CL21A106KAYNNNE", "C15850", {"1": "P:VBUS", "2": "P:GND"}, desc="VBUS bulk")
    s.place("C1", "Device", "C", (150, 135, 0), "10u", "Capacitor_SMD:C_0805_2012Metric",
            "CL21A106KAYNNNE", "C15850", {"1": "F:VIN_BUCK", "2": "P:GND"}, desc="Buck input")
    s.place("U2", "Regulator_Switching", "TPS54302", (175, 115, 0), "TPS54202DDCR",
            "Package_TO_SOT_SMD:SOT-23-6", "TPS54202DDCR", "C191884",
            {"1": "P:GND", "2": "L:SW", "3": "F:VIN_BUCK", "4": "L:FB", "5": "X",
             "6": "L:BOOT"},
            desc="2A buck, 500kHz, FB=0.6V; EN floats = enabled",
            ref_off=(0, -9.0), val_off=(0, 11.0))
    s.place("C7", "Device", "C", (195, 95, 0), "100n", "Capacitor_SMD:C_0402_1005Metric",
            "CL05B104KO5NNNC", "C1525", {"1": "L:BOOT", "2": "L:SW"}, desc="BOOT cap")
    s.place("R1", "Device", "R", (215, 130, 0), "100k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-07100KL", "C25741", {"1": "L:FB", "2": "F:VOUT_PRE"}, desc="FB high")
    s.place("R2", "Device", "R", (215, 145, 0), "22.1k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0722K1L", "C43473", {"1": "L:FB", "2": "P:GND"}, desc="FB low")
    s.place("L1", "Device", "L", (230, 115, 0), "10uH/2.45A",
            "platvorm_custom:IND-SMD_L6.0-W6.0", "YNR6045-100M", "C341067",
            {"1": "L:SW", "2": "F:VOUT_PRE"},
            desc="Magnetically shielded 10uH")
    s.place("C3", "Device", "C", (245, 135, 0), "22u", "Capacitor_SMD:C_0805_2012Metric",
            "CL21A226MAQNNNE", "C45783", {"1": "F:VOUT_PRE", "2": "P:GND"}, desc="Buck output")
    s.place("FB1", "Device", "FerriteBead", (260, 115, 180), "600R/3.5A",
            "Inductor_SMD:L_0805_2012Metric", "BLM21PG600SN1D", "C18305",
            {"1": "L:VOUT_PRE", "2": "P:+3V3"}, desc="Ripple filter to +3V3")
    s.place("C4", "Device", "C", (260, 145, 0), "10u", "Capacitor_SMD:C_0805_2012Metric",
            "CL21A106KAYNNNE", "C15850", {"1": "P:+3V3", "2": "P:GND"}, desc="+3V3 bulk")
    for net in ["VBUS", "+5V", "+12V", "-12V", "+3V3", "VIN_BUCK"]:
        spots = [sp for sp in (getattr(s, "psym_spots", []) + getattr(s, "f_spots", [])) if sp[0] == net]
        if spots:
            s.pwr_flag(spots[0][1], spots[0][2])
    return s

def sheet_usb():
    s = Sheet("USB & UART Bridge", 3, "/" + ROOT_UUID)
    s.text("USB-C -> USBLC6 ESD -> CH340C -> AUTO-DOWNLOAD", 25, 25)
    s.place("J3", "Connector", "USB_C_Receptacle_USB2.0_16P", (45, 110, 0), "USB-C",
            "platvorm_custom:USB-C_SMD-TYPE-C-31-M-12_1", "TYPE-C-31-M-12", "C165948",
            {"VBUS": "P:VBUS", "GND": "P:GND", "SHIELD": "P:GND",
             "CC1": "L:CC1", "CC2": "L:CC2", "D+": "L:USB_DP", "D-": "L:USB_DM",
             "SBU1": "X", "SBU2": "X"},
            desc="USB 2.0 receptacle, power + programming",
            ref_off=(-16.5, -26.2), val_off=(0, 28.7))
    s.place("R7", "Device", "R", (70, 85, 0), "5.1k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-075K1L", "C25905", {"1": "L:CC1", "2": "P:GND"}, desc="CC1 pull-down")
    s.place("R8", "Device", "R", (80, 85, 0), "5.1k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-075K1L", "C25905", {"1": "L:CC2", "2": "P:GND"}, desc="CC2 pull-down")
    s.place("U3", "Power_Protection", "USBLC6-2P6", (110, 105, 0), "USBLC6-2SC6",
            "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6", "C2687116",
            {"I/O1": "L:USB_DM", "I/O2": "L:USB_DP", "GND": "P:GND", "VBUS": "P:VBUS"},
            desc="USB ESD protection")
    s.place("U4", "Interface_USB", "CH340C", (160, 105, 0), "CH340C",
            "Package_SO:SOP-16_4.4x10.4mm_P1.27mm", "CH340C", "C84681",
            {"VCC": "P:+3V3", "V3": "P:+3V3", "GND": "P:GND",
             "UD+": "L:USB_DP", "UD-": "L:USB_DM",
             "TXD": "H:U0RXD", "RXD": "H:U0TXD",
             "9": "X", "10": "X", "11": "X", "12": "X", "15": "X",
             "13": "L:DTR", "14": "L:RTS"},
            desc="USB-UART bridge, internal oscillator, 3.3V",
            ref_off=(0, -11.5), val_off=(0, 13.5))
    s.place("C5", "Device", "C", (140, 145, 0), "100n", "Capacitor_SMD:C_0402_1005Metric",
            "CL05B104KO5NNNC", "C1525", {"1": "P:+3V3", "2": "P:GND"}, desc="U4 VCC decoupling")
    s.place("C8", "Device", "C", (155, 145, 0), "100n", "Capacitor_SMD:C_0402_1005Metric",
            "CL05B104KO5NNNC", "C1525", {"1": "P:+3V3", "2": "P:GND"}, desc="U4 V3 decoupling")
    s.place("R5", "Device", "R", (215, 65, 0), "10k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0710KL", "C25744", {"1": "L:DTR", "2": "L:Q1B"}, desc="Q1 base")
    s.place("R6", "Device", "R", (215, 100, 0), "10k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0710KL", "C25744", {"1": "L:RTS", "2": "L:Q2B"}, desc="Q2 base")
    s.place("Q1", "Transistor_BJT", "Q_NPN_BEC", (245, 60, 0), "S8050",
            "Package_TO_SOT_SMD:SOT-23", "S8050", "C2146",
            {"1": "L:Q1B", "2": "L:RTS", "3": "H:EN"}, desc="DTR/RTS -> EN")
    s.place("Q2", "Transistor_BJT", "Q_NPN_BEC", (245, 100, 0), "S8050",
            "Package_TO_SOT_SMD:SOT-23", "S8050", "C2146",
            {"1": "L:Q2B", "2": "L:DTR", "3": "H:IO9"}, desc="DTR/RTS -> IO9 (BOOT)")
    return s


def sheet_esp32():
    s = Sheet("ESP32-C6 Module", 4, "/" + ROOT_UUID)
    s.text("ESP32-C6-WROOM-1-N8", 25, 25)
    s.place("U1", "PCM_Espressif", "ESP32-C6-WROOM-1", (150, 105, 0), "ESP32-C6-WROOM-1-N8",
            "platvorm_custom:ESP32-C6-WROOM-1", "ESP32-C6-WROOM-1-N8", "C5366877",
            {"3": "H:EN", "10": "L:IO8", "15": "H:IO9", "13": "X", "14": "X",
             "24": "H:U0RXD", "25": "H:U0TXD",
             "2": "P:+3V3", "1": "P:GND", "28": "P:GND", "29": "P:GND",
             **{n: f"H:{nm}" for nm, n in
                [("IO0", "8"), ("IO1", "9"), ("IO2", "27"), ("IO3", "26"),
                 ("IO4", "4"), ("IO5", "5"), ("IO6", "6"), ("IO7", "7"),
                 ("IO10", "11"), ("IO11", "12"), ("IO15", "23"), ("IO18", "16"),
                 ("IO19", "17"), ("IO20", "18"), ("IO21", "19"), ("IO22", "20"),
                 ("IO23", "21")]}},
            desc="WiFi6/BLE5/802.15.4 module, 8MB flash; IO12/13 reserved (native USB)",
            ref_off=(0, -27.4), val_off=(0, 31.8))
    s.place("C2", "Device", "C", (115, 140, 0), "100n", "Capacitor_SMD:C_0402_1005Metric",
            "CL05B104KO5NNNC", "C1525", {"1": "P:+3V3", "2": "P:GND"}, desc="U1 decoupling")
    s.place("R9", "Device", "R", (100, 50, 180), "10k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0710KL", "C25744", {"1": "H:EN", "2": "P:+3V3"}, desc="EN pull-up")
    s.place("C6", "Device", "C", (115, 50, 0), "1u", "Capacitor_SMD:C_0402_1005Metric",
            "CL05A105KA5NNNC", "C52923", {"1": "H:EN", "2": "P:GND"}, desc="EN reset delay")
    s.place("SW2", "Switch", "SW_Push", (130, 50, 0), "RESET", "platvorm_custom:SW_TS-1187A",
            "TS-1187A-B-A-B", "C318884", {"1": "H:EN", "2": "P:GND"}, desc="Reset button")
    s.place("R3", "Device", "R", (100, 165, 180), "10k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0710KL", "C25744", {"1": "L:IO8", "2": "P:+3V3"}, desc="IO8 strap pull-up")
    s.place("R4", "Device", "R", (115, 165, 180), "10k", "Resistor_SMD:R_0402_1005Metric",
            "RC0402FR-0710KL", "C25744", {"1": "H:IO9", "2": "P:+3V3"}, desc="IO9 strap pull-up")
    s.place("SW1", "Switch", "SW_Push", (130, 165, 0), "BOOT", "platvorm_custom:SW_TS-1187A",
            "TS-1187A-B-A-B", "C318884", {"1": "H:IO9", "2": "P:GND"}, desc="Boot button")
    gnd = [sp for sp in s.psym_spots if sp[0] == "GND"]
    if gnd:
        s.pwr_flag(gnd[0][1], gnd[0][2])
    return s


def sheet_gpio():
    s = Sheet("GPIO Header", 5, "/" + ROOT_UUID)
    s.text("2x14 DAUGHTER-BOARD STACKING HEADER", 25, 25)
    net_rows = [
        ("+12V", "P"), ("GND", "P"), ("IO0", "H"), ("IO1", "H"), ("IO2", "H"),
        ("IO3", "H"), ("IO4", "H"), ("IO5", "H"), ("IO6", "H"), ("IO7", "H"),
        ("IO10", "H"), ("IO11", "H"), ("IO15", "H"), ("GND", "P"),
        ("-12V", "P"), ("GND", "P"), ("IO18", "H"), ("IO19", "H"), ("IO20", "H"),
        ("IO21", "H"), ("IO22", "H"), ("IO23", "H"), ("IO9", "H"), ("+5V", "P"),
        ("+3V3", "P"), ("GND", "P"), ("+3V3", "P"), ("GND", "P"),
    ]
    j2_map = {}
    for i, (net, kind) in enumerate(net_rows, start=1):
        if kind == "P" and i > 1:          # extended rails/GND (pin1 +12V top is clear)
            j2_map[str(i)] = f"E:{net}"
        else:
            j2_map[str(i)] = f"P:{net}" if kind == "P" else f"H:{net}"
    s.place("J2", "Connector_Generic", "Conn_02x14_Odd_Even", (148.59, 105, 0),
            "GPIO 2x14", "Connector_PinHeader_2.54mm:PinHeader_2x14_P2.54mm_Vertical",
            "PZ254V-12-28P", "C22465888", j2_map,
            desc="Daughter board header: rails + GPIO (see design doc)",
            ref_off=(0, -23.5), val_off=(0, 25.4))
    return s


if "--inspect" in sys.argv:
    for lib, name in [("Device","R"),("Device","C"),("Device","L"),("Device","D_Schottky"),
                      ("Device","FerriteBead"),("Regulator_Switching","TPS54202DDC"),
                      ("Interface_USB","CH340C"),("Connector","USB_C_Receptacle_USB2.0_16P"),
                      ("Power_Protection","USBLC6-2SC6"),("Transistor_BJT","Q_NPN_BEC"),
                      ("Switch","SW_Push"),("Connector_Generic","Conn_01x03"),
                      ("Connector_Generic","Conn_02x08_Odd_Even"),
                      ("Connector_Generic","Conn_02x14_Odd_Even"),
                      ("power","GND"),("power","+3V3"),("power","PWR_FLAG")]:
        ps = parse_pins(extract_symbol(lib, name))
        print(f"{lib}:{name}: " + " ".join(
            f'{p["number"]}/{p["name"] or "~"}/({p["x"]},{p["y"]},{p["a"]})/{p["etype"]}' for p in ps))
    sys.exit(0)

def main():
    emit = "--emit" in sys.argv
    sheets = [sheet_power(), sheet_usb(), sheet_esp32(), sheet_gpio()]
    # sanity: report hlabels per sheet
    for s in sheets:
        print(f"[{s.name}] symbols={sum(1 for i in s.items if i.startswith(chr(9)+'(symbol (lib_id'))} "
              f"hlabels={sorted(s.hlabels)}")
    if emit:
        out = os.path.join(PROJ)
        for s in sheets:
            p = os.path.join(out, SLUG[s.name] + ".kicad_sch")
            with open(p, "w") as f:
                f.write(s.render())
            print("wrote", p)
        with open(os.path.join(out, "Platvorm.kicad_sch"), "w") as f:
            f.write(build_root(sheets))
        print("wrote root")
        # project symbol library (custom parts) + lib tables
        vbus = vbus_symbol_def().replace("power:VBUS", "VBUS")
        # VBUS def was renamed from +5V; its internal sub-symbols already carry VBUS names
        with open(os.path.join(out, "platvorm.kicad_sym"), "w") as f:
            f.write(f'(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicad_symbol_editor")\n'
                    f'\t(generator_version "{GENVER}")\n\n{vbus}\n)\n')
        print("wrote platvorm.kicad_sym")
        with open(os.path.join(out, "sym-lib-table"), "w") as f:
            f.write('(sym_lib_table\n  (version 7)\n  (lib (name "platvorm")(type "KiCad")'
                    '(uri "${KIPRJMOD}/platvorm.kicad_sym")(options "")(descr "Platvorm custom symbols"))\n)\n')
        with open(os.path.join(out, "fp-lib-table"), "w") as f:
            f.write('(fp_lib_table\n  (version 7)\n  (lib (name "platvorm_custom")(type "KiCad")'
                    '(uri "${KIPRJMOD}/footprints/platvorm_custom.pretty")(options "")(descr "Platvorm custom footprints"))\n)\n')
        print("wrote lib tables")

SLUG = {"Power Supply": "power", "USB & UART Bridge": "usb_uart",
        "ESP32-C6 Module": "esp32", "GPIO Header": "gpio"}

if __name__ == "__main__":
    main()
