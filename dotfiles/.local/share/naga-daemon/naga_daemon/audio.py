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


def background_app(focused_app, playing_players, exclude=('spotify',)):
    """An app with audio that is not focused and not excluded, or None.

    Apps whose player says it is playing come first, then active streams, then paused ones.
    """
    skip = [normalize(a) for a in (focused_app, *exclude) if a]

    def rank(stream):
        if any(names_match(n, p) for n in stream.names for p in playing_players):
            return 0
        return 2 if stream.corked else 1

    for stream in sorted(list_streams(), key=rank):
        if not stream.names or any('speechdispatcher' in n for n in stream.names):
            continue
        if any(names_match(n, k) for n in stream.names for k in skip):
            continue
        return stream.app
    return None


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
