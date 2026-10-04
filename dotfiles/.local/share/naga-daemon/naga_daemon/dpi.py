import logging, threading
from .keys import DEVICE_NAME

log = logging.getLogger(__name__)


class DpiWorker(threading.Thread):
    """Talks to OpenRazer off the input thread, so DPI notifications show without waiting.

    Only the latest requested DPI is sent; steps that pile up while a write is in progress are skipped.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.wanted = None        # DPI to send to the mouse
        self.refresh = False      # re-read the DPI from the mouse
        self.current = None       # last DPI known to be on the mouse
        self.error = None
        self.start()

    def request(self, dpi=None, refresh=False):
        with self.lock:
            if dpi is not None:
                self.wanted = dpi
            self.refresh |= refresh
        self.wake.set()

    def run(self):
        mouse = None
        while True:
            self.wake.wait()
            self.wake.clear()
            with self.lock:
                wanted, refresh = self.wanted, self.refresh
                self.wanted, self.refresh = None, False
            try:
                if mouse is None:
                    from openrazer.client import DeviceManager
                    mouse = next((d for d in DeviceManager().devices if DEVICE_NAME in d.name), None)
                    if mouse is None:
                        raise LookupError('mouse not found in OpenRazer')
                if wanted is not None:
                    mouse.dpi = (wanted, wanted)
                    self.current = wanted
                elif refresh or self.current is None:
                    self.current = mouse.dpi[0]
                self.error = None
            except Exception as err:  # OpenRazer not running, or the mouse is on Bluetooth
                mouse, self.error = None, str(err) or type(err).__name__
