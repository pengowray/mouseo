"""Onboard layout for the Naga V2 HyperSpeed, based on Synapse profile "General v5".

Keys F13-F17, F19 and F24 are carriers for naga-daemon.py, which gives them the
behaviour the Windows AHK scripts used to provide. Everything else works with
no software running.
"""
from qdrazer.protocol import ButtonFunction, FnKeyboardModifier as Mod, FnMouse

# HID keyboard usages
# F19 and F24 have no meaning in the standard keymap; F21/F22 would toggle the touchpad without the daemon.
F13, F14, F15, F16, F17, F18, F19, F24 = 0x68, 0x69, 0x6a, 0x6b, 0x6c, 0x6d, 0x6e, 0x73
ESC, END, KP_ENTER = 0x29, 0x4d, 0x58
LCTRL, LALT = 0xe0, 0xe2
# HID consumer usages
PLAY, NEXT, PREV, VOL_UP, VOL_DOWN = 0xcd, 0xb5, 0xb6, 0xe9, 0xea


def key(k, mod=Mod(0)):
    return ButtonFunction().set_keyboard(k, modifier=mod)

def mouse(fn):
    return ButtonFunction().set_mouse(fn)

def media(usage):
    return ButtonFunction().set_consumer(usage)

def hyper():
    return ButtonFunction().set_hypershift_toggle()

def off():
    return ButtonFunction().set_disabled()


# Mouse button id: (label, normal, while holding Hyper)
LAYOUT = {
    0x01: ('Left click',        mouse(FnMouse.LEFT),       mouse(FnMouse.LEFT)),
    0x02: ('Right click',       mouse(FnMouse.RIGHT),      mouse(FnMouse.RIGHT)),
    0x03: ('Middle click',      mouse(FnMouse.MIDDLE),     media(PLAY)),
    0x09: ('Wheel up',          mouse(FnMouse.WHEEL_UP),   media(VOL_UP)),
    0x0a: ('Wheel down',        mouse(FnMouse.WHEEL_DOWN), media(VOL_DOWN)),
    0x0b: ('Top button 1',      hyper(),                   hyper()),
    0x0c: ('Top button 2',      key(F18),                  key(F18)),       # push to talk (daemon turns it into mouse button 12)
    0x34: ('Tilt left',         key(LCTRL),                media(PREV)),
    0x35: ('Tilt right',        key(F18),                  media(NEXT)),    # push to talk
    0x40: ('Thumb 1',           key(F24),                  key(KP_ENTER)),  # daemon: hold + wheel screen zoom
    0x41: ('Thumb 2',           mouse(FnMouse.MIDDLE),     media(PLAY)),
    0x42: ('Thumb 3',           key(F19),                  off()),  # daemon: tap Ctrl+Home, hold + wheel DPI
    0x43: ('Thumb 4',           key(LALT, Mod.LEFT_SHIFT), media(PREV)),
    0x44: ('Thumb 5',           hyper(),                   hyper()),
    0x45: ('Thumb 6',           key(END, Mod.LEFT_CONTROL), media(NEXT)),
    0x46: ('Thumb 7',           key(F17),                  off()),  # daemon: background app volume
    0x47: ('Thumb 8',           key(F13),                  off()),    # daemon: system volume
    0x48: ('Thumb 9',           key(F14),                  off()),  # daemon: Spotify volume
    0x49: ('Thumb 10',          key(ESC),                  off()),
    0x4a: ('Thumb 11',          key(F16),                  off()),  # daemon: YouTube frame step
    0x4b: ('Thumb 12',          key(F15),                  off()), # daemon: YouTube speed
}
