"""Starts and talks to overlay_ui.py, which draws the volume pie and the popup."""
import json, logging, os, subprocess, sys, threading, time

log = logging.getLogger(__name__)


class Overlay:
    """Talks to the overlay_ui.py process (the volume pie and the popup), restarting it if it exits.
    `hover` is the pie slot under the pointer."""

    def __init__(self):
        self.env = {}             # extra environment for the overlay process
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
        env = dict(os.environ, PYTHONPATH=package_dir, **self.env)
        try:
            self.proc = subprocess.Popen([sys.executable, '-m', 'naga_daemon.overlay_ui'], env=env, text=True,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as err:
            log.warning('cannot start the overlay: %s', err)
            return False
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        log.info('overlay started (pid %s)', self.proc.pid)
        return True

    def _read(self, proc):
        for line in proc.stdout:
            try:
                self.hover = json.loads(line).get('hover')
            except ValueError:
                pass
        code = proc.wait()
        if proc is self.proc:     # not stopped on purpose by stop()
            log.warning('overlay exited with code %s', code)

    def send(self, msg):
        with self.lock:
            if not self._ensure():
                return
            try:
                self.proc.stdin.write(json.dumps(msg) + '\n')
                self.proc.stdin.flush()
            except OSError as err:
                log.warning('overlay: %s', err)

    def start(self):
        with self.lock:
            self._ensure()

    def stop(self):
        """End the overlay process. The next send() starts a new one. Returns True if one was running."""
        with self.lock:
            proc, self.proc = self.proc, None
            self.started, self.hover = 0.0, None
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False

    def open(self, slots, centre):
        self.send({'op': 'open', 'slots': {str(k): v.as_json() for k, v in slots.items()}, 'centre': centre})

    def level(self, slot, level):
        self.send({'op': 'level', 'slot': slot, 'level': level})

    def close(self):
        self.hover = None
        self.send({'op': 'close'})

    def show(self, title, text, level=None):
        """The popup: a title, a value, and a bar filled to `level` (0 to 1) if given."""
        self.send({'op': 'popup', 'title': title, 'text': text, 'level': level})
