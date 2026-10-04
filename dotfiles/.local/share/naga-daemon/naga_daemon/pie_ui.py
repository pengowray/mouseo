"""The volume pie: a transparent overlay drawn around the pointer while thumb 5 is held.

Runs as its own process (GTK wants the main thread), started by pie.PieUI. Reads JSON lines
on stdin and writes the hovered slot to stdout:
  in:  {"op": "open", "slots": {"0": {"label", "icons", "level", "note", "streams"}, ...}, "centre": {...}}
       {"op": "level", "slot": 0 | null, "level": 40}
       {"op": "close"}
  out: {"hover": 0 | null}      null means the centre (system volume)

Slots are the eight directions, clockwise from up: 0 up, 2 right, 4 down, 6 left.
The overlay covers each monitor so it can see the pointer. The pie appears once the pointer has
moved SHOW_PX from where it was first seen, centred on that point. Behind each app's wedge, a faint
fill grows outward with how loud that app is right now.
"""
import json, math, sys, threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GLib, Gio, GtkLayerShell
import cairo
from .levels import Meters

SHOW_PX = 25        # pointer movement that brings up the pie
DEAD_PX = 45        # within this distance of the centre, the centre (system volume) is hovered
OUTER = 165         # pie radius
ICON = 32

BG = (0.12, 0.12, 0.13, 0.88)
WEDGE = (0.20, 0.20, 0.22, 0.92)
HOVER = (0.27, 0.55, 0.78, 0.95)
TEXT = (1, 1, 1, 1)
DIM = (1, 1, 1, 0.55)
BAR = (0.40, 0.80, 0.45, 1)
METER = (1, 1, 1, 0.13)
METER_FALL = 0.06    # how far a meter drops per frame
FRAME_MS = 33


