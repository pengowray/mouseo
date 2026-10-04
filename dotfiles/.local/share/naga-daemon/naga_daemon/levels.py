"""How loud each app is right now, for the meters behind the pie's wedges.

Records each sink input's monitor with parec at a low rate and keeps its latest peak. Reader
threads only store numbers; the UI polls `level()` from its own loop.
"""
import array, math, subprocess, threading

RATE = 8000
CHUNK = 400                 # bytes: 25 ms of 16-bit mono
FLOOR_DB = -60              # quieter than this shows as empty


def to_level(peak):
    """A sample peak (0..1) on a dB scale from FLOOR_DB to 0, as 0..1."""
    db = 20 * math.log10(max(peak, 1e-5))
    return min(max(1 - db / FLOOR_DB, 0.0), 1.0)


class Meters:
    def __init__(self):
        self.procs = []
        self.peaks = {}           # stream index -> latest level, 0..1

    def start(self, indexes):
        self.stop()
        for index in dict.fromkeys(indexes):
            try:
                proc = subprocess.Popen(
                    ['parec', f'--monitor-stream={index}', '--raw', '--format=s16le', '--channels=1',
                     f'--rate={RATE}', '--latency-msec=30'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                return            # no parec: no meters
            self.procs.append(proc)
            threading.Thread(target=self._read, args=(proc, index), daemon=True).start()

    def _read(self, proc, index):
        # A paused stream makes parec give up after about a second; it then reads as silent.
        while chunk := proc.stdout.read(CHUNK):
            samples = array.array('h', chunk[:len(chunk) // 2 * 2])
            if samples:
                self.peaks[index] = to_level(max(map(abs, samples)) / 32768)
        proc.wait()
        self.peaks[index] = 0.0

    def level(self, indexes):
        return max((self.peaks.get(i, 0.0) for i in indexes), default=0.0)

    def stop(self):
        for proc in self.procs:
            proc.kill()
        self.procs, self.peaks = [], {}
