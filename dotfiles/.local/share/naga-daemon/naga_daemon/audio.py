"""App audio streams, through pactl (PipeWire's PulseAudio interface)."""
import json, subprocess
from dataclasses import dataclass
from .util import normalize, names_match

NAME_PROPERTIES = ('application.name', 'application.process.binary', 'application.id',
                   'pipewire.access.portal.app_id', 'application.icon_name')
ICON_PROPERTIES = ('application.icon_name', 'pipewire.access.portal.app_id', 'application.id',
                   'application.name', 'application.process.binary')


@dataclass
class Stream:
    index: str
    app: str            # display name, e.g. 'Firefox'
    names: set          # normalized names to match an app against
    corked: bool        # paused
    percent: int | None
    icons: tuple = ()   # icon names to try, best first

    def belongs_to(self, app):
        want = normalize(app)
        return any(names_match(n, want) for n in self.names)


def list_streams():
    out = subprocess.run(['pactl', '-f', 'json', 'list', 'sink-inputs'], capture_output=True, text=True).stdout
    streams = []
    for s in json.loads(out or '[]'):
        props = s.get('properties', {})
        names = {normalize(props.get(k, '')) for k in NAME_PROPERTIES}
        percents = [int(c['value_percent'].rstrip('%')) for c in s.get('volume', {}).values()
                    if 'value_percent' in c]
        streams.append(Stream(
            index=str(s['index']),
            app=props.get('application.name') or props.get('application.process.binary', ''),
            names={n for n in names if len(n) >= 3},
            corked=bool(s.get('corked')),
            percent=max(percents) if percents else None,
            icons=tuple(props[k] for k in ICON_PROPERTIES if props.get(k))))
    return streams


def streams_for(app):
    return [s for s in list_streams() if s.belongs_to(app)]


def change_volume(indexes, percent):
    for index in indexes:
        subprocess.run(['pactl', 'set-sink-input-volume', index, f'{percent:+d}%'])


def volume_of(indexes):
    levels = [s.percent for s in list_streams() if s.index in indexes and s.percent is not None]
    return max(levels) if levels else None


def system_volume():
    """The default output's volume in percent, or None."""
    out = subprocess.run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'], capture_output=True, text=True).stdout
    percents = [int(part.rstrip('%')) for part in out.split() if part.endswith('%') and part[:-1].isdigit()]
    return max(percents) if percents else None
