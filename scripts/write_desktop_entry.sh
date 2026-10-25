#!/bin/sh
# Private helper: write the launcher in FreeDesktop format.
set -eu
[ "$#" -eq 1 ] || { echo 'Usage: write_desktop_entry.sh DESTINATION' >&2; exit 2; }
DEST=$1
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
# A desktop Exec value uses different quoting from the shell; quote the
# executable path and escape all characters special in quoted desktop strings.
escape_exec() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\$/\\$/g' -e 's/`/\\`/g'
}
LAUNCHER=$(escape_exec "$APP_DIR/launch.sh")
WORK_DIR=$(escape_exec "$APP_DIR")
mkdir -p "$(dirname -- "$DEST")"
if [ -e "$DEST" ] && ! grep -q '^X-TouchAudio-Launcher=1$' "$DEST"; then
  echo "Refusing to overwrite a desktop entry not created by Touch Audio: $DEST" >&2
  exit 1
fi
cat > "$DEST" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Touch Audio
Comment=Touchscreen audiobook and music player
Exec="$LAUNCHER"
Path="$WORK_DIR"
Icon=$APP_DIR/assets/app.svg
Terminal=false
Categories=AudioVideo;Audio;Player;
Keywords=music;audiobook;player;
StartupNotify=true
X-TouchAudio-Launcher=1
DESKTOP
chmod 755 "$DEST"
