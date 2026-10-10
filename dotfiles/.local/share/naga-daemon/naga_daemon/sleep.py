"""Notices when the PC goes to sleep and wakes up, through logind's PrepareForSleep signal.

After a wake the volume pie stopped appearing: it still got its messages but drew nothing,
while a freshly started pie worked. So __main__ stops the pie around sleep, and the next press
of thumb 5 starts a new one.
"""
import asyncio, logging, subprocess

log = logging.getLogger(__name__)

MONITOR = ['gdbus', 'monitor', '--system', '--dest', 'org.freedesktop.login1',
           '--object-path', '/org/freedesktop/login1']


def parse(line):
    """A `gdbus monitor` line: True if the PC is about to sleep, False if it just woke, else None.

    '/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)'
    """
    if '.PrepareForSleep (' not in line:
        return None
    return '(true,)' in line


class SleepWatch:
    def __init__(self, on_change):
        self.on_change = on_change   # called with True before sleeping and False after waking

    async def run(self):
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *MONITOR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                async for line in proc.stdout:
                    sleeping = parse(line.decode(errors='replace'))
                    if sleeping is not None:
                        self.on_change(sleeping)
                log.warning('gdbus monitor exited with code %s; the volume pie may not work after the PC sleeps',
                            await proc.wait())
            except FileNotFoundError:
                log.warning('gdbus not found; the volume pie may not work after the PC sleeps')
                return
            except OSError as err:
                log.warning('sleep tracking failed: %s', err)
            await asyncio.sleep(10)
