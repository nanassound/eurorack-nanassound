#!/usr/bin/env python3
# NOTE: schematic-layout DEPRECATED here. Re-running this file overwrites
# Maxxi.kicad_sch with the original ungrouped auto-layout. Use
# tools/layout_schematic.py for schematic layout work; this file remains
# the bootstrapper for Maxxi.kicad_sym.
"""Generate Maxxi.kicad_sch + Maxxi.kicad_sym (Nanas Sound Maxxi USB-C PD Eurorack PSU).

Connectivity is label-based: every symbol pin gets a short stub wire ending in a
global label (or a power:GND symbol / no_connect marker). This keeps generation
deterministic and ERC-checkable without geometric wire routing.

Pin-out ground truth:
- CH224K ESSOP-10: WCH datasheet fig (pin diagram, p1) + JLC/EasyEDA symbol
  1 VDD, 2 CFG2, 3 CFG3, 4 DP, 5 DM, 6 CC2, 7 CC1, 8 VBUS, 9 CFG1, 10 PG, 11 GND(EP)
- TPS54360B (TPS54360DDA symbol): 1 BOOT, 2 VIN, 3 EN, 4 RT/CLK, 5 FB, 6 COMP, 7 GND, 8 SW, 9 PAD
- LT1963A (DDPAK-5, KiCad Regulator_Linear LT1963AEQ extends LT1963EQ)
- LT3015EDD (DFN-8-EP): 1 IN, 2 IN, 3 /SHDN, 4 GND, 5 GND, 6 ADJ, 7 OUT, 8 OUT, 9 IN(EP)
"""
import pathlib
import re
import uuid
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TMP = pathlib.Path('/tmp/maxxi')
SLIB = pathlib.Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols')
ROOT_UUID = '88b3c921-84f7-4c3a-9d38-5128446295d1'  # keep scaffold root uuid

def U():
    return str(uuid.uuid4())

def balanced_block(src, anchor_idx):
    depth = 0
    for i in range(anchor_idx, len(src)):
        if src[i] == '(':
            depth += 1
        elif src[i] == ')':
            depth -= 1
            if depth == 0:
                return src[anchor_idx:i + 1]
    raise ValueError('unbalanced at %d' % anchor_idx)

def sym_def(src, name):
    i = src.find('(symbol "%s"' % name)
    assert i >= 0, name
    return balanced_block(src, i)

PIN_RE = re.compile(
    r'\(pin (\w+ \w+)\s*\(at ([-\d.]+) ([-\d.]+) ([\d.]+)\)\s*\(length ([\d.]+)\)\s*'
    r'\(name "([^"]*)"(?:\s*\(hide yes\))?[\s\S]{0,260}?\(number "([^"]*)"')

def pins_of(block):
    out = {}
    for m in PIN_RE.finditer(block):
        ptype, at_x, at_y, ang, length, name, num = m.groups()
        out[num] = dict(type=ptype, x=float(at_x), y=float(at_y), ang=int(float(ang)),
                        length=float(length), name=name)
    return out

# ---------------------------------------------------------------- lib symbols
mini = (ROOT.parent / 'Mini/V3.0/V3.0.kicad_sch').read_text()
plat = (ROOT.parent / 'EuroPlatvorm/platvorm.kicad_sym').read_text()

eurorack_def = sym_def(mini, '4ms_Connector:Eurorack_Power_16pin_Shrouded')
eurorack_def = eurorack_def.replace('4ms_Connector:Eurorack_Power_16pin_Shrouded',
                                    'Maxxi:Eurorack_Power_16pin_Shrouded')
eurorack_def = eurorack_def.replace('4ms_Connector:', 'maxxi_custom:')

vn02a_def = sym_def(mini, 'Amphenol_VN02A1500000G:VN02A1500000G')
vn02a_def = vn02a_def.replace('Amphenol_VN02A1500000G:VN02A1500000G', 'Maxxi:VN02A1500000G')
vn02a_def = vn02a_def.replace('(property "Footprint" "VN02A1500000G"',
                              '(property "Footprint" "maxxi_custom:VN02A1500000G"')

usbc_def = sym_def(plat, 'USB_C_Receptacle_USB2.0_16P')
usbc_def = usbc_def.replace('(symbol "USB_C_Receptacle_USB2.0_16P"',
                            '(symbol "Maxxi:USB_C_Receptacle_USB2.0_16P"')
usbc_def = usbc_def.replace('platvorm_custom:', 'maxxi_custom:')

sw_lib = (SLIB / 'Regulator_Switching.kicad_sym').read_text()
tps_def = sym_def(sw_lib, 'TPS54360DDA')
ln_lib = (SLIB / 'Regulator_Linear.kicad_sym').read_text()
lt_parent_def = sym_def(ln_lib, 'LT1963EQ')
lt_def = sym_def(ln_lib, 'LT1963AEQ')

dev = (SLIB / 'Device.kicad_sym').read_text()
pwr = (SLIB / 'power.kicad_sym').read_text()

std_defs = {}
for nm, src in [('C', dev), ('C_Polarized', dev), ('R', dev), ('LED', dev),
                ('Polyfuse', dev), ('D_TVS', dev), ('D_Schottky', dev), ('L', dev),
                ('GND', pwr), ('PWR_FLAG', pwr)]:
    d = sym_def(src, nm)
    # embedded defs must be named with the full lib_id
    d = d.replace('(symbol "%s"' % nm, '(symbol "Device:%s"' % nm, 1)
    std_defs[nm] = d
