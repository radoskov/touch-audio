#!/bin/sh
# Manage GUI session autostart; no root access or systemd unit needed.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TARGET=${XDG_CONFIG_HOME:-"$HOME/.config"}/autostart/touch-audio.desktop
case "${1:-}" in
  enable)
    "$APP_DIR/scripts/write_desktop_entry.sh" "$TARGET"
    printf 'Enabled desktop-login autostart: %s\n' "$TARGET"
    ;;
  disable)
    if [ -e "$TARGET" ]; then
      if ! grep -q '^X-TouchAudio-Launcher=1$' "$TARGET"; then
        echo "Refusing to remove a desktop entry not created by Touch Audio: $TARGET" >&2
        exit 1
      fi
      rm -- "$TARGET"
    fi
    echo 'Desktop-login autostart disabled.'
    ;;
  status)
    if [ -f "$TARGET" ] && grep -q '^X-TouchAudio-Launcher=1$' "$TARGET"; then
      printf 'Enabled: %s\n' "$TARGET"
    else
      echo 'Disabled'
    fi
    ;;
  *)
    echo 'Usage: ./autostart.sh enable|disable|status' >&2
    exit 2
    ;;
esac
