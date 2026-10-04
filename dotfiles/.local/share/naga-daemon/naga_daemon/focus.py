import asyncio, json, logging, os, shutil, subprocess

COS_CLI = shutil.which('cos-cli') or os.path.expanduser('~/.cargo/bin/cos-cli')

log = logging.getLogger(__name__)


class Focus:
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
    def set_sticky(on):
        """Make the focused window sticky (on all workspaces, above other windows) or not.

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
