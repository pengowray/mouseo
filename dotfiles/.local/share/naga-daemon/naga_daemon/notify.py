import logging
import dbus

log = logging.getLogger(__name__)


class Notifier:
    """Desktop notifications over D-Bus. Each one replaces the previous, so fast wheel steps update one bubble."""

    def __init__(self, app_name='Naga', timeout_ms=1500):
        self.app_name = app_name
        self.timeout_ms = timeout_ms
        self.last_id = 0
        self.iface = None

    def show(self, title, body):
        try:
            if self.iface is None:
                bus = dbus.SessionBus(private=True)  # private: OpenRazer uses the shared one from another thread
                self.iface = dbus.Interface(
                    bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications'),
                    'org.freedesktop.Notifications')
            self.last_id = int(self.iface.Notify(
                self.app_name, dbus.UInt32(self.last_id), '', title, body, [],
                {'transient': dbus.Boolean(True)}, self.timeout_ms))
        except dbus.DBusException as err:
            self.iface = None
            log.warning('notification failed: %s', err)