std_defs['GND'] = std_defs['GND'].replace('(symbol "Device:GND"', '(symbol "power:GND"', 1)
std_defs['PWR_FLAG'] = std_defs['PWR_FLAG'].replace('(symbol "Device:PWR_FLAG"', '(symbol "power:PWR_FLAG"', 1)
tps_def = tps_def.replace('(symbol "TPS54360DDA"', '(symbol "Regulator_Switching:TPS54360DDA"', 1)
lt_parent_def = lt_parent_def.replace('(symbol "LT1963EQ"', '(symbol "Regulator_Linear:LT1963EQ"', 1)
lt_def = lt_def.replace('(symbol "LT1963AEQ"', '(symbol "Regulator_Linear:LT1963AEQ"', 1)
lt_def = lt_def.replace('(extends "LT1963EQ")', '(extends "Regulator_Linear:LT1963EQ")', 1)

# ------------------------------------------------------------- custom symbols
def simple_ic_symbol(name, ref_prefix, pins, desc, fp):
    """pins: list of (num, name, ptype, side, y) side in 'L','R','B'."""
    body = '\t\t(rectangle\n\t\t\t(start -7.62 7.62)\n\t\t\t(end 7.62 -7.62)\n\t\t\t(stroke\n\t\t\t\t(width 0.254)\n\t\t\t\t(type default)\n\t\t\t)\n\t\t\t(fill\n\t\t\t\t(type background)\n\t\t\t)\n\t\t)'
    parts = []
    for num, pname, ptype, side, y in pins:
        if side == 'L':
            at, ang, ln = (-11.43, y, 0), 0, 3.81
        elif side == 'R':
            at, ang, ln = (11.43, y, 0), 180, 3.81
        else:
            at, ang, ln = (0, -7.62, 0), 90, 0
        parts.append(
            '\t\t(pin %s line\n\t\t\t(at %s %s %d)\n\t\t\t(length %s)\n\t\t\t(name "%s"\n\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n\t\t\t(number "%s"\n\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (ptype, at[0], at[1], ang, ln, pname, num))
    return ('''\t(symbol "Maxxi:%s"
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(in_pos_files yes)
\t\t(duplicate_pin_numbers_are_jumpers no)
\t\t(property "Reference" "%s"
\t\t\t(at 0 9.398 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "%s"
\t\t\t(at 0 -9.398 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Footprint" "%s"
\t\t\t(at 0 -12.7 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(hide yes)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(hide yes)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Description" "%s"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(hide yes)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(symbol "%s_0_1"
%s
\t\t)
\t\t(symbol "%s_1_1"
%s
\t\t)
\t\t(embedded_fonts no)
\t)''' % (name, ref_prefix, name, fp, desc, name, body, name,
          '\n'.join(parts)))

ch224_pins = [
    ('1', 'VDD', 'power_in', 'L', 5.08),
    ('9', 'CFG1', 'input', 'L', 2.54),
    ('2', 'CFG2', 'input', 'L', 0),
    ('3', 'CFG3', 'input', 'L', -2.54),
    ('10', 'PG', 'open_collector', 'L', -5.08),
    ('8', 'VBUS', 'input', 'R', 5.08),
    ('7', 'CC1', 'bidirectional', 'R', 2.54),
    ('6', 'CC2', 'bidirectional', 'R', 0),
    ('4', 'DP', 'bidirectional', 'R', -2.54),
    ('5', 'DM', 'bidirectional', 'R', -5.08),
    ('11', 'GND', 'power_in', 'B', 0),
]
lt3015_pins = [
    ('1', 'IN', 'power_in', 'L', 5.08),
    ('2', 'IN', 'power_in', 'L', 2.54),
    ('3', '/SHDN', 'input', 'L', 0),
    ('4', 'GND', 'power_in', 'L', -2.54),
    ('5', 'GND', 'power_in', 'R', 5.08),
    ('6', 'ADJ', 'input', 'R', 2.54),
    ('7', 'OUT', 'power_out', 'R', 0),
    ('8', 'OUT', 'passive', 'R', -2.54),
    ('9', 'IN', 'power_in', 'B', 0),
]
ch224_def = simple_ic_symbol('CH224K', 'U', ch224_pins,
                             'USB PD 3.0/2.0 sink controller, 4-22V, ESSOP-10 (WCH)',
                             'maxxi_custom:ESSOP-10_L4.9-W3.9-P1.0-LS6.0-TL-EP')
lt3015_def = simple_ic_symbol('LT3015EDD', 'U', lt3015_pins,
                              '1.5A low dropout negative LDO, -30V, DFN-8 (ADI)',
                              'maxxi_custom:DFN-8_L3.0-W3.0-P0.50-TL-EP')

maxxi_lib = ('(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "kicad_symbol_editor")\n'
             '\t(generator_version "9.0")\n'
             + eurorack_def + '\n' + vn02a_def + '\n' + usbc_def + '\n'
             + ch224_def + '\n' + lt3015_def + '\n)\n')
(ROOT / 'Maxxi.kicad_sym').write_text(maxxi_lib)

# ------------------------------------------------------------------ footprint
FP_R = 'Resistor_SMD:R_0603_1608Metric'
FP_R1210 = 'Resistor_SMD:R_1210_3225Metric'
FP_C0603 = 'Capacitor_SMD:C_0603_1608Metric'
FP_C1206 = 'Capacitor_SMD:C_1206_3216Metric'
FP_CP = 'Capacitor_SMD:CP_Elec_6.3x7.7'
FP_LED = 'LED_THT:LED_D2.0mm_W4.8mm_H2.5mm_FlatTop'
FP_FUSE = 'Fuse:Fuse_1812_4532Metric'
FP_SMB = 'Diode_SMD:D_SMB'
FP_SMA = 'Diode_SMD:D_SMA'
FP_SO8 = 'Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.71x3.7mm_ThermalVias'
FP_TO263 = 'Package_TO_SOT_SMD:TO-263-5_TabPin3'
FP_ESSOP = 'maxxi_custom:ESSOP-10_L4.9-W3.9-P1.0-LS6.0-TL-EP'
FP_DFN8 = 'maxxi_custom:DFN-8_L3.0-W3.0-P0.50-TL-EP'
FP_L8080 = 'maxxi_custom:IND-SMD_L8.0-W8.0_SMNR8040'
FP_USBC = 'maxxi_custom:USB-C_SMD_LAIL-TYPE-C-16PIN-05-LT'
FP_EURO = 'maxxi_custom:Pins_2x08_2.54mm_TH_EuroPower_Shrouded_reducedsilk'
FP_VN02A = 'maxxi_custom:VN02A1500000G'

# source data for passives: value -> (lcsc, mpn, mfr)
R_SRC = {
    '680R': ('C22356475', 'RCA03680RFLF', 'Yageo'),
    '1k': ('C2907002', 'FRC0603F1001TS', 'FIRSTART'),
    '1.87k': ('C2930054', 'FRC0603F1871TS', 'FIRSTART'),
    '2.2k': ('C2907005', 'FRC0603F2201TS', 'FIRSTART'),
    '10k': ('C2906982', 'FRC0603F1002TS', 'FIRSTART'),
    '10.2k': ('C2933125', 'FRC0603F1022TS', 'FIRSTART'),
    '13k': ('C2906992', 'FRC0603F1302TS', 'FIRSTART'),
    '22k': ('C2907015', 'FRC0603F2202TS', 'FIRSTART'),
    '24k': ('', 'RC0603FR-0724KL', 'Yageo'),
    '88.7k': ('C2999456', 'FRC0603F8872TS', 'FIRSTART'),
    '90.9k': ('C2930136', 'FRC0603F9092TS', 'FIRSTART'),
    '100k': ('C25803', '0603WAF1003T5E', 'UNI-ROYAL'),
    '200k': ('C2907009', 'FRC0603F2003TS', 'FIRSTART'),
}
C_SRC = {
    '39pF': ('C472792', 'CL10C390JB81PNC', 'Samsung'),
    '6.8nF': ('C107098', 'CC0603KRX7R9BB683', 'Murata'),
    '100nF': ('C14663', 'CC0603KRX7R9BB104', 'Murata'),
    '1uF': ('C29936', 'CL10B105KA8NNNC', 'Samsung'),
    '10uF 35V': ('C49326788', '1206X7S106K350NT', 'FH/Guangdong'),
    '10uF 50V': ('C49326770', '1206X7R106K500NT', 'FH/Guangdong'),
    '47uF 25V': ('C403725', 'GRM31CR61E476ME44L', 'Murata'),
    '100uF 35V': ('C72478', 'RVT1V101M0607', 'Rubycon'),
}

def transform(x, y, rot, mirror_x):
    if mirror_x:
        x = -x
    if rot == 0:
        return x, -y
    if rot == 90:
        return y, -x
    if rot == 180:
        return -x, y
    return -y, x

def outward_dir(ang, rot, mirror_x):
    d = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[ang]
    dx, dy = -d[0], -d[1]
    if mirror_x:
        dx = -dx
    if rot == 0:
        return dx, -dy
    if rot == 90:
        return dy, -dx
    if rot == 180:
        return -dx, dy
    return -dy, dx

LIBDEFS = {}
LIBDEFS['Device:R'] = std_defs['R']
LIBDEFS['Device:C'] = std_defs['C']
LIBDEFS['Device:C_Polarized'] = std_defs['C_Polarized']
LIBDEFS['Device:LED'] = std_defs['LED']
LIBDEFS['Device:Polyfuse'] = std_defs['Polyfuse']
LIBDEFS['Device:D_TVS'] = std_defs['D_TVS']
LIBDEFS['Device:D_Schottky'] = std_defs['D_Schottky']
LIBDEFS['Device:L'] = std_defs['L']
LIBDEFS['power:GND'] = std_defs['GND']
LIBDEFS['power:PWR_FLAG'] = std_defs['PWR_FLAG']
LIBDEFS['Regulator_Switching:TPS54360DDA'] = tps_def
LIBDEFS['Regulator_Linear:LT1963EQ'] = lt_parent_def
for d, nm in [(ch224_def, 'Maxxi:CH224K'), (lt3015_def, 'Maxxi:LT3015EDD'),
              (eurorack_def, 'Maxxi:Eurorack_Power_16pin_Shrouded'),
              (vn02a_def, 'Maxxi:VN02A1500000G'),
              (usbc_def, 'Maxxi:USB_C_Receptacle_USB2.0_16P')]:
    LIBDEFS[nm] = d

PIN_CACHE = {lid: pins_of(d) for lid, d in LIBDEFS.items()}
# LT1963AEQ extends LT1963EQ: it has no pins of its own
PIN_CACHE['Regulator_Linear:LT1963AEQ'] = pins_of(lt_parent_def)

# ---------------------------------------------------------------- components
# pin map: number -> ('net', NAME) | ('gnd',) | ('nc',)
CMP = []
def add(ref, lib, value, fp, x, y, rot=0, mirror=False, pins=None, dnp=False,
        in_bom=True, src=None, mfr='', desc='', extra=None):
    CMP.append(dict(ref=ref, lib=lib, value=value, fp=fp, x=x, y=y, rot=rot,
                    mirror=mirror, pins=pins or {}, dnp=dnp, in_bom=in_bom,
                    src=src or ('', '', ''), mfr=mfr, desc=desc, extra=extra or []))

# --- input stage
add('J1', 'Maxxi:USB_C_Receptacle_USB2.0_16P', 'USB_C_Receptacle_USB2.0_16P', FP_USBC, 40, 50,
    pins={'A1B12': ('gnd',), 'B1A12': ('gnd',), 'A4B9': ('net', 'VBUS_RAW'),
          'B4A9': ('net', 'VBUS_RAW'), 'A5': ('net', 'CC1'), 'B5': ('net', 'CC2'),
          'A6': ('nc',), 'B6': ('nc',), 'A7': ('nc',), 'B7': ('nc',),
          'A8': ('nc',), 'B8': ('nc',), '1': ('gnd',), '2': ('gnd',),
          '3': ('gnd',), '4': ('gnd',)},
    src=('C55591234', 'LAIL-TYPE-C-16PIN-05-LT', 'LAILAN'), mfr='LAILAN',
    desc='USB Type-C 2.0 receptacle, 16P, SMD vertical (A-row assumed on +Y side of footprint)')
add('F1', 'Device:Polyfuse', '4A/24V', FP_FUSE, 40, 100,
    pins={'1': ('net', 'VBUS_RAW'), '2': ('net', '+VBUS')},
    src=('C42435780', '1812L400/24GR', 'Littelfuse'), mfr='Littelfuse',
    desc='PTC resettable fuse 4A hold 24V (3A hold nuisance-trips at rated loads)')
add('D1', 'Device:D_TVS', 'SMBJ20A', FP_SMB, 62, 105,
    pins={'1': ('net', '+VBUS'), '2': ('gnd',)},
    src=('C353377', 'SMBJ20A', 'MDD'), mfr='MDD',
    desc='TVS diode 20V standoff, SMB')
add('C1', 'Device:C_Polarized', '100uF/35V', FP_CP, 78, 100,
    pins={'1': ('net', '+VBUS'), '2': ('gnd',)}, src=C_SRC['100uF 35V'],
    mfr='Rubycon', desc='Input bulk electrolytic')
add('C2', 'Device:C_Polarized', '100uF/35V', FP_CP, 94, 100,
    pins={'1': ('net', '+VBUS'), '2': ('gnd',)}, src=C_SRC['100uF 35V'],
    mfr='Rubycon', desc='Input bulk electrolytic')

# --- PD sink
add('U1', 'Maxxi:CH224K', 'CH224K', FP_ESSOP, 130, 55,
    pins={'1': ('net', 'VDD'), '2': ('nc',), '3': ('nc',), '4': ('net', 'DPIO'),
          '5': ('net', 'DPIO'), '6': ('net', 'CC2'), '7': ('net', 'CC1'),
          '8': ('net', 'VBUS_SNS'), '9': ('net', 'CFG1'), '10': ('net', 'PG'),
          '11': ('gnd',)},
    src=('C970725', 'CH224K', 'WCH'), mfr='WCH',
    desc='USB PD sink, CFG1 NC = request 20V; VBUS pin8 via R63 (abs max 13.5V)')
add('R1', 'Device:R', '24k', FP_R, 100, 84, dnp=True, in_bom=False,
    pins={'1': ('net', 'CFG1'), '2': ('gnd',)}, src=R_SRC['24k'], mfr='Yageo',
    desc='CFG1 strap, DNP + excluded from BOM: fit 24k=12V / 56k=15V, NC=20V')
add('R2', 'Device:R', '1k', FP_R1210, 115, 92,
    pins={'1': ('net', '+VBUS'), '2': ('net', 'VDD')},
    src=('C20164422', 'RC1210FR-071KP', 'YAGEO'), mfr='YAGEO',
    desc='CH224K VDD series R (fig 6.2); 1210/0.5W: 279mW at 20V contract')
add('C3', 'Device:C', '1uF', FP_C0603, 130, 100,
    pins={'1': ('net', 'VDD'), '2': ('gnd',)}, src=C_SRC['1uF'], mfr='Samsung',
    desc='CH224K VDD decoupling')
add('R3', 'Device:R', '1k', FP_R, 172, 84,
    pins={'1': ('net', 'DPIO'), '2': ('gnd',)}, src=R_SRC['1k'], mfr='FIRSTART',
    desc='DP/DM pulldown, PD-only mode (datasheet 5.5/6.3)')
add('R4', 'Device:R', '10k', FP_R, 155, 22,
    pins={'1': ('net', 'VDD'), '2': ('net', 'PG')}, src=R_SRC['10k'], mfr='FIRSTART',
    desc='PG open-drain pull-up to VDD (CH224K PG rating unstated; 3.3V-safe)')
add('R63', 'Device:R', '10k', FP_R, 145, 55,
    pins={'1': ('net', '+VBUS'), '2': ('net', 'VBUS_SNS')}, src=R_SRC['10k'], mfr='FIRSTART',
    desc='CH224K VBUS pin8 sense series R (pin abs max 13.5V; WCH v2.1 tab 4-2, fig 7-1: 10k)')

def buck(ref, lref, dref, rbase, cbase, x, y, sfx, pos_net, gnd_net, fb_top, fb_bot, fb_src, diode_lib, diode_val,
         diode_fp, diode_src, cin_net, desc, fb_top_net=None, cin_key='10uF 35V',
         l_out_net=None):
    """sfx: rail index '1','2','3' used in net names. fb_top_net overrides the FB divider top
    terminal (buck: positive output rail; IBB per TI Fig.50 p34: system GND). cin_key picks the
    converter input cap from C_SRC (IBB input spans +VBUS..-12V6 = 32.57V: use 50V+)."""
    b = sfx
    add(ref, 'Regulator_Switching:TPS54360DDA', 'TPS54360BDDAR', FP_SO8, x, y,
        pins={'1': ('net', 'BOOT' + b), '2': ('net', pos_net), '3': ('net', 'EN' + b),
              '4': ('net', 'RT' + b), '5': ('net', 'FB' + b), '6': ('net', 'COMP' + b),
              '7': ('net', gnd_net), '8': ('net', 'SW' + b), '9': ('net', gnd_net)},
        src=('C524806', 'TPS54360BDDAR', 'TI'), mfr='TI', desc=desc)
    add('R%d' % (rbase + 0), 'Device:R', '100k', FP_R, x - 22, y - 32,
        pins={'1': ('net', '+VBUS'), '2': ('net', 'EN' + b)}, src=R_SRC['100k'],
        mfr='UNI-ROYAL', desc='EN divider top')
    add('R%d' % (rbase + 1), 'Device:R', '22k', FP_R, x - 22, y - 20,
        pins={'1': ('net', 'EN' + b), '2': ('net', gnd_net)}, src=R_SRC['22k'],
        mfr='FIRSTART', desc='EN divider bottom')
    add('R%d' % (rbase + 2), 'Device:R', '200k', FP_R, x + 16, y - 34,
        pins={'1': ('net', 'RT' + b), '2': ('net', gnd_net)}, src=R_SRC['200k'],
        mfr='FIRSTART', desc='RT: 500 kHz (datasheet RT=200k)')
    add('R%d' % (rbase + 3), 'Device:R', '13k', FP_R, x + 30, y - 26,
        pins={'1': ('net', 'COMP' + b), '2': ('net', 'COMP' + b + 'S')},
        src=R_SRC['13k'], mfr='FIRSTART', desc='COMP zero resistor (TI app note)')
    add('C%d' % (cbase + 0), 'Device:C', '6.8nF', FP_C0603, x + 30, y - 14,
        pins={'1': ('net', 'COMP' + b + 'S'), '2': ('net', gnd_net)}, src=C_SRC['6.8nF'],
        mfr='Murata', desc='COMP zero cap')
    add('C%d' % (cbase + 1), 'Device:C', '39pF', FP_C0603, x + 44, y - 26,
        pins={'1': ('net', 'COMP' + b), '2': ('net', gnd_net)}, src=C_SRC['39pF'],
        mfr='Samsung', desc='COMP pole cap')
    add('R%d' % (rbase + 4), 'Device:R', fb_top, FP_R, x - 36, y + 14,
        pins={'1': ('net', fb_top_net or pos_out_net(b)), '2': ('net', 'FB' + b)}, src=fb_src[0],
        mfr=fb_src[2], desc='FB top')
    add('R%d' % (rbase + 5), 'Device:R', fb_bot, FP_R, x - 36, y + 27,
        pins={'1': ('net', 'FB' + b), '2': ('net', gnd_net)}, src=fb_src[1],
        mfr=fb_src[2], desc='FB bottom')
    add('C%d' % (cbase + 2), 'Device:C', '100nF', FP_C0603, x + 17, y + 13,
        pins={'1': ('net', 'BOOT' + b), '2': ('net', 'SW' + b)}, src=C_SRC['100nF'],
        mfr='Murata', desc='BOOT cap 0.1uF X7R (datasheet)')
    add(lref, 'Device:L', '10uH/4A', FP_L8080, x + 46, y + 13,
        pins={'1': ('net', 'SW' + b), '2': ('net', l_out_net or pos_out_net(b))},
        src=('C37429', 'SWPA8040S100MT', 'Sunlord'), mfr='Sunlord',
        desc='10uH 8x8 power inductor')
    add(dref, diode_lib, diode_val, diode_fp, x + 17, y + 29,
        pins={'1': ('net', 'SW' + b), '2': ('net', gnd_net)},
        src=diode_src, mfr='MDD', desc='Catch diode (K to SW)')
    add('C%d' % (cbase + 3), 'Device:C', cin_key, FP_C1206, x - 22, y + 13,
        pins={'1': ('net', '+VBUS'), '2': ('net', cin_net)}, src=C_SRC[cin_key],
        mfr=C_SRC[cin_key][2], desc='Converter input cap')

def pos_out_net(b):
    return {'1': '+12V6', '2': '-12V6', '3': '+5V'}[b]

buck('U2', 'L1', 'D2', 30, 30, 195, 45, '1', '+VBUS', 'GND', '10k', '680R',
     (R_SRC['10k'], R_SRC['680R'], 'FIRSTART'), 'Device:D_Schottky', 'SS36', FP_SMA,
     ('C16015', 'SS36', 'MDD'), 'GND', '+12.6V buck prereg for LT1963A')
buck('U3', 'L2', 'D3', 36, 34, 195, 130, '2', '+VBUS', '-12V6', '10k', '680R',
     (R_SRC['10k'], R_SRC['680R'], 'FIRSTART'), 'Device:D_Schottky', 'SS56', FP_SMA,
     ('C65009', 'SS56', 'MDD'), '-12V6',
     '-12.565V inverting buck-boost (IC GND on -12V6; FB top to GND per TI Fig.50 p34)',
     fb_top_net='GND', cin_key='10uF 50V', l_out_net='GND')
buck('U4', 'L3', 'D4', 42, 38, 195, 215, '3', '+VBUS', 'GND', '10k', '1.87k',
     (R_SRC['10k'], R_SRC['1.87k'], 'FIRSTART'), 'Device:D_Schottky', 'SS36', FP_SMA,
     ('C16015', 'SS36', 'MDD'), 'GND', '5.07V buck for Eurorack +5 rail')

# FB divider for U3 senses GND->-12V6: fix R net for that topology
for c in CMP:
    if c['ref'] == 'R25':  # U3 FB top (n=3 -> R? handled below)
        pass
# U2 FB top: R24 (n=2 -> R(2+14)=R16? no: n=2 -> R16/R17 names collide; fix by scan instead)

# --- LDOs
add('U5', 'Regulator_Linear:LT1963EQ', 'LT1963AEQ', FP_TO263, 270, 45,
    pins={'1': ('net', '+12V6'), '2': ('net', '+12V6'), '3': ('gnd',),
          '4': ('net', '+12V'), '5': ('net', 'ADJ1')},
    src=('C459702', 'LT1963AEQ', 'ADI'), mfr='ADI',
    desc='1.5A low-noise LDO, Vout=1.21*(1+90.9/10.2)+3uA*10.2k=12.02V; KiCad symbol: 1=SHDN 2=IN 3=GND 4=OUT 5=ADJ')
add('R50', 'Device:R', '90.9k', FP_R, 252, 62,
    pins={'1': ('net', '+12V'), '2': ('net', 'ADJ1')}, src=R_SRC['90.9k'], mfr='FIRSTART',
    desc='LT1963A ADJ divider top')
add('R51', 'Device:R', '10.2k', FP_R, 266, 62,
    pins={'1': ('net', 'ADJ1'), '2': ('gnd',)}, src=R_SRC['10.2k'], mfr='FIRSTART',
    desc='LT1963A ADJ divider bottom')
add('C50', 'Device:C', '47uF 25V', FP_C1206, 254, 20,
    pins={'1': ('net', '+12V6'), '2': ('gnd',)}, src=C_SRC['47uF 25V'], mfr='Murata',
    desc='LDO input cap')
add('C51', 'Device:C', '47uF 25V', FP_C1206, 288, 58,
    pins={'1': ('net', '+12V'), '2': ('gnd',)}, src=C_SRC['47uF 25V'], mfr='Murata',
    desc='+12V output cap')
add('C52', 'Device:C', '100nF', FP_C0603, 299, 58,
    pins={'1': ('net', '+12V'), '2': ('gnd',)}, src=C_SRC['100nF'], mfr='Murata',
    desc='+12V HF bypass')

add('U6', 'Maxxi:LT3015EDD', 'LT3015EDD', FP_DFN8, 270, 130,
    pins={'1': ('net', '-12V6'), '2': ('net', '-12V6'), '3': ('net', '-12V6'),
          '4': ('gnd',), '5': ('gnd',), '6': ('net', 'ADJ2'), '7': ('net', '-12V'),
          '8': ('net', '-12V'), '9': ('net', '-12V6')},
    src=('C117305', 'LT3015EDD', 'ADI'), mfr='ADI',
    desc='1.5A negative LDO, Vout=-1.22*(1+R2/R1)=-12.02V (R2=88.7k OUT->ADJ, R1=10k ADJ->GND, LT3015 p15 Fig2/Table1)')
add('R52', 'Device:R', '88.7k', FP_R, 252, 142,
    pins={'1': ('net', '-12V'), '2': ('net', 'ADJ2')}, src=R_SRC['88.7k'], mfr='FIRSTART',
    desc='LT3015 ADJ divider top (OUT->ADJ; p15 Table1: R2 large)')
add('R53', 'Device:R', '10k', FP_R, 266, 142,
    pins={'1': ('net', 'ADJ2'), '2': ('gnd',)}, src=R_SRC['10k'], mfr='FIRSTART',
    desc='LT3015 ADJ divider bottom (ADJ->GND; p15 Table1: R1 small)')
add('C53', 'Device:C', '47uF 25V', FP_C1206, 254, 108,
    pins={'1': ('net', '-12V6'), '2': ('gnd',)}, src=C_SRC['47uF 25V'], mfr='Murata',
    desc='LDO input cap')
add('C54', 'Device:C', '47uF 25V', FP_C1206, 288, 138,
    pins={'1': ('net', '-12V'), '2': ('gnd',)}, src=C_SRC['47uF 25V'], mfr='Murata',
    desc='-12V output cap')
add('C55', 'Device:C', '100nF', FP_C0603, 299, 138,
    pins={'1': ('net', '-12V'), '2': ('gnd',)}, src=C_SRC['100nF'], mfr='Murata',
    desc='-12V HF bypass')

# --- indicators
add('D5', 'Device:LED', 'L +12V', FP_LED, 252, 195,
    pins={'1': ('gnd',), '2': ('net', 'LD12')}, src=('C6717903', 'C6717903 LED', 'XL'))
add('R60', 'Device:R', '2.2k', FP_R, 270, 195,
    pins={'1': ('net', 'LD12'), '2': ('net', '+12V')}, src=R_SRC['2.2k'], mfr='FIRSTART')
add('D6', 'Device:LED', 'L -12V', FP_LED, 252, 208, rot=180,
    pins={'1': ('net', 'LN12'), '2': ('gnd',)}, src=('C6717903', 'C6717903 LED', 'XL'))
add('R61', 'Device:R', '2.2k', FP_R, 270, 208,
    pins={'1': ('net', 'LN12'), '2': ('net', '-12V')}, src=R_SRC['2.2k'], mfr='FIRSTART')
add('D7', 'Device:LED', 'L +5V', FP_LED, 252, 221,
    pins={'1': ('gnd',), '2': ('net', 'L5')}, src=('C6717903', 'C6717903 LED', 'XL'))
add('R62', 'Device:R', '680R', FP_R, 270, 221,
    pins={'1': ('net', 'L5'), '2': ('net', '+5V')}, src=R_SRC['680R'], mfr='Yageo')

# --- Eurorack outputs (Mini-proven convention: 13,14 = GND, 15,16 = -12V)
EURO_PINS = {'1': ('nc',), '2': ('nc',), '3': ('nc',), '4': ('nc',),
             '5': ('net', '+5V'), '6': ('net', '+5V'), '7': ('net', '+12V'),
             '8': ('net', '+12V'), '9': ('gnd',), '10': ('gnd',), '11': ('gnd',),
             '12': ('gnd',), '13': ('gnd',), '14': ('gnd',),
             '15': ('net', '-12V'), '16': ('net', '-12V')}
add('J2', 'Maxxi:Eurorack_Power_16pin_Shrouded', 'Eurorack_Power_16pin_Shrouded', FP_EURO,
    346, 45, pins=dict(EURO_PINS), in_bom=False,
    mfr='Cixi LanLing', desc='Eurorack power header',
    extra=[('Part Number', 'LL1007-1 (2*8 HITEMP)'), ('Specifications', 'Header, Male Pins, 2*8, 2.54mm, shrouded')])
add('J3', 'Maxxi:Eurorack_Power_16pin_Shrouded', 'Eurorack_Power_16pin_Shrouded', FP_EURO,
    346, 110, pins=dict(EURO_PINS), in_bom=False,
    mfr='Cixi LanLing', desc='Eurorack power header',
    extra=[('Part Number', 'LL1007-1 (2*8 HITEMP)'), ('Specifications', 'Header, Male Pins, 2*8, 2.54mm, shrouded')])
add('J4', 'Maxxi:VN02A1500000G', 'VN02A1500000G', FP_VN02A, 346, 200,
    pins={'1': ('net', '+5V'), '2': ('gnd',)},
    src=('C5188442', 'VN02A1500000G', 'Amphenol'), mfr='Amphenol',
    desc='2-pos terminal block, +5V output')

# --- 5V output caps
add('C56', 'Device:C', '47uF 25V', FP_C1206, 322, 214,
    pins={'1': ('net', '+5V'), '2': ('gnd',)}, src=C_SRC['47uF 25V'], mfr='Murata',
    desc='+5V output cap')
add('C57', 'Device:C', '100nF', FP_C0603, 333, 214,
    pins={'1': ('net', '+5V'), '2': ('gnd',)}, src=C_SRC['100nF'], mfr='Murata',
    desc='+5V HF bypass')

# --- PWR_FLAGs
FLAGS = [('GND', 20, 62), ('+VBUS', 20, 74), ('+12V6', 20, 150), ('-12V6', 20, 162),
         ('VDD', 20, 174), ('+5V', 20, 186)]

# ------------------------------------------------------------------ emit sch
def fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)

