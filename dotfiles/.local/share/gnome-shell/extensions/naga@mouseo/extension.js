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
    <!-- The focused window's app id and the connector of its monitor, e.g. ('firefox', 'DP-1') -->
    <method name="Focused"><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
    <!-- Keep the focused window above others, or stop. Returns its app id, or '' if none is focused. -->
    <method name="SetAbove"><arg type="b" direction="in"/><arg type="s" direction="out"/></method>
    <signal name="FocusChanged"><arg type="s"/><arg type="s"/></signal>
  </interface>
</node>`;

function appId(win) {
    if (!win)
        return '';
    return win.get_wm_class() || win.get_sandboxed_app_id() || win.get_gtk_application_id() ||
        Shell.WindowTracker.get_default().get_window_app(win)?.get_id()?.replace(/\.desktop$/, '') || '';
}

// Connector names (DP-1, HDMI-A-1, ...) by monitor index, from the names in /sys/class/drm.
function connectorsByIndex() {
    const manager = global.backend.get_monitor_manager();
    const result = {};
    try {
        const dir = Gio.File.new_for_path('/sys/class/drm');
        const files = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = files.next_file(null))) {
            const m = info.get_name().match(/^card\d+-(.+)$/);
            if (!m)
                continue;
            const index = manager.get_monitor_for_connector(m[1]);
            if (index >= 0)
                result[index] = m[1];
        }
    } catch (e) {
        console.warn(`naga: cannot list monitor connectors: ${e.message}`);
    }
    return result;
}

export default class NagaExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, PATH);
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, NAME, Gio.BusNameOwnerFlags.NONE, null, null);
        this._connectors = connectorsByIndex();
        this._monitorsId = global.backend.get_monitor_manager().connect('monitors-changed',
            () => { this._connectors = connectorsByIndex(); });
        this._focusId = global.display.connect('notify::focus-window', () => this._emit());
        this._last = null;
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
            return ['', ''];
        return [appId(win), this._connectors[win.get_monitor()] ?? ''];
    }

    _emit() {
        const now = this._focused();
        if (this._last && now[0] === this._last[0] && now[1] === this._last[1])
            return;
        this._last = now;
        this._dbus.emit_signal('FocusChanged', new GLib.Variant('(ss)', now));
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
