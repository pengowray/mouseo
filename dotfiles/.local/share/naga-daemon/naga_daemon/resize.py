"""Proportional window resizing: thumb 7 + right drag.

The daemon holds Super and the right button down for COSMIC, which starts its own resize, and
bends the pointer movement onto the window's diagonal so the width and height keep their ratio.

Which corner COSMIC is resizing from depends on where the window was grabbed, so a resize
starts with a small probe: move the pointer a few counts right and down, see which edges of
the focused window moved (from cosmic-window-watch), and move back.
"""
import json, logging, os, shutil, subprocess, threading, time
from evdev import ecodes as e

log = logging.getLogger(__name__)

WATCHER = shutil.which('cosmic-window-watch') or os.path.expanduser('~/.cargo/bin/cosmic-window-watch')
PROBE = 3            # pointer counts moved for the probe
PROBE_WAIT = 0.25    # seconds to wait for the window to answer the probe


class WindowWatch:
    """The focused window's geometry, kept current by a long-running cosmic-window-watch."""

    def __init__(self):
        self.window = {}          # {"app_id", "x", "y", "width", "height"}, or {} when unknown
        self.changed = threading.Condition()

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
                    with self.changed:
                        self.window = window
                        self.changed.notify_all()
                log.warning('cosmic-window-watch exited with code %s', proc.wait())
            except OSError as err:
                log.warning('cannot run cosmic-window-watch: %s', err)
            self.window = {}
            time.sleep(5)

    def wait_change(self, old, timeout):
        """The window once it differs from `old`, or None after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        with self.changed:
            while self.window == old:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.changed.wait(left)
            return self.window


def corner(before, after):
    """Which corner a probe moving right and down resized from, as (x sign, y sign).

    Growing on the right means the right edge is held (+1); the left edge moving right means the
    left edge is held (-1). The same goes for bottom (+1) and top (-1). None if nothing moved.
    """
    def sign(pos, size):
        if after[pos] != before[pos]:
            return -1
        if after[size] != before[size]:
            return 1
        return None
    sx, sy = sign('x', 'width'), sign('y', 'height')
    return None if sx is None or sy is None else (sx, sy)


def project(dx, dy, direction):
    """(dx, dy) projected onto `direction`, as floats."""
    vx, vy = direction
    t = (dx * vx + dy * vy) / (vx * vx + vy * vy)
    return t * vx, t * vy


class ProportionalResize:
    def __init__(self, output, watch):
        self.output, self.watch = output, watch
        self.active = False
        self.direction = None     # the diagonal to move along; None while probing or if the probe failed
        self.probing = False
        self.buffered = [0, 0]
        self.remainder = [0.0, 0.0]
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            self.active, self.probing, self.direction = True, True, None
            self.buffered, self.remainder = [0, 0], [0.0, 0.0]
        self.output.key(e.KEY_LEFTMETA, 1)
        self.output.button(e.BTN_RIGHT, 1)
        threading.Thread(target=self._probe, daemon=True).start()

    def _probe(self):
        time.sleep(0.03)          # let COSMIC focus the window and start the resize
        before = dict(self.watch.window)
        self.output.move(PROBE, PROBE)
        after = self.watch.wait_change(before, PROBE_WAIT)
        self.output.move(-PROBE, -PROBE)
        found = corner(before, after) if before.get('width') and after and after.get('width') else None
        with self.lock:
            if not self.active:
                return
            if found:
                self.direction = (found[0] * before['width'], found[1] * before['height'])
            self.probing = False
            log.debug('resize: %s %s -> corner %s', before, after, found)
            buffered, self.buffered = self.buffered, [0, 0]
        if any(buffered):
            self.motion(*buffered)

    def motion(self, dx, dy):
        with self.lock:
            if self.probing:
                self.buffered[0] += dx
                self.buffered[1] += dy
                return
            if self.direction is None:      # the probe failed: resize freely
                mx, my = dx, dy
            else:
                fx, fy = project(dx, dy, self.direction)
                fx, fy = fx + self.remainder[0], fy + self.remainder[1]
                mx, my = round(fx), round(fy)
                self.remainder = [fx - mx, fy - my]
        if mx or my:
            self.output.move(mx, my)

    def stop(self):
        with self.lock:
            if not self.active:
                return
            self.active = False
        self.output.button(e.BTN_RIGHT, 0)
        self.output.key(e.KEY_LEFTMETA, 0)
