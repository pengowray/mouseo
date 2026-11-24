import unittest
from naga_daemon.keys import parse_combo
from naga_daemon.profiles import Profiles
from naga_daemon.util import bar, app_label, names_match, normalize
from naga_daemon.focus import CosmicFocus, parse_gnome_signal
from naga_daemon.desktop import detect, next_zoom
from evdev import ecodes as e


class PartsTest(unittest.TestCase):
    def test_parse_combo(self):
        self.assertEqual(parse_combo('shift+dot'), [e.KEY_LEFTSHIFT, e.KEY_DOT])
        self.assertEqual(parse_combo('alt+left'), [e.KEY_LEFTALT, e.KEY_LEFT])
        with self.assertRaises(ValueError):
            parse_combo('shift+nosuchkey')

    def test_bar(self):
        self.assertEqual(bar(200, 200, 2400), '⬜' * 12)
        self.assertEqual(bar(2400, 200, 2400), '🟩' * 12)
        self.assertEqual(bar(250, 200, 2400).count('🟩'), 1)  # anything above the minimum shows one square

    def test_names(self):
        self.assertEqual(app_label('VLC media player (LibVLC 3.0.23)'), 'VLC media player')
        self.assertEqual(app_label('com.google.Chrome'), 'Chrome')
        self.assertTrue(names_match(normalize('firefox-bin'), normalize('firefox')))
        self.assertFalse(names_match('vl', 'vlc'))

    def test_profiles(self):
        p = Profiles({'browser': {'apps': ['firefox'], 'back': 'left'}, 'default': {'back': 'alt+left'}})
        self.assertEqual(p.for_app('firefox'), {'back': [e.KEY_LEFT]})
        self.assertEqual(p.for_app('kitty'), {'back': [e.KEY_LEFTALT, e.KEY_LEFT]})
        with self.assertRaises(ValueError):
            Profiles({'x': {'fastr': 'dot'}})

    def test_focus_update(self):
        f = CosmicFocus()
        f.update({'params': {'state': {'apps': [{'app_id': 'kitty', 'state': []},
                                                {'app_id': 'firefox', 'state': ['maximized', 'activated']}]}}})
        self.assertEqual(f.app_id, 'firefox')

    def test_gnome_focus_signal(self):
        self.assertEqual(parse_gnome_signal("/io/mouseo/Naga: io.mouseo.Naga.FocusChanged ('firefox', 'DP-1')\n"),
                         ('firefox', 'DP-1'))
        self.assertEqual(parse_gnome_signal("/io/mouseo/Naga: io.mouseo.Naga.FocusChanged ('', '')\n"), ('', ''))
        self.assertIsNone(parse_gnome_signal('The name io.mouseo.Naga is owned by :1.40\n'))

    def test_detect_desktop(self):
        self.assertEqual(detect({'XDG_CURRENT_DESKTOP': 'GNOME'}), 'gnome')
        self.assertEqual(detect({'XDG_CURRENT_DESKTOP': 'pop:GNOME'}), 'gnome')
        self.assertEqual(detect({'XDG_CURRENT_DESKTOP': 'COSMIC'}), 'cosmic')
        self.assertEqual(detect({}), 'cosmic')

    def test_next_zoom(self):
        self.assertEqual(next_zoom(1.0, True, 1.25, 32), 1.25)
        self.assertEqual(next_zoom(1.25, False, 1.25, 32), 1.0)
        self.assertEqual(next_zoom(1.0, False, 1.25, 32), 1.0)
        self.assertEqual(next_zoom(30.0, True, 1.25, 32), 32)

    def test_sleep_signal(self):
        from naga_daemon.sleep import parse
        line = '/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep ({},)\n'
        self.assertIs(parse(line.format('true')), True)
        self.assertIs(parse(line.format('false')), False)
        self.assertIsNone(parse('/org/freedesktop/login1: org.freedesktop.login1.Manager.SessionNew '
                                "('3', objectpath '/org/freedesktop/login1/session/_33')\n"))
        self.assertIsNone(parse('Monitoring signals on object /org/freedesktop/login1 owned by org.freedesktop.login1\n'))


class MonitorParsingTest(unittest.TestCase):
    def test_parse_getvcp(self):
        from naga_daemon.monitors import parse_getvcp
        self.assertEqual(parse_getvcp('VCP 10 C 70 100\nVCP 14 CNC x00 x0b x00 x06\n'), {0x10: 70, 0x14: 6})
        self.assertEqual(parse_getvcp('VCP 14 SNC x05'), {0x14: 5})

    def test_detect_uses_backlight_for_laptop_panel(self):
        from unittest import mock
        from types import SimpleNamespace
        from naga_daemon import monitors
        out = ('Invalid display\n   I2C bus:          /dev/i2c-10\n   DRM connector:    card0-eDP-1\n'
               '   Monitor:          CMN::\n\n'
               'Display 1\n   I2C bus:  /dev/i2c-5\n   DRM connector:           card0-DP-1\n'
               '   Monitor:                 GSM:LG ULTRAGEAR:304NTJJ4A468\n')
        with mock.patch.object(monitors.subprocess, 'run', return_value=SimpleNamespace(stdout=out)), \
             mock.patch.object(monitors, 'backlights', return_value=['intel_backlight']):
            found = monitors.detect()
        self.assertEqual([(m.connector, m.bus, m.model, m.backlight) for m in found],
                         [('DP-1', 5, 'LG ULTRAGEAR', None), ('eDP-1', None, 'Laptop screen', 'intel_backlight')])


class PresetPositionTest(unittest.TestCase):
    def test_current_index_matches_gains(self):
        from types import SimpleNamespace
        from naga_daemon.controls import MonitorControl
        presets = [(0x0b, 'Warm 2', [100, 86, 62]), (0x0b, 'Warm 1', [100, 93, 78]), (0x04, '5000 K', None)]
        m = SimpleNamespace(values={0x14: 0x0b, 0x16: 100, 0x18: 93, 0x1a: 78})
        self.assertEqual(MonitorControl.current_index(m, presets), 1)
        m.values = {0x14: 0x04}
        self.assertEqual(MonitorControl.current_index(m, presets), 2)
        m.values = {0x14: 0x0b, 0x16: 50, 0x18: 50, 0x1a: 50}   # User 1 with other gains
        self.assertEqual(MonitorControl.current_index(m, presets), 1)


class ZoomControlTest(unittest.TestCase):
    def test_tilts_and_middle_click_zoom_the_app(self):
        from types import SimpleNamespace
        from naga_daemon.controls import ZoomControl
        from naga_daemon.keys import MIDDLE, TILT_LEFT, TILT_RIGHT
        sent = []
        zoom = ZoomControl(SimpleNamespace(output=SimpleNamespace(tap=sent.append)))
        self.assertTrue(all(zoom.button(c) for c in (TILT_LEFT, TILT_RIGHT, MIDDLE)))
        self.assertEqual(sent, [[e.KEY_LEFTCTRL, e.KEY_MINUS], [e.KEY_LEFTCTRL, e.KEY_EQUAL], [e.KEY_LEFTCTRL, e.KEY_0]])
        self.assertTrue({k for combo in sent for k in combo} <= set(ZoomControl.KEYS))
