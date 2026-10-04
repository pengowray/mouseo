import logging, threading
import evdev
from evdev import ecodes as e
from .keys import OUR_PREFIX, key_name

log = logging.getLogger(__name__)

POINTER_BUTTONS = [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE, e.BTN_SIDE, e.BTN_EXTRA,
                   e.BTN_FORWARD, e.BTN_BACK, e.BTN_TASK]


class Output:
    """Virtual keyboard and mouse for the keys and buttons the daemon sends."""

    def __init__(self, keys):
        self.keyboard = evdev.UInput({e.EV_KEY: sorted(set(keys))}, name=f'{OUR_PREFIX} keys')
        self.pointer = evdev.UInput({e.EV_KEY: POINTER_BUTTONS, e.EV_REL: [e.REL_X, e.REL_Y]},
                                    name=f'{OUR_PREFIX} buttons')
        self.lock = threading.Lock()   # resize.py writes from its own thread

    def tap(self, combo):
        """Press and release a key combination, e.g. [KEY_LEFTCTRL, KEY_HOME]."""
        log.debug('send %s', '+'.join(key_name(c) for c in combo))
        with self.lock:
            self._tap(combo)

    def _tap(self, combo):
        for code in combo:
            self.keyboard.write(e.EV_KEY, code, 1)
        self.keyboard.syn()
        for code in reversed(combo):
            self.keyboard.write(e.EV_KEY, code, 0)
        self.keyboard.syn()

    def click(self, code):
        log.debug('click %s', key_name(code))
        self.button(code, 1)
        self.button(code, 0)

    def button(self, code, value):
        with self.lock:
            self.pointer.write(e.EV_KEY, code, value)
            self.pointer.syn()

    def key(self, code, value):
        with self.lock:
            self.keyboard.write(e.EV_KEY, code, value)
            self.keyboard.syn()

    def move(self, dx, dy):
        with self.lock:
            if dx:
                self.pointer.write(e.EV_REL, e.REL_X, dx)
            if dy:
                self.pointer.write(e.EV_REL, e.REL_Y, dy)
            self.pointer.syn()
