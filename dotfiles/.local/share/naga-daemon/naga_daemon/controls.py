"""What each held thumb button does. The router (router.py) calls these.

A control gets press() when its button goes down, wheel(up) per wheel step, button(code) for
middle click or a tilt (return True to swallow it), tap() if released without doing anything,
and release() when the button comes up. See Control for the rest.
"""
import logging, os, shutil, subprocess, threading
from evdev import ecodes as e
from . import audio, players
from .monitors import BRIGHTNESS, COLOUR_PRESET, GAINS
from .keys import MIDDLE, TILT_LEFT, TILT_RIGHT
from .util import bar, app_label

log = logging.getLogger(__name__)

MEDIA_COMMANDS = {MIDDLE: 'play-pause', TILT_LEFT: 'previous', TILT_RIGHT: 'next'}
MEDIA_KEYS = {MIDDLE: e.KEY_PLAYPAUSE, TILT_LEFT: e.KEY_PREVIOUSSONG, TILT_RIGHT: e.KEY_NEXTSONG}


class Control:
    extra_buttons = frozenset()   # buttons besides middle click and the tilts that button() gets

    def press(self): pass
    def wheel(self, up): pass
    def button(self, code): return False
    def button_up(self, code): pass   # a button that button() swallowed was released
    def capturing(self): return False # True to get pointer movement through motion() instead of passing it on
    def motion(self, dx, dy): pass
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


class WindowControl(Control):
    """Hold + tilt right / left: keep the focused window on top or stop.
    Hold + right drag: resize the window and keep its proportions (resize.py).

    COSMIC has no "always on top", so this uses sticky: the window floats above the others
    and shows on every workspace.
    """

    extra_buttons = frozenset({e.BTN_RIGHT})

    def __init__(self, ctx, resize):
        self.ctx, self.resize = ctx, resize

    def button(self, code):
        if code == e.BTN_RIGHT:
            self.resize.start()
            return True
        if code not in (TILT_LEFT, TILT_RIGHT):
            return False
        threading.Thread(target=self._set, args=(code == TILT_RIGHT,), daemon=True).start()
        return True

    def button_up(self, code):
        if code == e.BTN_RIGHT:
            self.resize.stop()

    def capturing(self):
        return self.resize.active

    def motion(self, dx, dy):
        self.resize.motion(dx, dy)

    def release(self):
        self.resize.stop()

    def _set(self, on):
        app = self.ctx.focus.set_sticky(on)
        if not app:
            self.ctx.notifier.show('Always on top', 'No window is focused')
        else:
            self.ctx.notifier.show('Always on top', f'{"On" if on else "Off"}: {app_label(app)}')


class DpiControl(Control):
    """Hold + wheel: DPI in fixed steps, shown at once and sent in the background. Tap: calls `on_tap`."""

    def __init__(self, ctx, worker, lo, hi, step, on_tap):
        self.ctx, self.worker = ctx, worker
        self.lo, self.hi, self.step = lo, hi, step
        self.on_tap = on_tap
        self.shown = None

    def press(self):
        self.shown = None
        self.worker.request(refresh=True)  # DPI may have changed elsewhere (e.g. Polychromatic)

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
        self.on_tap()


class MonitorControl(Control):
    """Hold + wheel: brightness of the focused window's monitor. Hold + tilt left / right: warmer / cooler preset.
    Hold + middle click: switch both monitors between night and day with monitor-night-light.

    `presets` maps a monitor serial to its colour presets, warmest first: [(value, name, gains), ...].
    `gains` is None, or (red, green, blue) to set after selecting the preset. Several entries can share
    a preset (User 1) with different gains, to give warmer steps than the monitor's own presets.
    """

    def __init__(self, ctx, worker, step, presets):
        self.ctx, self.worker, self.step, self.presets = ctx, worker, step, presets
        self.monitor = None
        self.located = threading.Event()

    def press(self):
        """Find the focused window's monitor in the background, so the input thread doesn't wait."""
        self.monitor = None
        self.located.clear()
        threading.Thread(target=self._locate, daemon=True).start()

    def _locate(self):
        output = self.ctx.focus.query_output() or self.ctx.focus.output
        self.monitor = self.worker.find(output)
        log.debug('monitor for output %r: %s', output, self.monitor and self.monitor.model)
        if self.monitor:
            self.worker.refresh(self.monitor)
        self.located.set()

    def ready(self):
        self.located.wait(0.5)  # usually done before the first wheel step
        if self.monitor is None:
            self.ctx.notifier.show('Monitor', 'Still looking for monitors')
        return self.monitor

    def wheel(self, up):
        if not (m := self.ready()):
            return
        current = m.values.get(BRIGHTNESS)
        if current is None:
            self.ctx.notifier.show(f'{m.model} brightness', 'Reading the monitor, try again')
            return
        new = min(100, max(0, current + (self.step if up else -self.step)))
        self.ctx.notifier.show(f'{m.model} brightness', f'{bar(new, 0, 100)}  {new}%')
        if new != current:
            self.worker.set(m, BRIGHTNESS, new)

    NIGHT_LIGHT = shutil.which('monitor-night-light') or os.path.expanduser('~/.local/bin/monitor-night-light')
    NIGHT_LIGHT_STATE = os.path.join(os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state'),
                                     'monitor-night-light')

    def toggle_night(self):
        try:
            mode = dict(line.split('=', 1) for line in open(self.NIGHT_LIGHT_STATE).read().split()).get('mode')
        except (OSError, ValueError):
            mode = None
        new = 'day' if mode == 'night' else 'night'
        self.ctx.notifier.show('Monitors', 'Night: Warm 3' if new == 'night' else 'Day: 5000 K (LG 6500 K)')
        subprocess.Popen([self.NIGHT_LIGHT, new], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.debug('monitor-night-light %s', new)
        if self.monitor:
            self.monitor.values.clear()  # re-read on the next press

    def button(self, code):
        if code == MIDDLE:
            self.toggle_night()
            return True
        if code not in (TILT_LEFT, TILT_RIGHT):
            return False
        if not (m := self.ready()):
            return True
        presets = self.presets.get(m.serial)
        title = f'{m.model} colour'
        if not presets:
            self.ctx.notifier.show(title, 'No colour presets for this monitor in config.toml')
            return True
        i = self.current_index(m, presets)
        i = max(0, i - 1) if code == TILT_LEFT else min(len(presets) - 1, i + 1)
        value, name, gains = presets[i]
        self.ctx.notifier.show(title, f'{bar(i, 0, len(presets) - 1)}  {name}')
        if value != m.values.get(COLOUR_PRESET) or gains:
            self.worker.set(m, COLOUR_PRESET, value)
        for feature, gain in zip(GAINS, gains or ()):
            self.worker.set(m, feature, gain)
        return True

    @staticmethod
    def current_index(m, presets):
        """Where the monitor is in the list. Unknown settings count as the middle of the list."""
        current = m.values.get(COLOUR_PRESET)
        gains = tuple(m.values.get(f) for f in GAINS)
        matches = [i for i, (value, _, g) in enumerate(presets) if value == current and (g is None or tuple(g) == gains)]
        return matches[0] if matches else len(presets) // 2
