import unittest
from evdev import InputEvent, ecodes as e
from naga_daemon import keys
from naga_daemon.controls import Control
from naga_daemon.resize import corner, project
from naga_daemon.router import Router


def win(x, y, w, h):
    return {'x': x, 'y': y, 'width': w, 'height': h}


class CornerTest(unittest.TestCase):
    def test_bottom_right(self):
        self.assertEqual(corner(win(10, 10, 800, 450), win(10, 10, 803, 453)), (1, 1))

    def test_top_left(self):
        self.assertEqual(corner(win(10, 10, 800, 450), win(13, 13, 797, 447)), (-1, -1))

    def test_top_right(self):
        self.assertEqual(corner(win(10, 10, 800, 450), win(10, 13, 803, 447)), (1, -1))

    def test_nothing_moved(self):
        self.assertIsNone(corner(win(10, 10, 800, 450), win(10, 10, 800, 450)))

    def test_project_onto_diagonal(self):
        fx, fy = project(10, 0, (16, 9))
        self.assertAlmostEqual(fy / fx, 9 / 16)


class Capturer(Control):
    extra_buttons = frozenset({e.BTN_RIGHT})
    def __init__(self):
        self.moves, self.ups, self.active = [], [], False
    def button(self, code):
        self.active = code == e.BTN_RIGHT
        return self.active
    def button_up(self, code): self.ups.append(code); self.active = False
    def capturing(self): return self.active
    def motion(self, dx, dy): self.moves.append((dx, dy))


def ev(type_, code, value):
    return InputEvent(0, 0, type_, code, value)


class RouterMotionTest(unittest.TestCase):
    def test_right_drag_motion_is_captured_until_release(self):
        ctl = Capturer()
        router = Router({keys.WINDOW: ctl})
        KBD, PTR = 'kbd', 'ptr'
        self.assertTrue(router.handle(KBD, ev(e.EV_KEY, keys.WINDOW, 1)))
        self.assertTrue(router.handle(PTR, ev(e.EV_KEY, e.BTN_RIGHT, 1)))
        self.assertTrue(router.handle(PTR, ev(e.EV_REL, e.REL_X, 4)))
        self.assertTrue(router.handle(PTR, ev(e.EV_REL, e.REL_Y, -2)))
        self.assertFalse(router.handle(PTR, ev(e.EV_SYN, e.SYN_REPORT, 0)))
        self.assertEqual(ctl.moves, [(4, -2)])
        self.assertTrue(router.handle(PTR, ev(e.EV_KEY, e.BTN_RIGHT, 0)))
        self.assertEqual(ctl.ups, [e.BTN_RIGHT])
        self.assertFalse(router.handle(PTR, ev(e.EV_REL, e.REL_X, 4)))   # passes through again

    def test_right_click_passes_through_without_a_capturing_control(self):
        router = Router({keys.DPI: Control()})
        router.handle('kbd', ev(e.EV_KEY, keys.DPI, 1))
        self.assertFalse(router.handle('ptr', ev(e.EV_KEY, e.BTN_RIGHT, 1)))


if __name__ == '__main__':
    unittest.main()
