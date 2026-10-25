#!/bin/sh
# Read-only: diagnose Linux/Raspberry Pi backlight availability and permissions.
set -eu
printf '%s\n' 'Touch Audio hardware-backlight diagnostic' '========================================'
printf 'User: %s\n' "$(id -un)"
printf 'Groups: %s\n' "$(id -nG)"
found=0
for dev in /sys/class/backlight/*; do
    [ -d "$dev" ] || continue
    found=1
    printf '\nDevice: %s\n' "${dev##*/}"
    for field in brightness actual_brightness max_brightness; do
        if [ -r "$dev/$field" ]; then
            printf '  %-20s %s\n' "$field" "$(cat "$dev/$field")"
        fi
    done
    if [ -w "$dev/brightness" ]; then
        printf '  Write permission: yes (hardware control should work)\n'
    else
        printf '  Write permission: no (the app will use software dimming)\n'
    fi
done
if [ "$found" -eq 0 ]; then
    printf '\nNo /sys/class/backlight device was found.\n'
    printf 'This is common for HDMI screens without a Linux backlight driver.\n'
fi
if command -v brightnessctl >/dev/null 2>&1; then
    printf '\nbrightnessctl is installed; list devices using: brightnessctl -l\n'
else
    printf '\nOptional Trixie packages: sudo apt install brightnessctl brightness-udev\n'
fi
printf '\nNo settings or permissions were changed by this script.\n'
