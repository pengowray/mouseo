"""Keys the onboard layout sends (see ~/projects/mouseo/layout.py), and key names in the config."""
from evdev import ecodes as e

DEVICE_NAME = 'Naga V2 HyperSpeed'
OUR_PREFIX = 'naga-daemon'   # name prefix of our own virtual devices, so we never grab them

# Carrier keys sent by held thumb buttons
FOCUSED_APP = e.KEY_F13      # thumb 8
SPOTIFY = e.KEY_F14          # thumb 9
WINDOW = e.KEY_F17           # thumb 7
SPEED = e.KEY_F15            # thumb 12
FINE_SPEED = e.KEY_F16       # thumb 11
DPI = e.KEY_F19              # thumb 2
ZOOM = e.KEY_F24             # thumb 1
MONITOR = e.KEY_RO           # thumb 4. Japanese Ro key: no meaning in a US layout, and F20-F23 mute the mic or toggle the touchpad
PIE = e.KEY_HENKAN           # thumb 5. Japanese Henkan key, also meaningless in a US layout

# Buttons that a held carrier can redirect
MIDDLE = e.BTN_MIDDLE
TILT_LEFT = e.KEY_LEFTCTRL   # the onboard layout makes tilt left send Ctrl
TILT_RIGHT = e.KEY_F18       # tilt right and top button 2 send F18 (push to talk)
REDIRECTABLE = {MIDDLE, TILT_LEFT, TILT_RIGHT}

ALIASES = {'shift': 'leftshift', 'ctrl': 'leftctrl', 'alt': 'leftalt', 'super': 'leftmeta'}


def parse_combo(text):
    """'shift+dot' -> [KEY_LEFTSHIFT, KEY_DOT]. Raises ValueError for unknown key names."""
    codes = []
    for part in text.lower().split('+'):
        name = 'KEY_' + ALIASES.get(part, part).upper()
        if not hasattr(e, name):
            raise ValueError(f'unknown key "{part}" in "{text}"')
        codes.append(getattr(e, name))
    return codes


def key_name(code):
    name = e.KEY.get(code) or e.BTN.get(code) or str(code)
    return name if isinstance(name, str) else name[0]
