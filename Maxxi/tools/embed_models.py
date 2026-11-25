#!/usr/bin/env python3
"""Embed the converted GLB models into power-supply-visual.html as base64.

Expects the GLBs produced by the STEP->GLB conversion (gmsh + trimesh, see
/tmp/step2glb.py or rebuild: Maxxi/footprints/maxxi_custom.3dshapes/*.step).
Re-run this after changing the models; it swaps the models-json block in place.
"""
import base64
import json
import re
import sys

HTML = 'Maxxi/power-supply-visual.html'
GLB_DIR = sys.argv[1] if len(sys.argv) > 1 else '/tmp/glbs'
KEYS = ['usbc', 'ind', 'essop', 'dfn8', 'hdr16']

models = {}
for k in KEYS:
    with open(f'{GLB_DIR}/{k}.glb', 'rb') as f:
        models[k] = base64.b64encode(f.read()).decode()
blob = json.dumps(models)

src = open(HTML).read()
new, n = re.subn(r'(<script id="models-json" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), src, count=1, flags=re.S)
if n != 1:
    sys.exit('models-json block not found')
open(HTML, 'w').write(new)
print(f'embedded {len(models)} models, html now {len(new)/1024:.0f} KB')
