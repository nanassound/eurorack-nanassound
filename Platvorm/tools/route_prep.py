#!/usr/bin/env python3
"""Prepare Platvorm.dsn for freerouting: 0.7 mm vias everywhere and a Power
class (0.5 mm tracks) for the 11 power nets. Run with any python3 AFTER
ExportSpecctraDSN."""
import re

POWER = ["+12V", "+3V3", "+5V", "-12V", "VBUS",
         '"/Power Supply/+12V_RAW"', '"/Power Supply/+5V_EURO"',
         '"/Power Supply/-12V_RAW"', '"/Power Supply/SW"',
         '"/Power Supply/VIN_BUCK"', '"/Power Supply/VOUT_PRE"']

VIA600 = "Via[0-1]_600:300_um"
VIA700 = "Via[0-1]_700:300_um"

dsn = open("Platvorm.dsn").read()

# every route/via reference moves to the 0.7 mm padstack
dsn = dsn.replace(VIA600, VIA700)

# --- split power nets out of the kicad_default class ---
start = dsn.index("(class kicad_default")
depth = 0
end = None
for i in range(start, len(dsn)):
    if dsn[i] == "(":
        depth += 1
    elif dsn[i] == ")":
        depth -= 1
        if depth == 0:
            end = i + 1
            break
assert end, "class block not terminated"

block = dsn[start:end]
hdr_end = block.index("(circuit")
tokens = re.findall(r'"[^"]*"|\S+', block[len("(class kicad_default"):hdr_end])
power_set = set(POWER)
kept = [t for t in tokens if t not in power_set]
removed = [t for t in tokens if t in power_set]
assert len(kept) + len(removed) == len(tokens)
assert len(removed) == len(POWER), f"missing power tokens: {set(POWER) - set(removed)}"
print(f"kicad_default: {len(tokens)} -> {len(kept)} nets (removed {len(removed)} power nets)")

new_default = "(class kicad_default " + " ".join(kept) + block[hdr_end:]
new_default = new_default.replace(f'(use_via "{VIA600}")', f'(use_via "{VIA700}")')

power_class = ('(class Power ' + " ".join(POWER) + '\n'
               '      (circuit (use_via "' + VIA700 + '"))\n'
               '      (rule\n        (width 500)\n        (clearance 200)\n      )\n    )')

dsn = dsn[:start] + new_default + "\n    " + power_class + dsn[end:]
open("Platvorm.dsn", "w").write(dsn)
print("DSN prepared: vias -> Via[0-1]_700:300_um, Power class 0.5mm/0.2mm")
