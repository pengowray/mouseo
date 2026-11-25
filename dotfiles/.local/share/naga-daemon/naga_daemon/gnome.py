"""GNOME: focus tracking and always on top through the naga@mouseo GNOME Shell extension (in the
dotfiles), system volume through the volume keys, and screen zoom through the GNOME magnifier."""
import ast, asyncio, logging, subprocess
from evdev import ecodes as e

log = logging.getLogger(__name__)


class Gnome:
    name = 'gnome'
    overlay_env = {'GDK_BACKEND': 'x11'}   # Mutter has no layer shell; X11 popup windows sit above everything
    ZOOM_STEP = 1.25                   # magnifier factor per wheel step
    ZOOM_MAX = 32.0

    def __init__(self, output):
        self.output = output
        self.focus = GnomeFocus()
        from gi.repository import Gio
        self.a11y = Gio.Settings.new('org.gnome.desktop.a11y.applications')
        self.magnifier = Gio.Settings.new('org.gnome.desktop.a11y.magnifier')

    def change_system_volume(self, up):
        """The volume keys: GNOME's volume step and its volume popup."""
        self.output.tap([e.KEY_VOLUMEUP if up else e.KEY_VOLUMEDOWN])

    def zoom(self, up):
        """The GNOME magnifier: on above 1x, off when zoomed back out to 1x."""
        on = self.a11y.get_boolean('screen-magnifier-enabled')
        factor = self.magnifier.get_double('mag-factor') if on else 1.0
        factor = next_zoom(factor, up, self.ZOOM_STEP, self.ZOOM_MAX)
        if factor > 1.0:
            self.magnifier.set_double('mag-factor', factor)
        if (factor > 1.0) != on:
            self.a11y.set_boolean('screen-magnifier-enabled', factor > 1.0)
        self.magnifier.sync()
        log.debug('zoom %.2f', factor)


def next_zoom(factor, up, step, most):
    """The zoom factor one wheel step on, snapping to 1x near the bottom."""
    factor = factor * step if up else factor / step
    return 1.0 if factor < 1.1 else min(most, round(factor, 2))


def next_zoom(factor, up, step, most):
    """The zoom factor one wheel step on, snapping to 1x near the bottom."""
    factor = factor * step if up else factor / step
    return 1.0 if factor < 1.1 else min(most, round(factor, 2))


BUS_NAME, OBJECT_PATH = 'io.mouseo.Naga', '/io/mouseo/Naga'
MONITOR = ['gdbus', 'monitor', '--session', '--dest', BUS_NAME, '--object-path', OBJECT_PATH]


def gnome_call(method, *args):
    """Call the naga@mouseo GNOME Shell extension. Returns its reply as a tuple, or None."""
    try:
        r = subprocess.run(['gdbus', 'call', '--session', '--dest', BUS_NAME, '--object-path', OBJECT_PATH,
                            '--method', f'{BUS_NAME}.{method}', *args], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            return ast.literal_eval(r.stdout.strip())
        log.debug('GNOME extension %s failed: %s', method, r.stderr.strip())
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as err:
        log.warning('GNOME extension %s failed: %s', method, err)
    return None


def parse_signal(line):
    """(app_id, output, monitor serial) from a `gdbus monitor` FocusChanged line, else None.

    "/io/mouseo/Naga: io.mouseo.Naga.FocusChanged ('firefox', 'DP-1', '304NTJJ4A468')"
    """
    marker = '.FocusChanged '
    if marker not in line:
        return None
    try:
        app_id, output, *serial = ast.literal_eval(line.split(marker, 1)[1].strip())
        return app_id, output, (serial or [''])[0]   # an older extension sends no serial
    except (ValueError, SyntaxError, TypeError):
        return None


class GnomeFocus:
    """Follows the focused window through the naga@mouseo GNOME Shell extension (in the dotfiles)."""

    NOT_RUNNING = "Can't tell which window is focused: the naga@mouseo GNOME extension isn't running"

    def __init__(self):
        self.app_id = ''
        self.output = ''   # connector of the focused window's monitor, e.g. 'DP-1' ('DP-0' under X11)
        self.serial = ''   # serial number of that monitor
        self.missing = ''  # why the focused window is unknown, for the popup; '' if nothing is wrong

    def set(self, app_id='', output='', serial=''):
        self.app_id, self.output, self.serial = app_id, output, serial

    async def run(self):
        warned = False
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(*MONITOR, stdout=subprocess.PIPE,
                                                            stderr=subprocess.DEVNULL)
                async for raw in proc.stdout:
                    line = raw.decode(errors='replace')
                    if (focused := parse_signal(line)) is not None:
                        self.set(*focused)
                    elif 'is owned by' in line:   # the extension started (or was already running)
                        self.missing = ''
                        self.set(*(await asyncio.to_thread(gnome_call, 'Focused') or ()))
                        log.info('focus tracking through the GNOME extension naga@mouseo')
                    elif 'does not have an owner' in line:
                        self.set()
                        self.missing = self.NOT_RUNNING
                        if not warned:
                            log.warning('GNOME extension naga@mouseo is not running: per-app keys use the '
                                        'default profile, and always on top does nothing. GNOME loads new '
                                        'extensions at login.')
                            warned = True
                log.warning('gdbus monitor exited with code %s', await proc.wait())
            except OSError as err:
                log.warning('focus tracking failed: %s', err)
            self.set()
            await asyncio.sleep(3)

    def query_monitor(self):
        """The focused window's monitor as (output, serial number), asked fresh."""
        reply = gnome_call('Focused')
        return (reply[1], reply[2] if len(reply) > 2 else '') if reply else (self.output, self.serial)

    @staticmethod
    def set_on_top(on):
        """Keep the focused window above other windows, or stop. Returns its app_id, or ''."""
        reply = gnome_call('SetAbove', 'true' if on else 'false')
        return reply[0] if reply else ''
