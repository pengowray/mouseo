"""What differs between COSMIC and GNOME: focus tracking, the system volume, screen zoom, and
how the overlay (volume pie and popup) gets windows above the others. Picked once at startup."""
import logging, os, subprocess
from evdev import ecodes as e
from .focus import CosmicFocus, GnomeFocus

log = logging.getLogger(__name__)

# Keys a desktop may send through the virtual keyboard
KEYS = [e.KEY_LEFTMETA, e.KEY_EQUAL, e.KEY_MINUS, e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN]


def detect(env=os.environ):
    """'gnome' or 'cosmic', from XDG_CURRENT_DESKTOP (such as 'COSMIC' or 'pop:GNOME')."""
    names = env.get('XDG_CURRENT_DESKTOP', '').lower().split(':')
    return 'gnome' if 'gnome' in names and 'cosmic' not in names else 'cosmic'


class Cosmic:
    name = 'cosmic'
    overlay_env = {}   # the overlay uses layer shell

    def __init__(self, output):
        self.output = output
        self.focus = CosmicFocus()

    def change_system_volume(self, up):
        """Step the default output's volume by COSMIC's volume step, showing COSMIC's volume popup.
        This is the call COSMIC makes for the volume keys; tapping the keys instead adds ~300 ms."""
        subprocess.run(['busctl', '--user', 'call', 'com.system76.CosmicSettingsDaemon',
                        '/com/system76/CosmicSettingsDaemon', 'com.system76.CosmicSettingsDaemon',
                        'VolumeUp' if up else 'VolumeDown'], capture_output=True)

    def zoom(self, up):
        self.output.tap([e.KEY_LEFTMETA, e.KEY_EQUAL if up else e.KEY_MINUS])


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


def make(output, name=None):
    return (Gnome if (name or detect()) == 'gnome' else Cosmic)(output)
