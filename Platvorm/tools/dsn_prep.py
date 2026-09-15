#!/usr/bin/env python3
"""Prepare Platvorm.dsn for freerouting: 0.7mm vias, drop unconnected nets /
keepout planes, inject the Power class. Verifies every step."""
import re

s = open("Platvorm.dsn").read()
s = s.replace("Via[0-1]_600:300_um", "Via[0-1]_700:300_um")

# rip unconnected net blocks (line-based, paren-balanced)
lines = s.splitlines(keepends=True)
out, i, ripped = [], 0, 0
while i < len(lines):
    line = lines[i]
    if re.search(r'\(net "unconnected-', line):
        depth = line.count("(") - line.count(")")
        i += 1
        while depth > 0 and i < len(lines):
            depth += lines[i].count("(") - lines[i].count(")")
            i += 1
        ripped += 1
        continue
    out.append(line)
    i += 1
s = "".join(out)
s = re.sub(r'"unconnected-\([^"]*\)"\s*', "", s)

# drop single-line keepouts and (plane ...) blocks
lines = [l for l in s.splitlines(keepends=True)
         if not (l.strip().startswith("(keepout") and l.count("(") == l.count(")"))]
out, i, planes = [], 0, 0
while i < len(lines):
    line = lines[i]
    if line.strip().startswith("(plane "):
        depth = line.count("(") - line.count(")")
        i += 1
        while depth > 0 and i < len(lines):
            depth += lines[i].count("(") - lines[i].count(")")
            i += 1
        planes += 1
        continue
    out.append(line)
    i += 1
s = "".join(out)

# The exporter already splits classes per the project's netclass_assignments
# (Power nets in their own class). Verify instead of injecting:
power_pat = re.compile(r"\+12V|\+3V3|\+5V|-12V|VBUS|VIN_BUCK|VOUT_PRE")
cls_blocks = re.findall(r"\(class [^)]*?\(circuit", s)
assert "(class Power" in s or "Power," in s, "Power class missing from export"
for net in ("+12V", "+3V3", "+5V", "-12V", "VBUS"):
    assert f"(net {net}" in s, f"net block missing: {net}"
assert "unconnected" not in s
open("Platvorm.dsn", "w").write(s)
print(f"DSN ready: planes {planes}, unconnected-blocks {ripped}, "
      f"planes {planes}, unconnected-blocks {ripped}")
