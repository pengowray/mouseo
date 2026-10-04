"""What each held thumb button does. The router (router.py) calls these.

A control gets press() when its button goes down, wheel(up) per wheel step, button(code) for
middle click or a tilt (return True to swallow it), tap() if released without doing anything,
and release() when the button comes up.
"""
import logging
from evdev import ecodes as e
from . import audio, players
from .keys import MIDDLE, TILT_LEFT, TILT_RIGHT
from .util import bar, app_label

log = logging.getLogger(__name__)

MEDIA_COMMANDS = {MIDDLE: 'play-pause', TILT_LEFT: 'previous', TILT_RIGHT: 'next'}
MEDIA_KEYS = {MIDDLE: e.KEY_PLAYPAUSE, TILT_LEFT: e.KEY_PREVIOUSSONG, TILT_RIGHT: e.KEY_NEXTSONG}


class Control:
    def press(self): pass
    def wheel(self, up): pass
    def button(self, code): return False
    def tap(self): pass
    def release(self): pass


class AppControl(Control):
    """Hold + wheel: one app's volume. Hold + middle click / tilts: its play/pause, previous, next.

    `choose_app` picks the app when first needed in each hold.
    """

    def __init__(self, ctx, choose_app, step, missing=('App volume', 'No app to control')):
        self.ctx, self.choose_app, self.step, self.missing = ctx, choose_app, step, missing
        self.release()

    def release(self):
        self.app = None
        self.streams = None

    def target(self):
        if self.app is None:
            self.app = self.choose_app() or ''
            log.debug('app control target: %r', self.app)
        return self.app

    def wheel(self, up):
        app = self.target()
        if not app:
            self.ctx.notifier.show(*self.missing)
            return
        title = f'{app_label(app)} volume'
        if self.streams is None:
            self.streams = [s.index for s in audio.streams_for(app)]
        if not self.streams:
            self.ctx.notifier.show(title, 'This app is not playing any sound')
            return
        audio.change_volume(self.streams, self.step if up else -self.step)
        if (level := audio.volume_of(self.streams)) is not None:
            self.ctx.notifier.show(title, f'{bar(level, 0, 100)}  {level}%')

    def button(self, code):
        player = players.find_player(self.target()) if self.target() else None
        if player:
            players.control(player, MEDIA_COMMANDS[code])
        else:  # no media controls for this app: let the desktop pick a player
            self.ctx.output.tap([MEDIA_KEYS[code]])
        return True


class SpeedControl(Control):
    """Hold + wheel: playback speed. Hold + middle click / tilts: play/pause, seek back/forward.

    Which keys that takes depends on the focused app (config profiles).
    """

    def __init__(self, ctx, fine):
        self.ctx = ctx
        self.faster, self.slower = ('faster_fine', 'slower_fine') if fine else ('faster', 'slower')

    def send(self, action):
        if combo := self.ctx.profiles.for_app(self.ctx.focus.app_id).get(action):
            self.ctx.output.tap(combo)

    def wheel(self, up):
        self.send(self.faster if up else self.slower)

    def button(self, code):
        self.send({MIDDLE: 'play_pause', TILT_LEFT: 'back', TILT_RIGHT: 'forward'}[code])
        return True


class ZoomControl(Control):
    """Hold + wheel: COSMIC screen zoom (Super+= / Super+-)."""

    KEYS = [e.KEY_LEFTMETA, e.KEY_EQUAL, e.KEY_MINUS]

    def __init__(self, ctx):
        self.ctx = ctx

    def wheel(self, up):
        self.ctx.output.tap([e.KEY_LEFTMETA, e.KEY_EQUAL if up else e.KEY_MINUS])


class DpiControl(Control):
    """Hold + wheel: DPI in fixed steps, shown at once and sent in the background. Tap: `tap_combo`."""

    def __init__(self, ctx, worker, lo, hi, step, tap_combo):
        self.ctx, self.worker = ctx, worker
        self.lo, self.hi, self.step = lo, hi, step
        self.tap_combo = tap_combo
        self.shown = None

    def press(self):
        self.shown = None
        self.worker.request(refresh=True)  # DPI may have changed on the mouse (Hyper + thumb 3 / 9)

    def wheel(self, up):
        current = self.shown or self.worker.current
        if current is None:
            reason = self.worker.error or 'still connecting to OpenRazer'
            self.ctx.notifier.show('DPI', f'Cannot change DPI: {reason}')
            self.worker.request(refresh=True)
            return
        new = min(self.hi, max(self.lo, (current // self.step + (1 if up else -1)) * self.step))
        self.shown = new
        self.ctx.notifier.show('DPI', f'{bar(new, self.lo, self.hi)}  {new}')
        if new != current:
            self.worker.request(new)
        log.debug('dpi %s -> %s', current, new)

    def tap(self):
        self.ctx.output.tap(self.tap_combo)