out = []
out.append('(kicad_sch')
out.append('\t(version 20260306)')
out.append('\t(generator "eeschema")')
out.append('\t(generator_version "10.0")')
out.append('\t(uuid "%s")' % ROOT_UUID)
out.append('\t(paper "A3")')
out.append('\t(title_block')
out.append('\t\t(title "Maxxi - USB-C PD Eurorack power supply")')
out.append('\t\t(date "2026-09-22")')
out.append('\t\t(rev "1")')
out.append('\t\t(company "Nanas Sound OÜ")')
out.append('\t)')
out.append('\t(lib_symbols')
for lid in LIBDEFS:  # insertion order: LT1963EQ parent precedes LT1963AEQ
    out.append(LIBDEFS[lid])
out.append('\t)')

gnd_spots = []
gnd_bus = {}  # (ref, side) -> list of (x, y) bus points

def emit_net_pin(px, py, comp, num, pin):
    """stub + label / gnd symbol / nc. Returns list of s-expr chunks."""
    chunks = []
    kind = pin[0]
    odx, ody = outward_dir(comp['pininfo'][num]['ang'], comp['rot'], comp['mirror'])
    is_header = comp['lib'].startswith('Maxxi:Eurorack')
    if is_header and kind == 'gnd':
        # long tail to a shared per-side vertical GND bus
        tail = 12.7
        sx, sy = px + odx * tail, py + ody * tail
        chunks.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (fmt(px), fmt(py), fmt(sx), fmt(sy), U()))
        side = 'L' if odx < 0 else 'R'
        gnd_bus.setdefault((comp['ref'], side), []).append((sx, sy))
        return chunks
    if is_header and kind == 'net' and pin[1] == '-12V':
        # long tail so the label clears the GND bus
        tail = 17.78
        sx, sy = px + odx * tail, py + ody * tail
        chunks.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (fmt(px), fmt(py), fmt(sx), fmt(sy), U()))
        ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(odx, ody)]
        chunks.append('\t(global_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (pin[1], fmt(sx), fmt(sy), ang, U()))
        return chunks
    tail = 2.54
    sx, sy = px + odx * tail, py + ody * tail
    chunks.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (fmt(px), fmt(py), fmt(sx), fmt(sy), U()))
    if kind == 'gnd':
        gnd_spots.append((sx, sy))
    elif kind == 'nc':
        chunks.append('\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)' % (fmt(sx), fmt(sy), U()))
    else:
        ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(odx, ody)]
        chunks.append('\t(global_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (pin[1], fmt(sx), fmt(sy), ang, U()))
    return chunks

for c in CMP:
    c['pininfo'] = PIN_CACHE[c['lib']]

for c in CMP:
    for num, pin in sorted(c['pins'].items(), key=lambda kv: (len(kv[0]), kv[0])):
        p = c['pininfo'].get(num)
        assert p, (c['ref'], num, sorted(c['pininfo']))
        dx, dy = transform(p['x'], p['y'], c['rot'], c['mirror'])
        px, py = c['x'] + dx, c['y'] + dy
        out.extend(emit_net_pin(px, py, c, num, pin))

# Eurorack header GND buses: vertical wire per side, single GND symbol at bottom
for (ref, side), pts in gnd_bus.items():
    xs = {pt[0] for pt in pts}
    assert len(xs) == 1, (ref, side, xs)
    bx = xs.pop()
    ys = sorted(pt[1] for pt in pts)
    top, bot = ys[0], ys[-1] + 2.54
    out.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (fmt(bx), fmt(top), fmt(bx), fmt(bot), U()))
    # T-points where tail wire endpoints land on the bus interior
    for iy in ys[1:]:
        out.append('\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "%s")\n\t)' % (fmt(bx), fmt(iy), U()))
    gnd_spots.append((bx, bot))

