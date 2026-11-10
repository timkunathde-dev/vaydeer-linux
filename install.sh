#!/bin/bash
# Vaydeer for Linux – installer
#   Install / update:  ./install.sh
#   Uninstall:         ./install.sh --uninstall
set -e

if [ "$EUID" -eq 0 ]; then
  echo "Please run WITHOUT sudo (the script asks for your password itself)."
  echo "Bitte OHNE sudo starten (das Skript fragt selbst nach dem Passwort)."
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR=/opt/vaydeer-linux
UNIT_DIR="$HOME/.config/systemd/user"
DESKTOP="$HOME/.local/share/applications/vaydeer-linux.desktop"
AUTOSTART="$HOME/.config/autostart/vaydeer-overlay.desktop"

stop_overlay() {
  pkill -u "$USER" -f "vaydeer-overlay.py" 2>/dev/null || true
}

if [ "$1" = "--uninstall" ]; then
  echo "→ Removing Vaydeer for Linux …"
  systemctl --user disable --now vaydeerd.service 2>/dev/null || true
  stop_overlay
  rm -f "$UNIT_DIR/vaydeerd.service" "$DESKTOP" "$AUTOSTART"
  systemctl --user daemon-reload
  sudo rm -rf "$APPDIR" /usr/local/bin/vaydeer-linux /usr/local/bin/vaydeer-overlay \
    /etc/udev/rules.d/70-vaydeer-linux.rules /etc/modules-load.d/vaydeer-linux.conf
  sudo udevadm control --reload-rules
  echo "✔ Uninstalled. Your key mapping is kept in ~/.config/vaydeer-linux/"
  exit 0
fi

for f in src/vaydeer_common.py src/vaydeerd.py src/vaydeer-gui.py src/vaydeer-overlay.py \
         data/70-vaydeer-linux.rules data/vaydeerd.service data/vaydeer-linux.desktop; do
  if [ ! -f "$SRC/$f" ]; then
    echo "Missing file: $f – please run install.sh from inside the repository folder."
    exit 1
  fi
done

echo "→ Installing dependencies …"
sudo apt-get install -y python3-evdev python3-gi gir1.2-gtk-4.0 gir1.2-gtk-3.0 libnotify-bin >/dev/null

# Replace the early test driver, if present
if [ -f /etc/systemd/system/vaydeer-keypad.service ]; then
  sudo systemctl disable --now vaydeer-keypad.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/vaydeer-keypad.service
  sudo systemctl daemon-reload
fi
sudo rm -f /usr/local/bin/vaydeer-keypad.py

echo "→ Copying program files to $APPDIR …"
sudo mkdir -p "$APPDIR"
sudo install -m 644 "$SRC/src/vaydeer_common.py" "$APPDIR/"
sudo install -m 755 "$SRC/src/vaydeerd.py" "$SRC/src/vaydeer-gui.py" "$SRC/src/vaydeer-overlay.py" "$APPDIR/"
printf '#!/bin/sh\nexec /usr/bin/python3 %s/vaydeer-gui.py "$@"\n' "$APPDIR" \
  | sudo tee /usr/local/bin/vaydeer-linux >/dev/null
printf '#!/bin/sh\nexec /usr/bin/python3 %s/vaydeer-overlay.py "$@"\n' "$APPDIR" \
  | sudo tee /usr/local/bin/vaydeer-overlay >/dev/null
sudo chmod 755 /usr/local/bin/vaydeer-linux /usr/local/bin/vaydeer-overlay

echo "→ Setting up device permissions (udev) …"
sudo install -D -m 644 "$SRC/data/70-vaydeer-linux.rules" /etc/udev/rules.d/70-vaydeer-linux.rules
sudo mkdir -p /etc/modules-load.d
echo uinput | sudo tee /etc/modules-load.d/vaydeer-linux.conf >/dev/null
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=change
sudo udevadm trigger --subsystem-match=misc --action=change

echo "→ Setting up background service …"
mkdir -p "$UNIT_DIR"
install -m 644 "$SRC/data/vaydeerd.service" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable vaydeerd.service >/dev/null 2>&1
systemctl --user restart vaydeerd.service

echo "→ Adding menu entry …"
mkdir -p "$(dirname "$DESKTOP")"
install -m 644 "$SRC/data/vaydeer-linux.desktop" "$DESKTOP"

# Restart a running overlay with the new version
if pgrep -u "$USER" -f "vaydeer-overlay.py" >/dev/null; then
  stop_overlay
  sleep 1
  setsid /usr/local/bin/vaydeer-overlay >/dev/null 2>&1 < /dev/null &
fi

sleep 2
echo
if systemctl --user is-active --quiet vaydeerd.service; then
  echo "✔ Done! Start “Vaydeer für Linux” from your app menu or run: vaydeer-linux"
else
  echo "Installed, but the service is not running yet. Please log out and back in once."
fi
