import argparse, asyncio, logging, os, sys, tomllib
from types import SimpleNamespace
import evdev
from evdev import ecodes as e
from . import keys
from .controls import AppControl, SpeedControl, ZoomControl, DpiControl, MonitorControl, WindowControl, MEDIA_KEYS
from . import desktop as desktops
from .dpi import DpiWorker
from .monitors import MonitorWorker
from .output import Output
from .overlay import Overlay
from .pie import PieControl
from .profiles import Profiles
from .router import Router
from .sleep import SleepWatch
from .stuck import StuckTilts

log = logging.getLogger('naga_daemon')
CONFIG = os.environ.get('NAGA_CONFIG') or os.path.expanduser('~/.config/naga/config.toml')


def build(config, desktop_name, overlay):
    profiles = Profiles(config['profiles'])
    output = Output(profiles.keys() | set(MEDIA_KEYS.values()) | set(ZoomControl.KEYS) | set(desktops.KEYS))
    desktop = desktops.make(output, desktop_name)
    focus = desktop.focus
    ctx = SimpleNamespace(desktop=desktop, focus=focus, profiles=profiles, output=output, popup=overlay)
    step = config['volume_step']
    overlay.env = desktop.overlay_env
    overlay.start()
    controls = {
        keys.PIE: PieControl(ctx, overlay, step),
        keys.WINDOW: WindowControl(ctx),
        keys.FOCUSED_APP: AppControl(ctx, lambda: focus.app_id, step, ('App volume', 'No window is focused')),
        keys.SPOTIFY: AppControl(ctx, lambda: 'spotify', step),
        keys.SPEED: SpeedControl(ctx, fine=False),
        keys.FINE_SPEED: SpeedControl(ctx, fine=True),
        keys.DPI: DpiControl(ctx, DpiWorker(), config['dpi_min'], config['dpi_max'], config['dpi_step'],
                             on_tap=lambda: output.click(e.BTN_MIDDLE)),
        keys.ZOOM: ZoomControl(ctx),
        keys.MONITOR: MonitorControl(ctx, MonitorWorker(), config['brightness_step'], {
            serial: [(p['value'], p['name'], p.get('gains')) for p in m['colour_presets']]
            for serial, m in config.get('monitors', {}).items()}),
    }
    ptt = getattr(e, config['push_to_talk'].upper(), None)
    if ptt is not None and ptt not in e.BTN.keys():
        ptt = None  # a key name such as "key_f18" means: pass F18 through unchanged
    push_to_talk = (lambda value: (output.button(ptt, value), log.debug('push to talk %s', value))) if ptt else None
    return Router(controls, push_to_talk), focus


async def forward(dev, router):
    """Grab one of the mouse's input devices and pass on whatever the router doesn't use."""
    out = evdev.UInput.from_device(dev, name=f'{keys.OUR_PREFIX} {dev.name}')
    dev.grab()
    async for ev in dev.async_read_loop():
        if not router.handle(dev.path, ev):
            out.write_event(ev)


async def main():
    with open(CONFIG, 'rb') as f:
        config = tomllib.load(f)
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    devices = [d for d in devices if keys.is_naga(d.name) and not d.name.startswith(keys.OUR_PREFIX)]
    if not devices:
        sys.exit('Mouse not found')  # systemd restarts us, so this also waits for a Bluetooth reconnect
    desktop_name = desktops.detect()
    overlay = Overlay()
    try:
        router, focus = build(config, desktop_name, overlay)
    except (KeyError, ValueError) as err:
        sys.exit(f'{CONFIG}: {err}')
    readers = [asyncio.create_task(forward(d, router)) for d in devices]
    log.info('grabbed %s', ', '.join(f'{d.path} ({d.phys})' for d in devices))
    log.info('desktop: %s', desktop_name)
    asyncio.create_task(focus.run())

    def on_sleep(sleeping):
        if overlay.stop():
            log.info('%s: stopped the overlay; the next popup or press of thumb 5 starts a new one', 'going to sleep' if sleeping else 'woke up')
    asyncio.create_task(SleepWatch(on_sleep).run())

    def on_stuck(code):
        if code == keys.TILT_RIGHT and router.push_to_talk:
            router.push_to_talk(0)
            title = 'Tilt right stuck: push to talk off'
        else:
            title = f'Wheel tilt {"right" if code == keys.TILT_RIGHT else "left"} stuck'
        log.warning('%s: the mouse has reported %s held for minutes; turning it off and on fixes it',
                    title, keys.key_name(code))
        overlay.show(title, 'Turn the mouse off and on', seconds=10)
    asyncio.create_task(StuckTilts(devices, on_stuck).run())
    done, _ = await asyncio.wait(readers, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        task.result()  # raises if a device disappeared


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', action='store_true', help='log every action')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(message)s', stream=sys.stdout)
    try:
        asyncio.run(main())
    except OSError as err:
        sys.exit(f'device lost: {err}')


if __name__ == '__main__':
    run()
