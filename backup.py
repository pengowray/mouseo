#!/usr/bin/env python3
"""Save the raw onboard assignments of every thumb-grid and top button to a JSON file."""
import json, sys, time
from naga import Naga, pt

BUTTONS = [0x01, 0x02, 0x03, 0x09, 0x0a, 0x0b, 0x0c, 0x34, 0x35] + list(range(0x40, 0x4c))

n = Naga()
out = {}
for hs in (0, 1):
    for b in BUTTONS:
        out[f'{b:02x}/{hs}'] = bytes(n.get_button_function(b, hs)).hex()
path = sys.argv[1] if len(sys.argv) > 1 else time.strftime('backup-%Y%m%d-%H%M%S.json')
json.dump(out, open(path, 'w'), indent=1)
print('saved', len(out), 'assignments to', path)
