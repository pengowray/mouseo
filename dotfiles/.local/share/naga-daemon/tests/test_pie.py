import unittest
from naga_daemon.audio import Stream
from naga_daemon.pie import assign_slots, UP, DOWN


def stream(index, app, corked=False, percent=50):
    name = ''.join(c for c in app.lower() if c.isalnum())
    return Stream(index=str(index), app=app, names={name}, corked=corked, percent=percent)


class AssignSlotsTest(unittest.TestCase):
    def test_focused_app_is_up_even_when_silent(self):
        slots = assign_slots('org.kde.kate', [stream(1, 'Spotify')], playing=set())
        self.assertEqual(slots[UP].note, 'No sound')
        self.assertEqual(slots[DOWN].label, 'Spotify')

    def test_focused_app_streams_are_grouped(self):
        slots = assign_slots('firefox', [stream(1, 'Firefox', percent=30), stream(2, 'Firefox', percent=60)], set())
        self.assertEqual(slots[UP].streams, ['1', '2'])
        self.assertEqual(slots[UP].level, 60)
        self.assertNotIn(DOWN, slots)

    def test_playing_app_goes_down_before_paused_and_quiet_ones(self):
        streams = [stream(1, 'VLC media player', corked=True), stream(2, 'Discord'), stream(3, 'Spotify')]
        slots = assign_slots('', streams, playing={'spotify'})
        self.assertNotIn(UP, slots)
        self.assertEqual(slots[DOWN].label, 'Spotify')
        self.assertEqual(slots[2].label, 'Discord')      # right
        self.assertEqual(slots[6].note, 'Paused')        # left

    def test_speech_dispatcher_is_left_out(self):
        slots = assign_slots('', [stream(1, 'speech-dispatcher-dummy')], set())
        self.assertEqual(slots, {})


if __name__ == '__main__':
    unittest.main()
