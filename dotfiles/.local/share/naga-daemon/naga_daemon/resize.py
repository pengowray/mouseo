"""Proportional window resizing: thumb 7 + right drag.

The daemon holds Super and the right button down for COSMIC, which starts its own resize, and
bends the pointer movement onto the window's diagonal so the width and height keep their ratio.

Which corner COSMIC resizes from depends on where the window was grabbed. The drag starts
unconstrained; the first window whose edges move (reported by cosmic-window-watch) is the one
being resized, and which edges moved gives the corner. From then on the movement follows the
diagonal, nudged back whenever the live size drifts off the original ratio.
"""
import json, logging, os, shutil, subprocess, threading, time
from evdev import ecodes as e

log = logging.getLogger(__name__)

WATCHER = shutil.which('cosmic-window-watch') or os.path.expanduser('~/.cargo/bin/cosmic-window-watch')
CORRECTION = 0.3     # fraction of the ratio error corrected per movement event
MAX_CORRECTION = 6   # pointer counts


class WindowWatch:
    """Every window's geometry by id, kept current by a long-running cosmic-window-watch."""

    def __init__(self):
        self.windows = {}         # id -> {"app_id", "focused", "x", "y", "width", "height"}

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                proc = subprocess.Popen([WATCHER], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in proc.stdout:
                    try:
                        window = json.loads(line)
                    except ValueError:
                        continue
                    if window.get('closed'):
                        self.windows.pop(window['id'], None)
                    elif 'width' in window:
                        self.windows[window['id']] = window
                log.warning('cosmic-window-watch exited with code %s', proc.wait())
            except OSError as err:
                log.warning('cannot run cosmic-window-watch: %s', err)
            self.windows = {}
            time.sleep(5)


def resized_window(before, now):
    """The id of the first window whose size changed since `before`, or None."""
    for wid, w in now.items():
        old = before.get(wid)
        if old and (w['width'], w['height']) != (old['width'], old['height']):
            return wid
    return None


def corner(before, after):
    """Which corner is being dragged, as (x sign, y sign), from a window before and during a resize.

    The right edge moving means the right side is held (+1); the left edge (x) moving means the
    left side is held (-1). The same goes for bottom (+1) and top (-1). A sign is None until
    that axis has moved.
    """
    def sign(pos, size):
        if after[pos] != before[pos]:
            return -1
        if after[size] != before[size]:
            return 1
        return None
    return sign('x', 'width'), sign('y', 'height')


def project(dx, dy, direction):
    """(dx, dy) projected onto `direction`, as floats."""
    vx, vy = direction
    t = (dx * vx + dy * vy) / (vx * vx + vy * vy)
    return t * vx, t * vy


class ProportionalResize:
    def __init__(self, output, watch):
        self.output, self.watch = output, watch
        self.active = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            self.active = True
            self.before = {k: dict(v) for k, v in self.watch.windows.items()}
            self.target = None        # id of the window being resized, once known
            self.signs = (None, None)
            self.direction = None
            self.remainder = [0.0, 0.0]
        self.output.key(e.KEY_LEFTMETA, 1)
        self.output.button(e.BTN_RIGHT, 1)

    def _learn(self):
        """Find the window and corner from what has moved so far."""
        now = self.watch.windows
        if self.target is None:
            self.target = resized_window(self.before, now)
            if self.target is None:
                return
            log.info('resize: %s', now[self.target].get('app_id'))
        before, current = self.before[self.target], now.get(self.target)
        if not current:
            return
        sx, sy = corner(before, current)
        self.signs = (self.signs[0] or sx, self.signs[1] or sy)
        if None not in self.signs:
            self.direction = (self.signs[0] * before['width'], self.signs[1] * before['height'])
            log.info('resize: corner %s, ratio %d:%d', self.signs, before['width'], before['height'])

    def motion(self, dx, dy):
        with self.lock:
            if not self.active:
                return
            if self.direction is None:
                self._learn()
            if self.direction is None:
                mx, my = dx, dy       # not known yet: move freely
            else:
                fx, fy = project(dx, dy, self.direction)
                fy += self._correction()
                fx, fy = fx + self.remainder[0], fy + self.remainder[1]
                mx, my = round(fx), round(fy)
                self.remainder = [fx - mx, fy - my]
        if mx or my:
            self.output.move(mx, my)

    def _correction(self):
        """Pointer counts to add to the vertical movement to bring the height back to the ratio."""
        w = self.watch.windows.get(self.target)
        if not w:
            return 0
        width0, height0 = self.direction[0] * self.signs[0], self.direction[1] * self.signs[1]
        error = w['height'] - w['width'] * height0 / width0     # pixels too tall
        return max(-MAX_CORRECTION, min(MAX_CORRECTION, -self.signs[1] * error * CORRECTION))

    def stop(self):
        with self.lock:
            if not self.active:
                return
            self.active = False
            if self.target and (w := self.watch.windows.get(self.target)):
                log.info('resize: ended at %dx%d', w['width'], w['height'])
        self.output.button(e.BTN_RIGHT, 0)
        self.output.key(e.KEY_LEFTMETA, 0)
