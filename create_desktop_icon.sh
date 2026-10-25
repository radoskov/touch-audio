#!/bin/sh
# Register Touch Audio as a proper desktop application and create its shortcut.
# Run this as the desktop user (not sudo).
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
APPLICATIONS_DIR=${XDG_DATA_HOME:-"$HOME/.local/share"}/applications
MENU_ENTRY=$APPLICATIONS_DIR/touch-audio.desktop
"$APP_DIR/scripts/write_desktop_entry.sh" "$MENU_ENTRY"
if command -v xdg-user-dir >/dev/null 2>&1; then
  DESKTOP_DIR=$(xdg-user-dir DESKTOP)
else
  DESKTOP_DIR=$HOME/Desktop
fi
[ -n "$DESKTOP_DIR" ] || DESKTOP_DIR=$HOME/Desktop
TARGET=$DESKTOP_DIR/touch-audio.desktop
"$APP_DIR/scripts/write_desktop_entry.sh" "$TARGET"
# Trust is per-user metadata on some file managers, and may require GVfs.
# Never globally disable the OS's safety prompt for all executable files.
TRUSTED=no
if command -v gio >/dev/null 2>&1; then
  if gio set "$TARGET" metadata::trusted true >/dev/null 2>&1; then
    TRUSTED=yes
  fi
fi
printf 'Installed application-menu entry: %s\n' "$MENU_ENTRY"
printf 'Desktop shortcut: %s\n' "$TARGET"
if [ "$TRUSTED" = no ]; then
  printf '%s\n' 'Desktop trust metadata was unavailable. If prompted, use the file manager'
  printf '%s\n' 'right-click "Trust this executable" / "Allow Launching" on this shortcut.'
fi
printf '%s\n' 'Alternatively, launch Touch Audio from the Applications menu (Audio & Video).'
