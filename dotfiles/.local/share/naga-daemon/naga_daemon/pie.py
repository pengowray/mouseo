"""Thumb 5: the volume pie. Hold + wheel changes the system volume. Move the mouse while holding
and a pie of apps playing sound appears around the pointer; the wheel, middle click and tilts
then go to the app under the pointer.

Up is always the focused app, down is the background app most likely to be the one you hear,
and the other directions hold the remaining apps with audio. The pie itself is drawn by
pie_ui.py in a separate process.
"""
import json, logging, os, subprocess, sys, threading, time
from dataclasses import dataclass, field
from evdev import ecodes as e
from . import audio, players
from .controls import Control, MEDIA_COMMANDS, MEDIA_KEYS
from .util import app_label, names_match, normalize

log = logging.getLogger(__name__)

UP, DOWN = 0, 4
OTHER_SLOTS = (2, 6, 1, 7, 3, 5)    # right, left, then the diagonals
VOLUME_KEYS = [e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN]


@dataclass
class PieItem:
    app: str                      # name used to find the app's media player
    label: str
    icons: list = field(default_factory=list)
    streams: list = field(default_factory=list)   # pactl sink-input indexes
    level: int | None = None
    note: str = ''

    def as_json(self):
        return {'label': self.label, 'icons': self.icons, 'level': self.level, 'note': self.note}


def _ignored(stream):
    return not stream.names or any('speechdispatcher' in n for n in stream.names)


def _item(app, label, streams, icons=()):
    levels = [s.percent for s in streams if s.percent is not None]
    note = 'No sound' if not streams else 'Paused' if all(s.corked for s in streams) else ''
    names = list(icons) + [i for s in streams for i in s.icons]
    return PieItem(app=app, label=label, icons=list(dict.fromkeys(names)), streams=[s.index for s in streams],
                   level=max(levels) if levels else None, note=note)


def assign_slots(focused_app, streams, playing):
    """Which app goes in which direction: {slot: PieItem}. Slot 0 is up, counting clockwise in eighths."""
    streams = [s for s in streams if not _ignored(s)]
    slots = {}
    if focused_app:
        mine = [s for s in streams if s.belongs_to(focused_app)]
        label = mine[0].app if mine else app_label(focused_app)
        slots[UP] = _item(focused_app, label, mine, icons=[focused_app])
        streams = [s for s in streams if s not in mine]

    groups = {}                   # one entry per app, in the order pactl lists them
    for s in streams:
        groups.setdefault(normalize(s.app) or min(s.names), []).append(s)

    def rank(group):
        if any(names_match(n, p) for s in group for n in s.names for p in playing):
            return 0              # its player says it is playing
        return 2 if all(s.corked for s in group) else 1

    ranked = sorted(groups.values(), key=rank)
    for slot, group in zip((DOWN, *OTHER_SLOTS), ranked):
        slots[slot] = _item(group[0].app, app_label(group[0].app), group)
    return slots


class PieUI:
    """Talks to the pie_ui.py process, restarting it if it exits. `hover` is the slot under the pointer."""

    def __init__(self):
        self.proc = None
        self.hover = None
        self.started = 0.0
        self.lock = threading.Lock()

    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return True
        if time.monotonic() - self.started < 5:
            return False          # it just failed; don't retry on every press
        self.started = time.monotonic()
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, PYTHONPATH=package_dir)
        try:
            self.proc = subprocess.Popen([sys.executable, '-m', 'naga_daemon.pie_ui'], env=env, text=True,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as err:
            log.warning('cannot start the volume pie: %s', err)
            return False
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        log.info('volume pie started (pid %s)', self.proc.pid)
        return True

    def _read(self, proc):
        for line in proc.stdout:
            try:
                self.hover = json.loads(line).get('hover')
            except ValueError:
                pass
        log.warning('volume pie exited with code %s', proc.wait())

    def send(self, msg):
        with self.lock:
            if not self._ensure():
                return
            try:
                self.proc.stdin.write(json.dumps(msg) + '\n')
                self.proc.stdin.flush()
            except OSError as err:
                log.warning('volume pie: %s', err)

    def start(self):
        with self.lock:
            self._ensure()

    def open(self, slots, centre):
        self.send({'op': 'open', 'slots': {str(k): v.as_json() for k, v in slots.items()}, 'centre': centre})

    def level(self, slot, level):
        self.send({'op': 'level', 'slot': slot, 'level': level})

    def close(self):
        self.hover = None
        self.send({'op': 'close'})


class PieControl(Control):
    def __init__(self, ctx, ui, step):
        self.ctx, self.ui, self.step = ctx, ui, step
        self.slots = {}
        self.hold = 0             # counts presses; negative while released
        self.lock = threading.Lock()

    def press(self):
        self.slots = {}
        self.ui.hover = None
        with self.lock:
            self.hold = abs(self.hold) + 1
        threading.Thread(target=self._open, args=(self.hold,), daemon=True).start()

    def _open(self, hold):
        """List the apps in the background, since pactl and playerctl take a moment."""
        slots = assign_slots(self.ctx.focus.app_id, audio.list_streams(), players.playing())
        centre = {'label': 'System', 'level': audio.system_volume()}
        with self.lock:
            if hold != self.hold:
                return            # released already
            self.slots = slots
            self.ui.open(slots, centre)
        log.debug('pie: %s', {k: v.label for k, v in slots.items()})

    def target(self):
        hover = self.ui.hover
        return None if hover is None else self.slots.get(hover)

    def wheel(self, up):
        item = self.target()
        if item is None:
            self.ctx.output.tap([VOLUME_KEYS[0] if up else VOLUME_KEYS[1]])
            threading.Thread(target=self._show_system_level, daemon=True).start()
            return
        if not item.streams:
            return                # the pie already says "No sound"
        audio.change_volume(item.streams, self.step if up else -self.step)
        item.level = audio.volume_of(item.streams)
        self.ui.level(self.ui.hover, item.level)

    def _show_system_level(self):
        time.sleep(0.05)          # let the desktop apply the volume key first
        self.ui.level(None, audio.system_volume())

    def button(self, code):
        item = self.target()
        player = players.find_player(item.app) if item else None
        if player:
            players.control(player, MEDIA_COMMANDS[code])
        else:                     # system, or no media controls: let the desktop pick a player
            self.ctx.output.tap([MEDIA_KEYS[code]])
        return True

    def release(self):
        with self.lock:
            self.hold = -self.hold
            self.ui.close()
