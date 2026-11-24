import ast, asyncio, json, logging, os, shutil, subprocess

COS_CLI = shutil.which('cos-cli') or os.path.expanduser('~/.cargo/bin/cos-cli')

log = logging.getLogger(__name__)


class CosmicFocus:
    """Follows the focused window's app_id through a long-running `cos-cli serve`."""

    def __init__(self):
        self.app_id = ''
        self.output = ''   # COSMIC output name of the focused window, e.g. 'DP-1'

    async def run(self):
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    COS_CLI, 'serve', stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, limit=16 * 1024 * 1024)
                proc.stdin.write(b'{"jsonrpc":"2.0","method":"info","id":1}\n')
                await proc.stdin.drain()
                async for line in proc.stdout:
                    self.update(json.loads(line))
                log.warning('cos-cli exited with code %s; per-app keys use the default profile until it restarts',
                            await proc.wait())
            except (OSError, ValueError) as err:
                log.warning('focus tracking failed: %s', err)
            self.app_id = ''
            await asyncio.sleep(3)

    @staticmethod
    def query_output():
        """The focused window's output, asked fresh (about 0.2 s).

        The long-running `cos-cli serve` keeps stale output names after a monitor reconnects.
        """
        try:
            out = subprocess.run([COS_CLI, 'info', '--json'], capture_output=True, text=True, timeout=2).stdout
            for app in json.loads(out).get('apps', []):
                if 'activated' in app.get('state', []):
                    return (app.get('outputs') or [{}])[0].get('name', '')
        except (OSError, ValueError, subprocess.TimeoutExpired) as err:
            log.warning('cos-cli info failed: %s', err)
        return ''

    @staticmethod
    def set_on_top(on):
        """Make the focused window sticky (on all workspaces, above other windows) or not.
        COSMIC has no "always on top", so sticky stands in for it.

        Returns the window's app_id, or '' if no window is focused.
        """
        try:
            out = subprocess.run([COS_CLI, 'info', '--json'], capture_output=True, text=True, timeout=2).stdout
            for app in json.loads(out).get('apps', []):
                if 'activated' in app.get('state', []):
                    subprocess.run([COS_CLI, 'state', '-i', str(app['index']), '--sticky' if on else '--unsticky'],
                                   capture_output=True, timeout=2)
                    return app.get('app_id', '')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as err:
            log.warning('cos-cli state failed: %s', err)
        return ''

    def update(self, msg):
        """Handle an `info` reply or a `state_change` notification."""
        state = msg.get('result') or (msg.get('params') or {}).get('state') or {}
        for app in state.get('apps', []):
            if 'activated' in app.get('state', []):
                self.app_id = app.get('app_id', '')
                outputs = app.get('outputs') or [{}]
                self.output = outputs[0].get('name', '')
                return


GNOME_NAME, GNOME_PATH = 'io.mouseo.Naga', '/io/mouseo/Naga'
GNOME_MONITOR = ['gdbus', 'monitor', '--session', '--dest', GNOME_NAME, '--object-path', GNOME_PATH]


def gnome_call(method, *args):
    """Call the naga@mouseo GNOME Shell extension. Returns its reply as a tuple, or None."""
    try:
        r = subprocess.run(['gdbus', 'call', '--session', '--dest', GNOME_NAME, '--object-path', GNOME_PATH,
                            '--method', f'{GNOME_NAME}.{method}', *args], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            return ast.literal_eval(r.stdout.strip())
        log.debug('GNOME extension %s failed: %s', method, r.stderr.strip())
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as err:
        log.warning('GNOME extension %s failed: %s', method, err)
    return None


def parse_gnome_signal(line):
    """(app_id, output) from a `gdbus monitor` FocusChanged line, else None.

    "/io/mouseo/Naga: io.mouseo.Naga.FocusChanged ('firefox', 'DP-1')"
    """
    marker = '.FocusChanged '
    if marker not in line:
        return None
    try:
        app_id, output = ast.literal_eval(line.split(marker, 1)[1].strip())
        return app_id, output
    except (ValueError, SyntaxError, TypeError):
        return None


class GnomeFocus:
    """Follows the focused window through the naga@mouseo GNOME Shell extension (in the dotfiles)."""

    def __init__(self):
        self.app_id = ''
        self.output = ''   # connector of the focused window's monitor, e.g. 'DP-1'

    def set(self, app_id, output):
        self.app_id, self.output = app_id, output

    async def run(self):
        warned = False
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(*GNOME_MONITOR, stdout=subprocess.PIPE,
                                                            stderr=subprocess.DEVNULL)
                async for raw in proc.stdout:
                    line = raw.decode(errors='replace')
                    if (focused := parse_gnome_signal(line)) is not None:
                        self.set(*focused)
                    elif 'is owned by' in line:   # the extension started (or was already running)
                        self.set(*(await asyncio.to_thread(gnome_call, 'Focused') or ('', '')))
                        log.info('focus tracking through the GNOME extension naga@mouseo')
                    elif 'does not have an owner' in line:
                        self.set('', '')
                        if not warned:
                            log.warning('GNOME extension naga@mouseo is not running: per-app keys use the '
                                        'default profile, and always on top does nothing. GNOME loads new '
                                        'extensions at login.')
                            warned = True
                log.warning('gdbus monitor exited with code %s', await proc.wait())
            except OSError as err:
                log.warning('focus tracking failed: %s', err)
            self.set('', '')
            await asyncio.sleep(3)

    @staticmethod
    def query_output():
        """The focused window's output, asked fresh."""
        reply = gnome_call('Focused')
        return reply[1] if reply else ''

    @staticmethod
    def set_on_top(on):
        """Keep the focused window above other windows, or stop. Returns its app_id, or ''."""
        reply = gnome_call('SetAbove', 'true' if on else 'false')
        return reply[0] if reply else ''
