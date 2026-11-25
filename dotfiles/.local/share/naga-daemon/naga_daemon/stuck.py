"""Notices when the mouse reports a tilt key held down for minutes.

The mouse sometimes keeps Left Ctrl and F18 (the keys its tilts send) in every report until it is
turned off and on. The kernel then treats them as held, so a tilt sends no new press, and push to
talk (F18) stays on.
"""
import asyncio, logging, time
from .keys import TILT_LEFT, TILT_RIGHT

log = logging.getLogger(__name__)

STUCK_AFTER = 180   # seconds a tilt key has to stay down
CHECK_EVERY = 15    # seconds


class StuckTilts:
    def __init__(self, devices, on_stuck):
        self.devices = devices
        self.on_stuck = on_stuck   # called with the key code, once each time a key gets stuck
        self.since = {}            # key code -> when it was first seen held
        self.reported = set()

    def check(self, held, now):
        """The tilt keys that have just passed STUCK_AFTER, given the keys held now."""
        for code in (TILT_LEFT, TILT_RIGHT):
            if code in held:
                self.since.setdefault(code, now)
            else:
                self.since.pop(code, None)
                self.reported.discard(code)
        stuck = [code for code, t in self.since.items() if now - t >= STUCK_AFTER and code not in self.reported]
        self.reported.update(stuck)
        return stuck

    async def run(self):
        while True:
            await asyncio.sleep(CHECK_EVERY)
            held = set()
            for dev in self.devices:
                try:
                    held.update(dev.active_keys())
                except OSError:
                    pass   # the device went away; forward() notices
            for code in self.check(held, time.monotonic()):
                self.on_stuck(code)
