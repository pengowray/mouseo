import asyncio, json, logging, os, shutil, subprocess

log = logging.getLogger(__name__)


class Focus:
    """Follows the focused window's app_id through a long-running `cos-cli serve`."""

    def __init__(self):
        self.app_id = ''

    async def run(self):
        exe = shutil.which('cos-cli') or os.path.expanduser('~/.cargo/bin/cos-cli')
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    exe, 'serve', stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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

    def update(self, msg):
        """Handle an `info` reply or a `state_change` notification."""
        state = msg.get('result') or (msg.get('params') or {}).get('state') or {}
        for app in state.get('apps', []):
            if 'activated' in app.get('state', []):
                self.app_id = app.get('app_id', '')
                return
