#!/usr/bin/env python3
"""Compare the mouse's onboard buttons with layout.py, and write the differences with --write."""
import sys
import naga  # noqa: sets up the vendored qdrazer path
from naga import Naga, describe, pt
from layout import LAYOUT

write = '--write' in sys.argv
n = Naga()
changes = 0
for button, (label, *fns) in LAYOUT.items():
    for hs, want in enumerate(fns):
        have = n.get_button_function(button, hs)
        if bytes(have)[:2 + want.fn_value_length] == bytes(want)[:2 + want.fn_value_length]:
            continue
        changes += 1
        layer = 'Hyper ' if hs else ''
        print(f'{layer + label:<20} {describe(have):<60} -> {describe(want)}')
        if write:
            n.set_button_function(button, want, hs)
            back = n.get_button_function(button, hs)
            if bytes(back)[:2 + want.fn_value_length] != bytes(want)[:2 + want.fn_value_length]:
                sys.exit(f'  read-back mismatch: {describe(back)}')
if not changes:
    print('Mouse already matches layout.py')
elif not write:
    print(f'\n{changes} differences. Run with --write to apply them.')
else:
    print(f'\nWrote and verified {changes} assignments.')
