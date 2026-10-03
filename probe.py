#!/usr/bin/env python3
"""Read-only: print device info and every button assignment the mouse reports."""
import sys
from naga import Naga, describe, pt

n = Naga()
print('device', n.path)
for name, cmd, size in [('serial', 0x0082, 16), ('firmware', 0x0081, 4), ('device mode', 0x0084, 2),
                        ('profiles total', 0x058a, 1), ('profiles in use', 0x0580, 1)]:
    try:
        print(f'{name:<16}', n.transact(cmd, size=size).hex(' '))
    except pt.RazerException as e:
        print(f'{name:<16} error: {e}')

profiles = [int(a) for a in sys.argv[1:]] or [1]
for profile in profiles:
    for hs in (0, 1):
        print(f'\n== profile {profile}, hypershift {"on" if hs else "off"} ==')
        for button in range(0x01, 0x80):
            try:
                bf = n.get_button_function(button, hs, profile)
            except pt.RazerException as e:
                continue
            print(f'  button 0x{button:02x}: {describe(bf)}')
