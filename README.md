# mouseo

Onboard button layout for a Razer Naga V2 HyperSpeed, written from Linux without Synapse.

> [!WARNING]
> This is my personal mouse setup, not indended as a general utility.

# about

The layout is stored in the mouse, so it works on any computer. A few buttons send spare
F-keys (F13-F17, F19, F24) that the `naga-daemon` user service turns into app volume,
playback speed, DPI, screen zoom and push to talk. The daemon and its settings are in the
chezmoi dotfiles, not here:

- `~/.local/share/naga-daemon/naga_daemon/` (the code; `~/.local/bin/naga-daemon` starts it)
- `~/.config/naga/config.toml` (per-app keys, DPI step, volume step)
- `~/.config/systemd/user/naga-daemon.service`

Its tests: `cd ~/.local/share/naga-daemon && python3 -m unittest discover -s tests -t .`

Setup steps that need sudo (OpenRazer, cos-cli, udev rule) are in the dotfiles'
`install-essentials.sh`.

## Files

| File | What it does |
|---|---|
| `layout.py` | The layout: every button, normal and while holding Hyper (thumb 5). |
| `apply.py` | Shows how the mouse differs from `layout.py`. `--write` writes and verifies. |
| `probe.py` | Prints every button assignment the mouse reports. Read-only. |
| `backup.py` | Saves the raw assignments to a JSON file. |
| `sync-dotfiles.sh` | Copies the daemon's installed files into `dotfiles/`, for reference. |
| `dotfiles/` | That copy. Edit the chezmoi repo, not these. |
| `test_top_buttons.py` | For a minute, shows a notification when either top button is pressed. |
| `naga.py` | Talks to the mouse over hidraw feature reports. |
| `vendor/razerqdhid` | Protocol library by geezmolycos (MIT), cloned, not committed. |

## Use

```bash
git clone https://github.com/geezmolycos/razerqdhid.git vendor/razerqdhid
python3 apply.py           # show differences
python3 apply.py --write   # write them
```

Writing needs access to the receiver's hidraw device. The dotfiles' udev rule grants it to
the logged-in user; without it, run with `sudo` or `sudo chmod a+rw /dev/hidrawN`.

Only works through the USB receiver (product id `00b4`), not Bluetooth.

## Layout

| Button | Normal | Holding Hyper |
|---|---|---|
| Top button 1 | Hyper | Hyper |
| Top button 2 | push to talk | push to talk |
| Middle click | middle click | play/pause |
| Wheel | scroll | volume |
| Tilt left / right | Ctrl / push to talk | previous / next track |
| Thumb 1 | hold + wheel: screen zoom | Keypad Enter |
| Thumb 2 | tap: middle click, hold + wheel: DPI | play/pause |
| Thumb 3 | Ctrl+Home | nothing |
| Thumb 4 | Shift+Alt | previous track |
| Thumb 5 | Hyper | Hyper |
| Thumb 6 | Ctrl+End | next track |
| Thumb 7 | hold: background app's volume and media | nothing |
| Thumb 8 | hold: focused app's volume and media | nothing |
| Thumb 9 | hold: Spotify's volume and media | nothing |
| Thumb 10 | Esc | nothing |
| Thumb 11 | hold: fine playback speed, seek | nothing |
| Thumb 12 | hold: playback speed, seek | nothing |

Push to talk reaches apps as mouse button 12 (Discord shows it as MOUSE12).

## What the mouse supports

Tested through the receiver with the razerqdhid commands (2026-10-04, firmware 1.1):

| Command | Works |
|---|---|
| Button functions, normal and Hyper layer (`0x020c` / `0x028c`) | yes |
| Serial, firmware, device mode | yes |
| Profiles: count and list (`0x058a`, `0x0580`) | yes, 1 profile |
| Polling rate, DPI, DPI stages | yes |
| Battery level (`0x0780`), idle time (`0x0783`) | yes |
| Sensor lift (`0x0b8b`) | yes |
| Scroll mode, scroll acceleration, smart reel | not supported |
| LED effect and brightness | not supported |
| Flash usage, macro list and count | not supported |

Button ids: left/right/middle `0x01`-`0x03`, wheel up/down `0x09`/`0x0a`, top buttons
`0x0b` (front) / `0x0c` (behind it), tilt left/right `0x34`/`0x35`, thumb grid 1-12 `0x40`-`0x4b`.
The control channel is the 90-byte feature report on USB interface 0, transaction id `0x1f`.
