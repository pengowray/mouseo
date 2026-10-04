from .keys import parse_combo


class Profiles:
    """Per-app keys for playback speed and seeking, from the config's [profiles.*] tables."""

    ACTIONS = ('faster', 'slower', 'faster_fine', 'slower_fine', 'back', 'forward', 'play_pause')

    def __init__(self, table):
        self.profiles = []
        for name, p in table.items():
            unknown = set(p) - {'apps', *self.ACTIONS}
            if unknown:
                raise ValueError(f'profile "{name}": unknown setting {", ".join(sorted(unknown))}')
            combos = {k: parse_combo(v) for k, v in p.items() if k != 'apps'}
            self.profiles.append((name, [a.lower() for a in p.get('apps', [])], combos))
        self.default = next((c for n, _, c in self.profiles if n == 'default'), {})

    def for_app(self, app_id):
        """The first profile whose "apps" matches part of the app_id, else "default"."""
        app = app_id.lower()
        for _, apps, combos in self.profiles:
            if any(a in app for a in apps):
                return combos
        return self.default

    def keys(self):
        return {code for _, _, combos in self.profiles for combo in combos.values() for code in combo}
