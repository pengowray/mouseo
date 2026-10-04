"""Media players, through playerctl (MPRIS)."""
import subprocess
from .util import normalize, names_match


def _playerctl(*args):
    return subprocess.run(['playerctl', *args], capture_output=True, text=True).stdout


def find_player(app):
    """The player name playerctl uses for the app ('firefox.instance_1_23'), or None."""
    want = normalize(app)
    for player in _playerctl('-l').split():
        if names_match(normalize(player.split('.')[0]), want):
            return player
    return None


def playing():
    """Normalized names of players that say they are playing. Updates the moment you press pause."""
    out = _playerctl('-a', 'metadata', '--format', '{{playerName}}|{{status}}')
    return {normalize(line.split('|')[0]) for line in out.splitlines() if line.endswith('|Playing')}


def control(player, command):
    """command: 'play-pause', 'previous' or 'next'."""
    subprocess.run(['playerctl', '-p', player, command])
