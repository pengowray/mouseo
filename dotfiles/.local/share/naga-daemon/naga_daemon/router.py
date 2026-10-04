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
        self.swallowed = {}               # (source, code) of presses whose release must be dropped too -> control
        self.motion = [0, 0]              # pointer movement captured since the last sync event

    def handle(self, source, ev):
        if ev.type == e.EV_KEY and ev.code in self.controls:
            self._carrier(ev)
            return True
        control = self.controls.get(self.held)

        if control and ev.type == e.EV_KEY and ev.value == 1:
            self.used = True  # pressing anything else during a hold means it wasn't a tap

        if ev.type == e.EV_REL:
            if control and ev.code == e.REL_WHEEL:
                self.used = True
                for _ in range(abs(ev.value)):
                    control.wheel(ev.value > 0)
                return True
            if control and ev.code == e.REL_WHEEL_HI_RES:
                return True
            if control and ev.code in (e.REL_X, e.REL_Y) and control.capturing():
                self.motion[ev.code == e.REL_Y] += ev.value
                return True

        if ev.type == e.EV_SYN and any(self.motion):
            if control and control.capturing():
                control.motion(*self.motion)
            self.motion = [0, 0]

        if ev.type == e.EV_KEY:
            key = (source, ev.code)
            redirect = ev.code in REDIRECTABLE or (control and ev.code in control.extra_buttons)
            if ev.value == 1 and control and redirect and control.button(ev.code):
                self.swallowed[key] = control
                return True
            if key in self.swallowed:
                if ev.value == 0:
                    self.swallowed.pop(key).button_up(ev.code)
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
