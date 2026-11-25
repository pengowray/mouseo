"""Picks the desktop once at startup. What differs between them (focus tracking, the system volume,
screen zoom, and how the overlay gets windows above the others) is in cosmic.py and gnome.py."""
import os
from evdev import ecodes as e

# Keys a desktop may send through the virtual keyboard
KEYS = [e.KEY_LEFTMETA, e.KEY_EQUAL, e.KEY_MINUS, e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN]


def detect(env=os.environ):
    """'gnome' or 'cosmic', from XDG_CURRENT_DESKTOP (such as 'COSMIC' or 'pop:GNOME')."""
    names = env.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
    return 'gnome' if 'gnome' in names and 'cosmic' not in names else 'cosmic'


def make(output, name=None):
    if (name or detect()) == 'gnome':
        from .gnome import Gnome
        return Gnome(output)
    from .cosmic import Cosmic
    return Cosmic(output)
