#!/usr/bin/env python3
"""Linux replacement for the Windows AHK scripts used with the Razer Naga V2 HyperSpeed.

Grabs the mouse's input devices, passes everything through unchanged, except while
one of the carrier keys from layout.py (F13-F16, F21, F22) is held: then the wheel,
middle click and wheel tilts do the things described in config.toml.
"""
import asyncio, json, os, shutil, subprocess, sys, tomllib
import evdev
from evdev import ecodes as e

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.toml')
DEVICE_NAME = 'Naga V2 HyperSpeed'
OUR_PREFIX = 'naga-daemon'
VERBOSE = '-v' in sys.argv

F13, F14, F15, F16, F21, F22 = e.KEY_F13, e.KEY_F14, e.KEY_F15, e.KEY_F16, e.KEY_F21, e.KEY_F22
CARRIERS = {F13, F14, F15, F16, F21, F22}
TILT_LEFT, TILT_RIGHT = e.KEY_LEFTCTRL, e.KEY_F18   # what the onboard layout sends for wheel tilt
ALIASES = {'shift': 'leftshift', 'ctrl': 'leftctrl', 'alt': 'leftalt', 'super': 'leftmeta'}


def parse_combo(text):
    codes = []
    for part in text.lower().split('+'):
        name = 'KEY_' + ALIASES.get(part, part).upper()
        if not hasattr(e, name):
            sys.exit(f'{CONFIG}: unknown key "{part}" in "{text}"')
        codes.append(getattr(e, name))
    return codes


def normalize(name):
    return ''.join(ch for ch in name.lower() if ch.isalnum())


def bar(value, lo, hi, cells=12):
    filled = round(cells * (value - lo) / (hi - lo)) if hi > lo else cells
    filled = min(cells, max(1 if value > lo else 0, filled))
    return '🟩' * filled + '⬜' * (cells - filled)


def log(*args):
    print(*args, flush=True)


class Focus:
    """Follows the focused window's app_id through a long-running `cos-cli serve`."""

    def __init__(self):
        self.app_id = ''

    async def run(self):
        exe = shutil.which('cos-cli') or os.path.expanduser('~/.cargo/bin/cos-cli')
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    exe, 'serve', stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, limit=16 * 1024 * 1024)
                proc.stdin.write(b'{"jsonrpc":"2.0","method":"info","id":1}\n')
                await proc.stdin.drain()
                async for line in proc.stdout:
                    self._update(json.loads(line))
                await proc.wait()
            except (OSError, ValueError) as err:
                log('focus tracking failed:', err)
            self.app_id = ''
            await asyncio.sleep(3)

    def _update(self, msg):
        state = msg.get('result') or (msg.get('params') or {}).get('state') or {}
        for app in state.get('apps', []):
            if 'activated' in app.get('state', []):
                self.app_id = app.get('app_id', '')
                return


