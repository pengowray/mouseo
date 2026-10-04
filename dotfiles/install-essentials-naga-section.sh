# --- Razer Naga V2 HyperSpeed: OpenRazer, Polychromatic, naga-daemon ------------------
# The mouse's onboard button layout is written with ~/projects/mouseo. The tracked
# naga-daemon user service gives its extra keys their behaviour (app volume, playback speed,
# DPI, push to talk, volume pie). It needs python3-evdev, playerctl, gtk-layer-shell (to draw
# the volume pie), OpenRazer (for DPI) and cos-cli (to follow the focused window). plugdev
# lets the daemon read the mouse (takes effect at next login). uinput access comes from steam-devices, above.
for ppa in openrazer polychromatic; do
  if ! ls /etc/apt/sources.list.d/ | grep -q "^$ppa-"; then
    log "Adding $ppa PPA"
    sudo add-apt-repository -y "ppa:$ppa/stable"
  fi
done
NAGA_PKGS=(openrazer-meta polychromatic python3-evdev python3-dbus playerctl gir1.2-gtklayershell-0.1)
NAGA_MISSING=()
for p in "${NAGA_PKGS[@]}"; do pkg_installed "$p" || NAGA_MISSING+=("$p"); done
if [ ${#NAGA_MISSING[@]} -gt 0 ]; then
  log "Installing Razer mouse packages: ${NAGA_MISSING[*]}"
  sudo apt-get install -y "${NAGA_MISSING[@]}"
fi
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx plugdev; then
  sudo gpasswd -a "$USER" plugdev
fi
if [ ! -x "$HOME/.cargo/bin/cos-cli" ]; then
  log "Installing cos-cli"
  cargo install --locked --git https://github.com/estin/cos-cli
fi
# Reports the focused window's size to naga-daemon, for proportional resizing (thumb 7 + right drag)
if [ ! -x "$HOME/.cargo/bin/cosmic-window-watch" ]; then
  log "Installing cosmic-window-watch"
  cargo install --locked --git https://github.com/pengowray/mouseo cosmic-window-watch
fi
# OpenRazer's udev rules only cover the USB receiver. This one lets the logged-in user read
# the mouse over Bluetooth too (naga-daemon), and reach its control channel (mouseo).
# It must sort before 73-seat-late.rules for uaccess to apply.
NAGA_RULES=/etc/udev/rules.d/70-razer-naga.rules
NAGA_RULES_NEW=$(mktemp -p "$TMP")
cat > "$NAGA_RULES_NEW" <<'RULES'
# Installed by run_onchange_before_install-essentials.sh in the chezmoi dotfiles.
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Naga V2 HyperSpeed*", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1532", ATTRS{idProduct}=="00b4", TAG+="uaccess"
RULES
if ! cmp -s "$NAGA_RULES_NEW" "$NAGA_RULES"; then
  log "Installing $NAGA_RULES"
  sudo install -m 0644 "$NAGA_RULES_NEW" "$NAGA_RULES"
  sudo udevadm control --reload
  sudo udevadm trigger --subsystem-match=input --subsystem-match=hidraw
fi
# naga-daemon.service is enabled by the tracked graphical-session.target.wants symlink

