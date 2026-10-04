#!/usr/bin/env python3
"""For one minute, show a notification whenever either top button is pressed.

Top button 1 is Hyper, which sends nothing on its own, so it temporarily sends F24 instead.
naga-daemon is paused during the test, then everything is put back.
"""
import select, subprocess, sys, time
import evdev
from evdev import ecodes as e
from naga import Naga, pt
from layout import LAYOUT, F24

SECONDS = 60
TOP_1, TOP_2 = 0x0b, 0x0c
NAMES = {e.KEY_F24: ('Top button 1', 'set to Hyper'), e.KEY_F18: ('Top button 2', 'set to push to talk')}


def notify(title, body, seconds=3):
    subprocess.run(['notify-send', '-a', 'Naga', '-t', str(seconds * 1000), title, body])


mouse = Naga()
service_was_active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'naga-daemon']).returncode == 0
try:
    if service_was_active:
        subprocess.run(['systemctl', '--user', 'stop', 'naga-daemon'], check=True)
    mouse.set_button_function(TOP_1, pt.ButtonFunction().set_keyboard(F24))
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    devices = {d.fd: d for d in devices if 'Naga V2 HyperSpeed' in d.name}
    notify('Top button test', f'Press each top button. Running for {SECONDS} seconds.', 5)
    print(f'Press each top button. Running for {SECONDS} seconds.')
    end = time.time() + SECONDS
    while (left := end - time.time()) > 0:
        for fd in select.select(list(devices), [], [], left)[0]:
            for ev in devices[fd].read():
                if ev.type == e.EV_KEY and ev.value == 1 and ev.code in NAMES:
                    title, body = NAMES[ev.code]
                    print(title, 'pressed')
                    notify(title, body)
finally:
    _, normal, hyper = LAYOUT[TOP_1]
    mouse.set_button_function(TOP_1, normal)
    mouse.set_button_function(TOP_1, hyper, 1)
    if service_was_active:
        subprocess.run(['systemctl', '--user', 'start', 'naga-daemon'])
    notify('Top button test', 'Finished. Top button 1 is Hyper again.', 5)
    print('Finished. Top button 1 is Hyper again.')
