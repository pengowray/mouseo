import unittest
from naga_daemon.keys import parse_combo
from naga_daemon.profiles import Profiles
from naga_daemon.util import bar, app_label, names_match, normalize
from naga_daemon.focus import Focus
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
        f = Focus()
        f.update({'params': {'state': {'apps': [{'app_id': 'kitty', 'state': []},
                                                {'app_id': 'firefox', 'state': ['maximized', 'activated']}]}}})
        self.assertEqual(f.app_id, 'firefox')
