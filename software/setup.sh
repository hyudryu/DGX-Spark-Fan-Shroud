#!/usr/bin/env bash
# Set up the Fan Controller app on this machine.
#
#   ./setup.sh             install everything and enable autostart
#   ./setup.sh --no-enable install but don't enable the systemd unit
#
# Idempotent — safe to re-run.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_UNIT_DIR="$HOME/.config/systemd/user"
USER_APPS_DIR="$HOME/.local/share/applications"
ENABLE=1
for arg in "$@"; do
  case "$arg" in
    --no-enable) ENABLE=0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

echo "[1/5] installing apt packages (will prompt for sudo)…"
sudo apt-get update -qq
sudo apt-get install -y \
  python3-gi \
  python3-gi-cairo \
  gir1.2-gtk-3.0 \
  gir1.2-ayatanaappindicator3-0.1 \
  python3-serial \
  gnome-shell-extension-appindicator || true

echo "[2/5] adding $USER to dialout group (for /dev/ttyACM*)…"
if ! id -nG "$USER" | grep -qw dialout; then
  sudo usermod -aG dialout "$USER"
  echo "    -> log out and back in for the group change to take effect."
fi

echo "[3/5] installing systemd user unit…"
mkdir -p "$USER_UNIT_DIR"
cp "$INSTALL_DIR/packaging/fancontroller.service" "$USER_UNIT_DIR/fancontroller.service"
# Replace WorkingDirectory placeholder with the real install dir
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" \
  "$USER_UNIT_DIR/fancontroller.service"
systemctl --user daemon-reload

echo "[4/5] installing application launcher (.desktop)…"
mkdir -p "$USER_APPS_DIR"
sed "s|__INSTALL_DIR__|$INSTALL_DIR|" \
  "$INSTALL_DIR/packaging/fancontroller.desktop" \
  > "$USER_APPS_DIR/fancontroller.desktop"
chmod +x "$USER_APPS_DIR/fancontroller.desktop"
update-desktop-database "$USER_APPS_DIR" 2>/dev/null || true

if [ "$ENABLE" -eq 1 ]; then
  echo "[5/5] enabling headless fan control…"
  systemctl --user reenable fancontroller.service
else
  echo "[5/5] skipping autostart (--no-enable)."
fi

echo
echo "Done. Try it now:"
echo "  python3 -m fancontroller --ui-only # open configuration UI"
echo "  systemctl --user start fancontroller"
echo "  systemctl --user status fancontroller"
echo
echo "Pin to dash: search 'Fan Controller' in the activities view, then right-click → 'Pin to Dash'."
