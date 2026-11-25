def normalize(name):
    """Lowercase letters and digits only: 'VLC media player' -> 'vlcmediaplayer'."""
    return ''.join(ch for ch in name.lower() if ch.isalnum())


def names_match(a, b):
    """Whether two normalized app names refer to the same app ('firefox' and 'firefoxbin')."""
    return len(a) >= 3 and len(b) >= 3 and (a in b or b in a)


def app_label(app):
    """A readable app name: 'VLC media player (LibVLC 3.0)' -> 'VLC media player', 'com.google.Chrome' -> 'Chrome'."""
    return app.split(' (')[0] if ' ' in app else app.rsplit('.', 1)[-1]
