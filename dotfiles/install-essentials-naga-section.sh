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
# OpenRazer's udev rules only cover the USB receiver. This one lets the logged-in user read
# the mouse over Bluetooth too (naga-daemon), and reach its control channel (mouseo).
# It must sort before 73-seat-late.rules for uaccess to apply.
NAGA_RULES=/etc/udev/rules.d/70-razer-naga.rules
NAGA_RULES_NEW=$(mktemp -p "$TMP")
cat > "$NAGA_RULES_NEW" <<'RULES'
# Installed by run_onchange_before_install-essentials.sh in the chezmoi dotfiles.
# USB receiver: "Naga V2 HyperSpeed", 1532:00b4. Bluetooth: "Naga V2 HS", HID id 0005:068E:00B5.
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Naga V2 HyperSpeed*", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Naga V2 HS*", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1532", ATTRS{idProduct}=="00b4", TAG+="uaccess"
SUBSYSTEM=="hidraw", KERNELS=="0005:068E:00B5.*", TAG+="uaccess"
RULES
if ! cmp -s "$NAGA_RULES_NEW" "$NAGA_RULES"; then
  log "Installing $NAGA_RULES"
  sudo install -m 0644 "$NAGA_RULES_NEW" "$NAGA_RULES"
  sudo udevadm control --reload
  sudo udevadm trigger --subsystem-match=input --subsystem-match=hidraw
fi
# naga-daemon.service is enabled by the tracked graphical-session.target.wants symlink

# --- dasho: local dashboard on http://localhost/ (~/projects/dasho) -----------------
# A system service, run by Bun from the path in the repo's dasho.service. That path is in
# an nvm Node folder (npm installs Bun there), so install that Node version and Bun into it.
# ~/projects comes from Syncthing, so on a new machine dasho is skipped until it has synced.
DASHO="$HOME/projects/dasho"
if [ -f "$DASHO/dasho.service" ]; then
  BUN=$(sed -n 's/^ExecStart=\([^ ]*bun\) .*/\1/p' "$DASHO/dasho.service")
  if [ -n "$BUN" ] && [ ! -x "$BUN" ]; then
    case "$BUN" in
      "$HOME"/.nvm/versions/node/v*/bin/bun)
        node_ver=${BUN#"$HOME"/.nvm/versions/node/}; node_ver=${node_ver%%/*}
        log "Installing Node $node_ver and Bun for dasho"
        export NVM_DIR="$HOME/.nvm"
        set +u; . "$NVM_DIR/nvm.sh"; nvm install "$node_ver"; set -u
        "$HOME/.nvm/versions/node/$node_ver/bin/npm" install -g bun
        ;;
      *) log "dasho.service runs Bun from $BUN, which isn't installed. Install it there or edit the service." ;;
    esac
  fi
  if [ -x "$BUN" ]; then
    if [ ! -d "$DASHO/node_modules" ]; then
      log "Installing dasho's packages"
      (cd "$DASHO" && "$BUN" install)
    fi
    if ! cmp -s "$DASHO/dasho.service" /etc/systemd/system/dasho.service; then
      log "Installing dasho.service"
      sudo cp "$DASHO/dasho.service" /etc/systemd/system/dasho.service
      sudo systemctl daemon-reload
      sudo systemctl enable dasho
      sudo systemctl restart dasho
    fi
  fi
else
  log "Skipping dasho: $DASHO isn't here yet (it comes from Syncthing). Re-run this script once it has synced."
fi

# --- VOICSKY ECHO 96 keyboard ----------------------------------------------------------
# Lets the logged-in user's browser reach the keyboard over WebHID, which the AETHER web
# control panel uses (wired USB only, Chromium browsers only). Without it the browser lists
# the keyboard but fails to connect. It must sort before 73-seat-late.rules for uaccess to apply.
ECHO_RULES=/etc/udev/rules.d/70-voicsky-echo.rules
ECHO_RULES_NEW=$(mktemp -p "$TMP")
cat > "$ECHO_RULES_NEW" <<'RULES'
# Installed by run_onchange_before_install-essentials.sh in the chezmoi dotfiles.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0c45", ATTRS{idProduct}=="8009", TAG+="uaccess"
RULES
if ! cmp -s "$ECHO_RULES_NEW" "$ECHO_RULES"; then
  log "Installing $ECHO_RULES"
  sudo install -m 0644 "$ECHO_RULES_NEW" "$ECHO_RULES"
  sudo udevadm control --reload
  sudo udevadm trigger --subsystem-match=hidraw
fi

