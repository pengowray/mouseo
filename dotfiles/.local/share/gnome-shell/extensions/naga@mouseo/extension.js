// D-Bus service for naga-daemon on GNOME, which has no other way to tell a Wayland client
// which window is focused. Bus name and object: io.mouseo.Naga at /io/mouseo/Naga.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
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
    }

    disable() {
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
