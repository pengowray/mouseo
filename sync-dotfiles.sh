#!/usr/bin/env bash
# Copies the naga-daemon files from this machine into dotfiles/, for reference.
# The chezmoi dotfiles repo is where they are edited and installed from; run this after
# changing them there, so this repo keeps a matching copy.
set -euo pipefail
cd "$(dirname "$0")"
OUT=dotfiles
rm -rf "$OUT"
copy() { mkdir -p "$OUT/$(dirname "$1")"; cp -r "$HOME/$1" "$OUT/$1"; }
copy .local/bin/naga-daemon
copy .local/share/naga-daemon
copy .config/naga/config.toml
copy .config/systemd/user/naga-daemon.service
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
# The Razer section of the setup script (packages, cos-cli, udev rule)
sed -n '/^# --- Razer Naga/,/^# --- fonts/p' "$(chezmoi source-path)/.chezmoiscripts/run_onchange_before_install-essentials.sh" \
  | sed '$d' > "$OUT/install-essentials-naga-section.sh"
echo "Copied to $OUT/:"; find "$OUT" -type f | sort