class Actions:
    def __init__(self, config, focus):
        self.config = config
        self.focus = focus
        self.profiles = []
        keys = {e.KEY_LEFTCTRL, e.KEY_HOME, e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN,
                e.KEY_PLAYPAUSE, e.KEY_PREVIOUSSONG, e.KEY_NEXTSONG,
                e.KEY_LEFTMETA, e.KEY_EQUAL, e.KEY_MINUS}
        for name, p in config['profiles'].items():
            combos = {k: parse_combo(v) for k, v in p.items() if k != 'apps'}
            keys.update(c for combo in combos.values() for c in combo)
            self.profiles.append((name, [a.lower() for a in p.get('apps', [])], combos))
        self.kbd = evdev.UInput({e.EV_KEY: sorted(keys)}, name=f'{OUR_PREFIX} keys')
        self.notify_id = None
        self.volume_target = None

    def profile(self):
        app = self.focus.app_id.lower()
        for name, apps, combos in self.profiles:
            if any(a in app for a in apps):
                return combos
        return next((c for n, _, c in self.profiles if n == 'default'), {})

    def tap(self, combo):
        if VERBOSE:
            log(f'[{self.focus.app_id or "?"}]', '+'.join(e.KEY[c] if isinstance(e.KEY[c], str) else e.KEY[c][0] for c in combo))
        for c in combo:
            self.kbd.write(e.EV_KEY, c, 1)
        self.kbd.syn()
        for c in reversed(combo):
            self.kbd.write(e.EV_KEY, c, 0)
        self.kbd.syn()

    def media_action(self, action):
        if combo := self.profile().get(action):
            self.tap(combo)

    # Hold + wheel. `steps` is positive for wheel up.
    def wheel(self, carrier, steps):
        up = steps > 0
        for _ in range(abs(steps)):
            step = self.config['volume_step'] * (1 if up else -1)
            if carrier == F13:
                self.app_volume(self.focus.app_id, step)
            elif carrier == F14:
                self.app_volume('spotify', step)
            elif carrier == F15:
                self.media_action('faster' if up else 'slower')
            elif carrier == F16:
                self.media_action('faster_fine' if up else 'slower_fine')
            elif carrier == F22:
                self.tap([e.KEY_LEFTMETA, e.KEY_EQUAL if up else e.KEY_MINUS])  # COSMIC screen zoom
        if carrier == F21:
            self.step_dpi(1 if up else -1)

    # Hold + middle click or wheel tilt. Returns False if nothing is assigned, so the key passes through.
    def button(self, carrier, code):
        if carrier in (F13, F14):
            self.tap([{e.BTN_MIDDLE: e.KEY_PLAYPAUSE, TILT_LEFT: e.KEY_PREVIOUSSONG,
                       TILT_RIGHT: e.KEY_NEXTSONG}[code]])
        elif carrier in (F15, F16):
            self.media_action({e.BTN_MIDDLE: 'play_pause', TILT_LEFT: 'back', TILT_RIGHT: 'forward'}[code])
        else:
            return False
        return True

    def tap_alone(self, carrier):
        if carrier == F21:
            self.tap([e.KEY_LEFTCTRL, e.KEY_HOME])

    def release(self, carrier):
        self.volume_target = None

    def app_volume(self, app_id, percent):
        """Change the volume of every audio stream from the app, and show the new level."""
        if self.volume_target is None:
            self.volume_target = (app_id, self.find_streams(app_id))
        app_id, streams = self.volume_target
        label = app_id.rsplit('.', 1)[-1] or 'App'
        if not streams:
            self.notify(f'{label} volume', 'This app is not playing any sound')
            return
        for stream in streams:
            subprocess.run(['pactl', 'set-sink-input-volume', stream, f'{percent:+d}%'])
        levels = [v for s in self.list_streams() if str(s['index']) in streams
                  for v in [self.stream_percent(s)] if v is not None]
        if levels:
            level = max(levels)
            self.notify(f'{label} volume', f'{bar(level, 0, 100)}  {level}%')

    @staticmethod
    def list_streams():
        out = subprocess.run(['pactl', '-f', 'json', 'list', 'sink-inputs'],
                             capture_output=True, text=True).stdout
        return json.loads(out or '[]')

    @staticmethod
    def stream_percent(stream):
        channels = stream.get('volume', {}).values()
        values = [int(c['value_percent'].rstrip('%')) for c in channels if 'value_percent' in c]
        return max(values) if values else None

    def find_streams(self, app_id):
        want = normalize(app_id)
        found = []
        for stream in self.list_streams():
            props = stream.get('properties', {})
            names = {normalize(props.get(k, '')) for k in (
                'application.name', 'application.process.binary', 'application.id',
                'pipewire.access.portal.app_id', 'application.icon_name')}
            if any(len(n) >= 3 and (n in want or want in n) for n in names):
                found.append(str(stream['index']))
        return found

    def step_dpi(self, direction):
        try:
            from openrazer.client import DeviceManager
            mouse = next(d for d in DeviceManager().devices if DEVICE_NAME in d.name)
        except Exception as err:  # OpenRazer not running, or the mouse is on Bluetooth
            self.notify('DPI', f'Cannot change DPI: {err or "mouse not found in OpenRazer"}')
            return
        lo, hi, step = self.config['dpi_min'], self.config['dpi_max'], self.config['dpi_step']
        current = mouse.dpi[0]
        new = min(hi, max(lo, (current // step + direction) * step))
        if new != current:
            mouse.dpi = (new, new)
        self.notify('DPI', f'{bar(new, lo, hi)}  {new}')
        if VERBOSE:
            log('dpi', current, '->', new)

    def notify(self, title, body):
        cmd = ['notify-send', '--print-id', '-t', '1500', '-a', 'Naga', '-h', 'boolean:transient:true', title, body]
        if self.notify_id:
            cmd[2:2] = ['-r', self.notify_id]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        self.notify_id = out or self.notify_id


class Mouse:
    """One grabbed input device of the mouse, with a passthrough copy."""

    held = None          # carrier key currently held, shared by all of the mouse's devices
    used = False         # whether the held carrier did anything (so a tap means Ctrl+Home)
    swallowed = set()    # keys pressed during a carrier hold, whose release must be dropped too

    def __init__(self, dev, actions):
        self.dev = dev
        self.actions = actions
        self.out = evdev.UInput.from_device(dev, name=f'{OUR_PREFIX} {dev.name}')
        dev.grab()

    async def run(self):
        cls = Mouse
        async for ev in self.dev.async_read_loop():
            if ev.type == e.EV_KEY and ev.code in CARRIERS:
                if ev.value == 1 and cls.held is None:
                    cls.held, cls.used = ev.code, False
                elif ev.value == 0 and cls.held == ev.code:
                    if not cls.used:
                        self.actions.tap_alone(ev.code)
                    self.actions.release(ev.code)
                    cls.held = None
                continue

            if cls.held is not None and ev.type == e.EV_KEY and ev.value == 1:
                cls.used = True  # holding thumb 3 while pressing something else is not a tap

            if cls.held is not None and ev.type == e.EV_REL:
                if ev.code == e.REL_WHEEL:
                    cls.used = True
                    self.actions.wheel(cls.held, ev.value)
                    continue
                if ev.code == e.REL_WHEEL_HI_RES:
                    continue

            if ev.type == e.EV_KEY and ev.code in (e.BTN_MIDDLE, TILT_LEFT, TILT_RIGHT):
                key = (self.dev.path, ev.code)
                if ev.value == 1 and cls.held is not None and self.actions.button(cls.held, ev.code):
                    cls.used = True
                    cls.swallowed.add(key)
                    continue
                if key in cls.swallowed:
                    if ev.value == 0:
                        cls.swallowed.discard(key)
                    continue

            self.out.write_event(ev)


async def main():
    with open(CONFIG, 'rb') as f:
        config = tomllib.load(f)
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    devices = [d for d in devices if DEVICE_NAME in d.name and not d.name.startswith(OUR_PREFIX)]
    if not devices:
        sys.exit('Mouse not found')  # systemd restarts us, so this also waits for a Bluetooth reconnect
    focus = Focus()
    actions = Actions(config, focus)
    mice = [Mouse(d, actions) for d in devices]
    log('grabbed', ', '.join(f'{d.path} ({d.phys})' for d in devices))
    tasks = [asyncio.create_task(m.run()) for m in mice] + [asyncio.create_task(focus.run())]
    done, _ = await asyncio.wait(tasks[:-1], return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        t.result()  # raises if a device disappeared


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except OSError as err:
        sys.exit(f'device lost: {err}')