def slot_at(dx, dy):
    """Which slot a pointer offset from the centre points at, or None for the centre."""
    if math.hypot(dx, dy) < DEAD_PX:
        return None
    angle = math.degrees(math.atan2(dx, -dy)) % 360   # 0 = up, clockwise
    return int((angle + 22.5) // 45) % 8


class Pie:
    def __init__(self):
        self.windows = []
        self.slots, self.centre = {}, None
        self.origin = None        # (window, x, y) where the pointer was first seen
        self.pointer = None
        self.shown = False
        self.hover = None
        self.icons = {}
        self.meters = Meters()
        self.shown_levels = {}    # slot -> meter level being drawn, 0..1
        self.ticker = None
        Gdk.Screen.get_default().connect('monitors-changed', lambda *_: self.rebuild())
        self.rebuild()

    def rebuild(self):
        for w in self.windows:
            w.destroy()
        display = Gdk.Display.get_default()
        self.windows = [self.make_window(display.get_monitor(i)) for i in range(display.get_n_monitors())]

    def make_window(self, monitor):
        w = Gtk.Window()
        w.set_app_paintable(True)
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(w, monitor)
        GtkLayerShell.set_namespace(w, 'naga-pie')
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(w, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(w, edge, True)
        w.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
        w.connect('draw', self.draw)
        w.connect('motion-notify-event', self.moved)
        w.connect('enter-notify-event', self.moved)
        return w

    # --- commands from the daemon

    def command(self, msg):
        op = msg.get('op')
        if op == 'open':
            self.slots = {int(k): v for k, v in msg.get('slots', {}).items()}
            self.centre = msg.get('centre')
            if not any(w.get_visible() for w in self.windows):
                self.origin, self.pointer, self.shown, self.hover = None, None, False, None
                for w in self.windows:
                    w.show_all()
            self.meters.start(i for item in self.slots.values() for i in item.get('streams', []))
            self.shown_levels = {}
            if self.ticker is None:
                self.ticker = GLib.timeout_add(FRAME_MS, self.tick)
            self.redraw()
        elif op == 'level':
            item = self.centre if msg.get('slot') is None else self.slots.get(msg['slot'])
            if item is not None:
                item['level'] = msg.get('level')
                self.redraw()
        elif op == 'close':
            for w in self.windows:
                w.hide()
            self.slots, self.centre = {}, None
            self.stop_meters()
        return False

    def tick(self):
        """Meters jump up at once and fall back slowly."""
        for slot, item in self.slots.items():
            now = self.meters.level(item.get('streams', []))
            self.shown_levels[slot] = max(now, self.shown_levels.get(slot, 0) - METER_FALL)
        if self.shown:
            self.redraw()
        return True

    def stop_meters(self):
        self.meters.stop()
        self.shown_levels = {}
        if self.ticker is not None:
            GLib.source_remove(self.ticker)
            self.ticker = None

    # --- pointer

    def moved(self, w, ev):
        if self.origin is None or self.origin[0] is not w:
            self.origin, self.shown = (w, ev.x, ev.y), False
        self.pointer = (ev.x, ev.y)
        dx, dy = ev.x - self.origin[1], ev.y - self.origin[2]
        if not self.shown and math.hypot(dx, dy) >= SHOW_PX:
            self.shown = True
        hover = slot_at(dx, dy) if self.shown else None
        if hover is not None and hover not in self.slots:
            hover = None      # an empty direction counts as the centre
        if hover != self.hover:
            self.hover = hover
            print(json.dumps({'hover': hover}), flush=True)
        self.redraw()

    def redraw(self):
        for w in self.windows:
            w.queue_draw()

    # --- drawing

    def draw(self, w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if not self.shown or self.origin is None or self.origin[0] is not w:
            return
        _, cx, cy = self.origin
        cr.set_source_rgba(*BG)
        cr.arc(cx, cy, OUTER + 6, 0, 2 * math.pi)
        cr.fill()
        for slot in range(8):
            self.draw_wedge(cr, cx, cy, slot, self.slots.get(slot))
        self.draw_centre(cr, cx, cy)
        if self.pointer:
            cr.set_source_rgba(*TEXT)
            cr.arc(*self.pointer, 3, 0, 2 * math.pi)
            cr.fill()

    def draw_wedge(self, cr, cx, cy, slot, item):
        mid = math.radians(slot * 45 - 90)
        a0, a1 = mid - math.radians(21), mid + math.radians(21)
        cr.new_path()
        cr.arc(cx, cy, OUTER, a0, a1)
        cr.arc_negative(cx, cy, DEAD_PX + 4, a1, a0)
        cr.close_path()
        if item is None:
            cr.set_source_rgba(*WEDGE[:3], 0.35)
            cr.fill()
            return
        cr.set_source_rgba(*(HOVER if slot == self.hover else WEDGE))
        cr.fill()
        level = self.shown_levels.get(slot, 0)
        if level > 0.01:
            inner = DEAD_PX + 4
            cr.arc(cx, cy, inner + (OUTER - inner) * level, a0, a1)
            cr.arc_negative(cx, cy, inner, a1, a0)
            cr.close_path()
            cr.set_source_rgba(*METER)
            cr.fill()
        r = (OUTER + DEAD_PX) / 2 + 6
        x, y = cx + r * math.cos(mid), cy + r * math.sin(mid)
        self.draw_item(cr, x, y, item, icon=True)

    def draw_centre(self, cr, cx, cy):
        cr.set_source_rgba(*(HOVER if self.hover is None else WEDGE))
        cr.arc(cx, cy, DEAD_PX, 0, 2 * math.pi)
        cr.fill()
        if self.centre:
            self.draw_item(cr, cx, cy - 4, self.centre, icon=False)

    def draw_item(self, cr, x, y, item, icon):
        top = y - (ICON / 2 + 8 if icon else 6)
        if icon and (pix := self.icon(item.get('icons') or [])):
            Gdk.cairo_set_source_pixbuf(cr, pix, x - pix.get_width() / 2, top - pix.get_height() / 2)
            cr.paint()
            top += ICON / 2 + 12
        self.text(cr, x, top, item.get('label', ''), 12, TEXT, bold=True)
        level = item.get('level')
        if item.get('note'):
            self.text(cr, x, top + 15, item['note'], 10, DIM)
        elif level is not None:
            self.text(cr, x, top + 15, f'{level}%', 10, DIM)
        if level is not None:
            width = 48
            cr.set_source_rgba(1, 1, 1, 0.2)
            cr.rectangle(x - width / 2, top + 24, width, 3)
            cr.fill()
            cr.set_source_rgba(*BAR)
            cr.rectangle(x - width / 2, top + 24, width * min(level, 100) / 100, 3)
            cr.fill()

    @staticmethod
    def text(cr, x, y, s, size, colour, bold=False):
        if len(s) > 14:
            s = s[:13] + '…'
        cr.select_font_face('Sans', cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(size)
        ext = cr.text_extents(s)
        cr.set_source_rgba(*colour)
        cr.move_to(x - ext.width / 2 - ext.x_bearing, y + size / 2)
        cr.show_text(s)

    def icon(self, names):
        key = tuple(names)
        if key not in self.icons:
            self.icons[key] = self.load_icon(names)
        return self.icons[key]

    @staticmethod
    def load_icon(names):
        theme = Gtk.IconTheme.get_default()
        for name in names:
            if not name:
                continue
            candidates = [name, name.lower()]
            try:
                info = Gio.DesktopAppInfo.new(name + '.desktop')
            except TypeError:
                info = None
            info = info or app_by_name().get(normalize(name))
            if info and info.get_icon():
                icon = info.get_icon()
                candidates = (icon.get_names() if isinstance(icon, Gio.ThemedIcon) else [icon.to_string()]) + candidates
            for c in candidates:
                try:
                    if c.startswith('/'):
                        from gi.repository import GdkPixbuf
                        return GdkPixbuf.Pixbuf.new_from_file_at_size(c, ICON, ICON)
                    if theme.has_icon(c):
                        return theme.load_icon(c, ICON, Gtk.IconLookupFlags.FORCE_SIZE)
                except GLib.Error:
                    continue
        return None


def normalize(name):
    return ''.join(ch for ch in name.lower() if ch.isalnum())


_apps = None

def app_by_name():
    """Installed apps by normalized name and by the last part of their id, so 'Spotify' finds
    the Flatpak 'com.spotify.Client'."""
    global _apps
    if _apps is None:
        _apps = {}
        for info in Gio.AppInfo.get_all():
            app_id = (info.get_id() or '').removesuffix('.desktop')
            for key in (info.get_name() or '', app_id, *app_id.split('.')):
                if len(normalize(key)) >= 3:
                    _apps.setdefault(normalize(key), info)
    return _apps


def read_stdin(pie):
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        GLib.idle_add(pie.command, msg)
    GLib.idle_add(pie.stop_meters)
    GLib.idle_add(Gtk.main_quit)   # the daemon went away


def main():
    if not GtkLayerShell.is_supported():
        sys.exit('naga pie: the compositor does not support layer shell')
    pie = Pie()
    threading.Thread(target=read_stdin, args=(pie,), daemon=True).start()
    Gtk.main()


if __name__ == '__main__':
    main()
