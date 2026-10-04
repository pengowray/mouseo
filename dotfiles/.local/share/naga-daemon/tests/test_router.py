"""Run with: python3 -m unittest discover -s ~/.local/share/naga-daemon/tests -t ~/.local/share/naga-daemon"""
import unittest
from evdev import InputEvent, ecodes as e
from naga_daemon import keys
from naga_daemon.controls import Control
from naga_daemon.router import Router

KBD, PTR = '/dev/input/kbd', '/dev/input/ptr'


def key(code, value):
    return InputEvent(0, 0, e.EV_KEY, code, value)


def wheel(steps):
    return InputEvent(0, 0, e.EV_REL, e.REL_WHEEL, steps)


class Recorder(Control):
    def __init__(self, swallow=True):
        self.calls, self.swallow = [], swallow
    def press(self): self.calls.append('press')
    def wheel(self, up): self.calls.append('up' if up else 'down')
    def button(self, code): self.calls.append(keys.key_name(code)); return self.swallow
    def tap(self): self.calls.append('tap')
    def release(self): self.calls.append('release')


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.ctl = Recorder()
        self.ptt = []
        self.router = Router({keys.DPI: self.ctl}, self.ptt.append)

    def send(self, source, *events):
        return [self.router.handle(source, ev) for ev in events]

    def test_tap(self):
        self.assertEqual(self.send(KBD, key(keys.DPI, 1), key(keys.DPI, 2), key(keys.DPI, 0)), [True] * 3)
        self.assertEqual(self.ctl.calls, ['press', 'tap', 'release'])

    def test_wheel_while_held_is_used_and_not_a_tap(self):
        self.send(KBD, key(keys.DPI, 1))
        self.assertEqual(self.send(PTR, wheel(2), InputEvent(0, 0, e.EV_REL, e.REL_WHEEL_HI_RES, 240)), [True, True])
        self.send(KBD, key(keys.DPI, 0))
        self.assertEqual(self.ctl.calls, ['press', 'up', 'up', 'release'])

    def test_wheel_without_carrier_passes_through(self):
        self.assertEqual(self.send(PTR, wheel(-1)), [False])

    def test_redirected_button_swallows_its_release_after_the_carrier_is_released(self):
        self.send(KBD, key(keys.DPI, 1))
        self.assertTrue(self.router.handle(PTR, key(e.BTN_MIDDLE, 1)))
        self.send(KBD, key(keys.DPI, 0))
        self.assertTrue(self.router.handle(PTR, key(e.BTN_MIDDLE, 0)))
        self.assertFalse(self.router.handle(PTR, key(e.BTN_MIDDLE, 1)))  # next click is normal

    def test_unhandled_button_passes_through_but_cancels_the_tap(self):
        self.ctl.swallow = False
        self.send(KBD, key(keys.DPI, 1))
        self.assertFalse(self.router.handle(PTR, key(e.BTN_MIDDLE, 1)))
        self.send(KBD, key(keys.DPI, 0))
        self.assertNotIn('tap', self.ctl.calls)

    def test_other_keys_pass_through_and_cancel_the_tap(self):
        self.send(KBD, key(keys.DPI, 1))
        self.assertFalse(self.router.handle(KBD, key(e.KEY_ESC, 1)))
        self.send(KBD, key(keys.DPI, 0))
        self.assertNotIn('tap', self.ctl.calls)

    def test_push_to_talk_when_no_carrier_held(self):
        self.assertEqual(self.send(KBD, key(keys.TILT_RIGHT, 1), key(keys.TILT_RIGHT, 2), key(keys.TILT_RIGHT, 0)),
                         [True] * 3)
        self.assertEqual(self.ptt, [1, 0])

    def test_tilt_left_ctrl_passes_through_without_carrier(self):
        self.assertFalse(self.router.handle(KBD, key(keys.TILT_LEFT, 1)))

    def test_second_carrier_during_a_hold_is_ignored(self):
        other = Recorder()
        self.router.controls[keys.ZOOM] = other
        self.send(KBD, key(keys.DPI, 1), key(keys.ZOOM, 1), key(keys.ZOOM, 0), key(keys.DPI, 0))
        self.assertEqual(other.calls, [])

    def test_push_to_talk_disabled_passes_f18_through(self):
        router = Router({}, None)
        self.assertFalse(router.handle(KBD, key(keys.TILT_RIGHT, 1)))
