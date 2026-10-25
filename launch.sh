#!/bin/sh
# Always start from this project folder; makes desktop shortcuts independent of cwd.
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON=${TOUCH_AUDIO_PYTHON:-/usr/bin/python3}
STATE_DIR=${XDG_STATE_HOME:-"$HOME/.local/state"}/touch_audio_player
mkdir -p "$STATE_DIR"
exec "$PYTHON" "$APP_DIR/app.py" --config "$APP_DIR/config.yaml" "$@" >> "$STATE_DIR/launch.log" 2>&1
