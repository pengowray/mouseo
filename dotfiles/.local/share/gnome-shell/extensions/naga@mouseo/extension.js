// Helper for naga-daemon on GNOME:
// - A D-Bus service (io.mouseo.Naga at /io/mouseo/Naga) that says which window is focused, since
//   GNOME has no other way to tell a Wayland client, and keeps a window on top when asked.
// - Screen zoom (the GNOME magnifier) covers only the monitor under the pointer, as on COSMIC,
//   instead of the whole desktop across all monitors.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PointerWatcher from 'resource:///org/gnome/shell/ui/pointerWatcher.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const NAME = 'io.mouseo.Naga';
const PATH = '/io/mouseo/Naga';
const IFACE = `<node>
  <interface name="${NAME}">
    <!-- The focused window's app id, and the connector and serial number of its monitor,
         e.g. ('firefox', 'DP-1', '304NTJJ4A468'). Connector names differ between X11 and Wayland;
         the serial number matches what ddcutil reports. -->
    <method name="Focused">
      <arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/>
    </method>
    <!-- Keep the focused window above others, or stop. Returns its app id, or '' if none is focused. -->
    <method name="SetAbove"><arg type="b" direction="in"/><arg type="s" direction="out"/></method>
    <signal name="FocusChanged"><arg type="s"/><arg type="s"/><arg type="s"/></signal>
  </interface>
</node>`;

function appId(win) {
    if (!win)
        return '';
    return win.get_wm_class() || win.get_sandboxed_app_id() || win.get_gtk_application_id() ||
        Shell.WindowTracker.get_default().get_window_app(win)?.get_id()?.replace(/\.desktop$/, '') || '';
}

// Calls back with {monitor index: [connector, serial]}, from Mutter's own list of monitors.
function readMonitors(callback) {
    const manager = global.backend.get_monitor_manager();
    Gio.DBus.session.call('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
        'org.gnome.Mutter.DisplayConfig', 'GetCurrentState', null, null, Gio.DBusCallFlags.NONE, -1, null,
        (conn, res) => {
            const result = {};
            try {
                const [, monitors] = conn.call_finish(res).deepUnpack();
                for (const [[connector, , , serial]] of monitors) {
                    const index = manager.get_monitor_for_connector(connector);
                    if (index >= 0)
                        result[index] = [connector, serial];
                }
            } catch (e) {
                console.warn(`naga: cannot list monitors: ${e.message}`);
            }
            callback(result);
        });
}

// Like the magnifier's own proportional mouse tracking, but relative to the zoomed monitor rather
// than the whole desktop, so the zoomed view stays on that monitor's contents.
function centerOnMonitor(xPoint, yPoint) {
    const [, , widthRoi, heightRoi] = this.getROI();
    const x0 = this._viewPortX, y0 = this._viewPortY;
    const halfWidth = this._viewPortWidth / 2, halfHeight = this._viewPortHeight / 2;
    const x = Math.min(Math.max(xPoint, x0), x0 + 2 * halfWidth);
    const y = Math.min(Math.max(yPoint, y0), y0 + 2 * halfHeight);
    const padding = Math.min(this._viewPortWidth, this._viewPortHeight) / 5;
    const xProportion = (x - x0 - halfWidth) / halfWidth;     // -1 ... 1
    const yProportion = (y - y0 - halfHeight) / halfHeight;
    return [x - xProportion * (widthRoi / 2 - padding / this._xMagFactor),
        y - yProportion * (heightRoi / 2 - padding / this._yMagFactor)];
}

// Keeps the magnifier's zoomed view on the monitor under the pointer while zoom is on.
class OneMonitorZoom {
    constructor() {
        this._watch = null;
        this._region = Main.magnifier?.getZoomRegions()[0] ?? null;
        if (!this._region)
            return;
        this._region._centerFromPointProportional = centerOnMonitor;
        Main.magnifier.connectObject('active-changed', (_, active) => this._sync(active), this);
        this._sync(Main.magnifier.isActive());
    }

    _sync(active) {
        if (active && !this._watch) {
            this._watch = PointerWatcher.getPointerWatcher().addWatch(50, (x, y) => this._follow(x, y));
            const [x, y] = global.get_pointer();
            this._follow(x, y);
        } else if (!active && this._watch) {
            this._watch.remove();
            this._watch = null;
        }
    }

    _follow(x, y) {
        const m = Main.layoutManager.findMonitorForPoint(x, y);
        const r = this._region;
        if (m && (r._viewPortX !== m.x || r._viewPortY !== m.y ||
                  r._viewPortWidth !== m.width || r._viewPortHeight !== m.height))
            r.setViewPort({x: m.x, y: m.y, width: m.width, height: m.height});
    }

    destroy() {
        if (!this._region)
            return;
        this._sync(false);
        Main.magnifier.disconnectObject(this);
        delete this._region._centerFromPointProportional;   // back to the prototype's
        const full = {x: 0, y: 0, width: global.screen_width, height: global.screen_height};
        this._region.setViewPort(full);
        this._region = null;
    }
}

export default class NagaExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, PATH);
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, NAME, Gio.BusNameOwnerFlags.NONE, null, null);
        this._monitors = {};
        this._last = null;
        const refresh = () => readMonitors(monitors => {
            this._monitors = monitors;
            this._emit();
        });
        refresh();
        this._monitorsId = global.backend.get_monitor_manager().connect('monitors-changed', refresh);
        this._focusId = global.display.connect('notify::focus-window', () => this._emit());
        this._zoom = new OneMonitorZoom();
    }

    disable() {
        this._zoom.destroy();
        this._zoom = null;
        global.display.disconnect(this._focusId);
        global.backend.get_monitor_manager().disconnect(this._monitorsId);
        Gio.bus_unown_name(this._nameId);
        this._dbus.unexport();
        this._dbus = null;
    }

    _focused() {
        const win = global.display.focus_window;
        if (!win)
            return ['', '', ''];
        const [connector, serial] = this._monitors[win.get_monitor()] ?? ['', ''];
        return [appId(win), connector, serial];
    }

    _emit() {
        if (!this._dbus)
            return;   // disabled while Mutter was answering
        const now = this._focused();
        if (this._last && now.every((value, i) => value === this._last[i]))
            return;
        this._last = now;
        this._dbus.emit_signal('FocusChanged', new GLib.Variant('(sss)', now));
    }

    Focused() {
        return this._focused();
    }

    SetAbove(on) {
        const win = global.display.focus_window;
        if (!win)
            return '';
        if (on)
            win.make_above();
        else
            win.unmake_above();
        return appId(win);
    }
}
