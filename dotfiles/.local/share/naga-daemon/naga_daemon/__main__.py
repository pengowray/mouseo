import argparse, asyncio, logging, os, sys, tomllib
from types import SimpleNamespace
import evdev
from evdev import ecodes as e
from . import audio, players, keys
from .controls import AppControl, SpeedControl, ZoomControl, DpiControl, MEDIA_KEYS
from .dpi import DpiWorker
from .focus import Focus
from .notify import Notifier
from .output import Output
from .profiles import Profiles
from .router import Router

log = logging.getLogger('naga_daemon')
CONFIG = os.environ.get('NAGA_CONFIG') or os.path.expanduser('~/.config/naga/config.toml')


def build(config, focus):
    profiles = Profiles(config['profiles'])
    output = Output(profiles.keys() | set(MEDIA_KEYS.values()) | set(ZoomControl.KEYS))
    ctx = SimpleNamespace(focus=focus, profiles=profiles, output=output, notifier=Notifier())
    step = config['volume_step']
    controls = {
        keys.FOCUSED_APP: AppControl(ctx, lambda: focus.app_id, step, ('App volume', 'No window is focused')),
        keys.SPOTIFY: AppControl(ctx, lambda: 'spotify', step),
        keys.BACKGROUND_APP: AppControl(
            ctx, lambda: audio.background_app(focus.app_id, players.playing()), step,
            ('Background app volume', 'No other app is playing sound')),
        keys.SPEED: SpeedControl(ctx, fine=False),
        keys.FINE_SPEED: SpeedControl(ctx, fine=True),
        keys.DPI: DpiControl(ctx, DpiWorker(), config['dpi_min'], config['dpi_max'], config['dpi_step'],
                             on_tap=lambda: output.click(e.BTN_MIDDLE)),
        keys.ZOOM: ZoomControl(ctx),
    }
    ptt = getattr(e, config['push_to_talk'].upper(), None)
    if ptt is not None and ptt not in e.BTN.keys():
        ptt = None  # a key name such as "key_f18" means: pass F18 through unchanged
    push_to_talk = (lambda value: (output.button(ptt, value), log.debug('push to talk %s', value))) if ptt else None
    return Router(controls, push_to_talk)


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
    devices = [d for d in devices if keys.DEVICE_NAME in d.name and not d.name.startswith(keys.OUR_PREFIX)]
    if not devices:
        sys.exit('Mouse not found')  # systemd restarts us, so this also waits for a Bluetooth reconnect
    focus = Focus()
    try:
        router = build(config, focus)
    except (KeyError, ValueError) as err:
        sys.exit(f'{CONFIG}: {err}')
    readers = [asyncio.create_task(forward(d, router)) for d in devices]
    log.info('grabbed %s', ', '.join(f'{d.path} ({d.phys})' for d in devices))
    asyncio.create_task(focus.run())
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
