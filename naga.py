#!/usr/bin/env python3
"""Read (and later write) onboard button assignments on a Razer Naga V2 HyperSpeed.

Uses the protocol reverse-engineered by razerqdhid (vendor/razerqdhid), talking
to the mouse's control interface through Linux hidraw feature reports.
"""
import fcntl, glob, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor/razerqdhid/public/py'))
import qdrazer.protocol as pt

VID, PID = 0x1532, 0x00B4
REPORT_LEN = 91  # report id byte + 90-byte Razer report


def _ioc(nr, size):
    return (3 << 30) | (size << 16) | (ord('H') << 8) | nr  # _IOWR('H', nr, size)

HIDIOCSFEATURE = _ioc(0x06, REPORT_LEN)
HIDIOCGFEATURE = _ioc(0x07, REPORT_LEN)


def find_control_hidraw():
    """The control channel is the 90-byte vendor feature report on USB interface 0."""
    for d in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        uevent = open(os.path.join(d, 'device/uevent')).read()
        if f'HID_ID=0003:{VID:08X}:{PID:08X}' not in uevent:
            continue
        if os.path.realpath(os.path.join(d, 'device')).split('/')[-2].endswith(':1.0'):
            return '/dev/' + os.path.basename(d)
    sys.exit('Naga V2 HyperSpeed receiver not found')


class Naga:
    def __init__(self, path=None):
        self.path = path or find_control_hidraw()
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except PermissionError:
            sys.exit(f'No permission for {self.path}. Run: sudo chmod a+rw {self.path}')

    def transact(self, command, args=b'', size=None):
        """Send one command and return the response arguments. Raises on failure."""
        size = len(args) if size is None else size
        r = pt.Report.new((command >> 8) & 0xff, command & 0xff, size)
        r.arguments[:len(args)] = args
        r.calculate_crc()
        out = bytearray(b'\x00' + bytes(r))
        for attempt in range(3):
            fcntl.ioctl(self.fd, HIDIOCSFEATURE, out)
            for i in range(20):
                time.sleep(0.005 * (i + 1))
                buf = bytearray(REPORT_LEN)
                fcntl.ioctl(self.fd, HIDIOCGFEATURE, buf)
                rr = pt.Report.from_buffer_copy(bytes(buf[1:]))
                if (rr.command_class, rr.command_id.id) != (r.command_class, r.command_id.id):
                    break  # another program's reply; resend
                if rr._status == pt.Status.BUSY.value:
                    continue
                if rr._status == pt.Status.OK.value:
                    return bytes(rr.arguments[:max(size, rr.data_size)])
                raise pt.RazerException(pt.Status(rr._status).name)
        raise pt.RazerException('no matching reply')

    def get_button_function(self, button, hypershift=0, profile=1):
        data = self.transact(0x028c, bytes([profile, button, hypershift]), size=10)
        return pt.ButtonFunction.from_buffer_copy(data[3:10])

    def set_button_function(self, button, bf, hypershift=0, profile=1):
        self.transact(0x020c, bytes([profile, button, hypershift]) + bytes(bf))


def describe(bf):
    try:
        cat = bf.get_category()
    except ValueError:
        return f'unknown class 0x{bf._fn_class:02x} {bf.get_fn_value().hex(" ")}'
    try:
        detail = getattr(bf, 'get_' + cat)()
    except Exception:
        detail = bf.get_fn_value().hex(' ')
    return f'{cat:<18} {detail}'
