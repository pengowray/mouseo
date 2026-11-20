"""Monitor brightness and colour presets over DDC/CI, through ddcutil, and a laptop panel's backlight.

A laptop's built-in panel has no DDC/CI (ddcutil lists it as an "Invalid display"), so its
brightness goes through the kernel backlight instead: read from /sys/class/backlight and
set through logind, which lets the logged-in user change it without root.

ddcutil takes about half a second per change, so a worker thread sends only the latest
value for each monitor setting, and the input thread never waits.
"""
import glob, logging, os, re, subprocess, threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
BRIGHTNESS, COLOUR_PRESET = 0x10, 0x14
GAINS = (0x16, 0x18, 0x1a)   # red, green, blue video gain (used by the User presets)
READ = (BRIGHTNESS, COLOUR_PRESET, *GAINS)


@dataclass
class Monitor:
    connector: str          # 'DP-1', as COSMIC names the output
    bus: int                # /dev/i2c-N
    model: str              # 'LG ULTRAGEAR'
    serial: str
    values: dict = field(default_factory=dict)   # VCP feature -> last known value
    backlight: str = None   # 'intel_backlight' for a laptop panel, whose brightness isn't set over DDC/CI


def backlights():
    """The kernel backlight devices, firmware ones first, as the kernel docs suggest."""
    order = {'firmware': 0, 'platform': 1, 'raw': 2}
    devices = []
    for path in glob.glob('/sys/class/backlight/*'):
        try:
            kind = open(os.path.join(path, 'type')).read().strip()
        except OSError:
            kind = 'raw'
        devices.append((order.get(kind, 3), os.path.basename(path)))
    return [name for _, name in sorted(devices)]


def read_backlight(name):
    """The backlight's brightness in percent, or None."""
    try:
        path = f'/sys/class/backlight/{name}'
        return round(int(open(f'{path}/brightness').read()) * 100 / int(open(f'{path}/max_brightness').read()))
    except (OSError, ValueError, ZeroDivisionError):
        return None


def set_backlight(name, percent):
    try:
        top = int(open(f'/sys/class/backlight/{name}/max_brightness').read())
    except (OSError, ValueError):
        return
    raw = max(1, round(percent * top / 100))  # 0 turns some panels off completely
    r = subprocess.run(['busctl', 'call', '--system', 'org.freedesktop.login1', '/org/freedesktop/login1/session/auto',
                        'org.freedesktop.login1.Session', 'SetBrightness', 'ssu', 'backlight', name, str(raw)],
                       capture_output=True, text=True)
    if r.returncode:
        log.warning('setting backlight %s failed: %s', name, r.stderr.strip())


def detect():
    out = subprocess.run(['ddcutil', 'detect', '--brief'], capture_output=True, text=True).stdout
    monitors = []
    panels = []
    for block in out.split('\n\n'):
        if block.lstrip().startswith('Invalid display'):
            if conn := re.search(r'DRM connector:\s*card\d+-(eDP\S*|LVDS\S*|DSI\S*)', block):
                panels.append(conn.group(1))  # a laptop panel: use its backlight
            continue
        bus = re.search(r'/dev/i2c-(\d+)', block)
        conn = re.search(r'DRM connector:\s*card\d+-(\S+)', block)
        mon = re.search(r'Monitor:\s*[^:]*:(.*):(\S*)\s*$', block, re.M)
        if bus and conn and mon:
            monitors.append(Monitor(conn.group(1), int(bus.group(1)), mon.group(1).strip(), mon.group(2)))
    for connector, name in zip(panels, backlights()):
        monitors.append(Monitor(connector, None, 'Laptop screen', '', backlight=name))
    return monitors


def parse_getvcp(text):
    """'VCP 10 C 70 100' -> {0x10: 70}; 'VCP 14 SNC x05' or 'VCP 14 CNC x00 x0b x00 x06' -> {0x14: 6}."""
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == 'VCP':
            feature = int(parts[1], 16)
            if parts[2] == 'C':
                values[feature] = int(parts[3])
            elif parts[-1].startswith('x'):
                values[feature] = int(parts[-1][1:], 16)
    return values


class MonitorWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.monitors = None      # detected on first use
        self.pending = {}         # (monitor, feature) -> value to send
        self.to_read = set()      # monitors whose values to re-read
        self.ready = threading.Event()
        self.start()

    def find(self, connector):
        """The monitor on a COSMIC output name, or the first monitor. None until detection finishes."""
        if not self.ready.is_set():
            return None
        return next((m for m in self.monitors if m.connector == connector), self.monitors[0] if self.monitors else None)

    def refresh(self, monitor=None):
        with self.lock:
            if monitor:
                self.to_read.add(monitor.connector)
        self.wake.set()

    def set(self, monitor, feature, value):
        monitor.values[feature] = value
        with self.lock:
            self.pending[monitor.connector, feature] = value
        self.wake.set()

    def run(self):
        self.monitors = detect()
        log.info('monitors: %s', ', '.join(f'{m.connector} {m.model}' for m in self.monitors) or 'none')
        self.ready.set()
        while True:
            self.wake.wait()
            self.wake.clear()
            with self.lock:
                pending, self.pending = self.pending, {}
                to_read, self.to_read = self.to_read, set()
            for (connector, feature), value in pending.items():
                monitor = self._by_connector(connector)
                if monitor.backlight:
                    if feature == BRIGHTNESS:
                        set_backlight(monitor.backlight, value)
                else:
                    self._ddcutil(monitor.bus, 'setvcp', f'{feature:x}', str(value), '--noverify')
            for connector in to_read:
                monitor = self._by_connector(connector)
                if monitor.backlight:
                    if (connector, BRIGHTNESS) not in self.pending and (level := read_backlight(monitor.backlight)) is not None:
                        monitor.values[BRIGHTNESS] = level
                    continue
                bus = monitor.bus
                values = parse_getvcp(self._ddcutil(bus, 'getvcp', *(f'{f:x}' for f in READ), '--brief'))
                for missing in set(READ) - set(values):  # reads fail now and then; retry once
                    values.update(parse_getvcp(self._ddcutil(bus, 'getvcp', f'{missing:x}', '--brief')))
                for feature, value in values.items():
                    if (connector, feature) not in self.pending:  # don't undo a change made while reading
                        monitor.values[feature] = value

    def _by_connector(self, connector):
        return next(m for m in self.monitors if m.connector == connector)

    @staticmethod
    def _ddcutil(bus, *args):
        r = subprocess.run(['ddcutil', '--bus', str(bus), *args], capture_output=True, text=True)
        if r.returncode:
            log.warning('ddcutil --bus %s %s failed: %s', bus, ' '.join(args), r.stderr.strip() or r.stdout.strip())
        return r.stdout
