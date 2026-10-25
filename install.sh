#!/bin/sh
set -eu
# Intended for Raspberry Pi OS with Desktop (Bookworm / Trixie).
# Use apt for Qt, VLC, and Python modules built for the installed OS.
sudo apt update
sudo apt install -y vlc libvlc5 python3-pyqt5 python3-pyqt5.qtsvg \
  python3-vlc python3-yaml python3-ruamel.yaml python3-mutagen python3-flask
printf '\nSystem packages installed. Launch with: python3 app.py\n'
printf 'Desktop icon: ./create_desktop_icon.sh\n'
printf 'Autostart after login: ./autostart.sh enable  (or disable/status)\n'