# junctions: none needed (no T-topologies)

# power flags: stub down + label
for j, (net, fx, fy) in enumerate(FLAGS, 1):
    out.append('\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (fx, fy, fx, fy + 2.54, U()))
    out.append('\t(global_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s 270)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "%s")\n\t)' % (net, fx, fy + 2.54, U()))
    out.append('\t(symbol\n\t\t(lib_id "power:PWR_FLAG")\n\t\t(at %s %s 0)\n\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)\n\t\t(uuid "%s")\n\t\t(property "Reference" "#FLG%02d"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Value" "PWR_FLAG"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Footprint" ""\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Datasheet" ""\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Description" "Special symbol for telling ERC where power comes from"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(pin "1"\n\t\t\t(uuid "%s")\n\t\t)\n\t\t(instances\n\t\t\t(project "Maxxi"\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference "#FLG%02d")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)' % (fx, fy, U(), j, fx, fy - 3.81, fx, fy - 1.27, fx, fy + 1.27, fx, fy + 1.27, fx, fy + 1.27, U(), ROOT_UUID, j))

# GND power symbols at all gnd stub spots
for i, (gx, gy) in enumerate(gnd_spots, 1):
    out.append('\t(symbol\n\t\t(lib_id "power:GND")\n\t\t(at %s %s 0)\n\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n\t\t(dnp no)\n\t\t(uuid "%s")\n\t\t(property "Reference" "#PWR%03d"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Value" "GND"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Footprint" ""\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Datasheet" ""\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(property "Description" "Power symbol creates a global label with name \\"GND\\" , ground"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t\t(pin "1"\n\t\t\t(uuid "%s")\n\t\t)\n\t\t(instances\n\t\t\t(project "Maxxi"\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference "#PWR%03d")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)' % (gx, gy, U(), i, gx, gy + 3.81, gx, gy + 1.27, gx, gy - 1.27, gx, gy - 1.27, gx, gy - 1.27, U(), ROOT_UUID, i))

# component instances
for c in CMP:
    lcsc, mpn, mfr2 = c['src']
    out.append('\t(symbol')
    out.append('\t\t(lib_id "%s")' % c['lib'])
    mir = '\n\t\t(mirror x)' if c['mirror'] else ''
    out.append('\t\t(at %s %s %d)%s' % (fmt(c['x']), fmt(c['y']), c['rot'], mir))
    out.append('\t\t(unit 1)')
    out.append('\t\t(body_style 1)')
    out.append('\t\t(exclude_from_sim no)')
    out.append('\t\t(in_bom %s)' % ('yes' if c['in_bom'] else 'no'))
    out.append('\t\t(on_board yes)')
    out.append('\t\t(in_pos_files yes)')
    out.append('\t\t(dnp %s)' % ('yes' if c['dnp'] else 'no'))
    out.append('\t\t(uuid "%s")' % U())
    out.append('\t\t(property "Reference" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (c['ref'], fmt(c['x'] - 2), fmt(c['y'] - 11)))
    out.append('\t\t(property "Value" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (c['value'], fmt(c['x'] - 2), fmt(c['y'] + 11)))
    out.append('\t\t(property "Footprint" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (c['fp'], fmt(c['x']), fmt(c['y'])))
    out.append('\t\t(property "Datasheet" ""\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (fmt(c['x']), fmt(c['y'])))
    out.append('\t\t(property "Description" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (c['desc'], fmt(c['x']), fmt(c['y'])))
    if mpn:
        out.append('\t\t(property "Manufacturer_Part_Number" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (mpn, fmt(c['x']), fmt(c['y'])))
    if mfr2 or c['mfr']:
        out.append('\t\t(property "Manufacturer" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (mfr2 or c['mfr'], fmt(c['x']), fmt(c['y'])))
    if lcsc:
        out.append('\t\t(property "LCSC Part Number" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (lcsc, fmt(c['x']), fmt(c['y'])))
    for k, v in c['extra']:
        out.append('\t\t(property "%s" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (k, v, fmt(c['x']), fmt(c['y'])))
    for num in sorted(c['pins'], key=lambda s: (len(s), s)):
        out.append('\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)' % (num, U()))
    out.append('\t\t(instances\n\t\t\t(project "Maxxi"\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)' % (ROOT_UUID, c['ref']))
    out.append('\t)')

out.append('\t(sheet_instances')
out.append('\t\t(path "/"')
out.append('\t\t\t(page "1")')
out.append('\t\t)')
out.append('\t)')
out.append('\t(embedded_fonts no)')
out.append(')')

(ROOT / 'Maxxi.kicad_sch').write_text('\n'.join(out) + '\n')
print('wrote Maxxi.kicad_sch with %d components, %d gnd symbols, %d flags'
      % (len(CMP), len(gnd_spots), len(FLAGS)))
print('wrote Maxxi.kicad_sym')
