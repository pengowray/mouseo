from evdev import ecodes as e
from .keys import REDIRECTABLE, TILT_RIGHT


class Router:
    """Decides what happens to each input event from the mouse.

    While a carrier key is held, its control gets the wheel and the redirectable buttons.
    Everything else passes through. handle() returns True if the event was used up.
    One router is shared by all of the mouse's input devices, since a carrier key arrives on
    the keyboard device and the wheel on the pointer device.
    """

    def __init__(self, controls, push_to_talk=None):
        self.controls = controls          # carrier key code -> Control
        self.push_to_talk = push_to_talk  # callable(value), or None to pass F18 through
        self.held = None                  # carrier key code being held
        self.used = False                 # whether anything happened during this hold
        self.swallowed = set()            # (source, code) of presses whose release must be dropped too

    def handle(self, source, ev):
        if ev.type == e.EV_KEY and ev.code in self.controls:
            self._carrier(ev)
            return True
        control = self.controls.get(self.held)

        if control and ev.type == e.EV_KEY and ev.value == 1:
            self.used = True  # pressing anything else during a hold means it wasn't a tap

        if control and ev.type == e.EV_REL:
            if ev.code == e.REL_WHEEL:
                self.used = True
                for _ in range(abs(ev.value)):
                    control.wheel(ev.value > 0)
                return True
            if ev.code == e.REL_WHEEL_HI_RES:
                return True

        if ev.type == e.EV_KEY and ev.code in REDIRECTABLE:
            key = (source, ev.code)
            if ev.value == 1 and control and control.button(ev.code):
                self.swallowed.add(key)
                return True
            if key in self.swallowed:
                if ev.value == 0:
                    self.swallowed.discard(key)
                return True
            if ev.code == TILT_RIGHT and self.push_to_talk:
                if ev.value in (0, 1):
                    self.push_to_talk(ev.value)
                return True
        return False

    def _carrier(self, ev):
        if ev.value == 1 and self.held is None:
            self.held, self.used = ev.code, False
            self.controls[ev.code].press()
        elif ev.value == 0 and self.held == ev.code:
            control = self.controls[ev.code]
            if not self.used:
                control.tap()
            control.release()
            self.held = None
