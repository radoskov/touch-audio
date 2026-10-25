"""Low-cost display brightness controller, independent of the GUI.

/sys/class/backlight is the native Linux/DSI hardware path. If it is absent or
not writable, a GUI callback provides visual-only dimming (no backlight savings).
No root shell, sudo command, busy polling, or periodic subprocesses are used.
"""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable


def clamp(value: int | float) -> int:
    return min(100, max(10, round(float(value))))


class SysfsBacklight:
    """Pick a writable display backlight, preferring Pi DSI/lcd devices."""

    def __init__(self, root: Path = Path('/sys/class/backlight'), device: str = ''):
        self.path: Path | None = None
        self.maximum = 100
        self.current = 100
        if device and ('/' in device or device in ('.', '..')):
            raise ValueError('Backlight device must be a simple device name')
        paths = [root / device] if device else (list(root.iterdir()) if root.is_dir() else [])
        paths.sort(key=lambda p: (not any(s in p.name.lower() for s in ('dsi', 'rpi', 'lcd', 'backlight')), p.name))
        for path in paths:
            try:
                maximum = int((path / 'max_brightness').read_text().strip())
                value = int((path / 'brightness').read_text().strip())
                if maximum <= 0 or not os.access(path / 'brightness', os.W_OK):
                    continue
                self.path = path / 'brightness'
                self.maximum = maximum
                self.current = clamp(round(value * 100 / maximum))
                break
            except (OSError, ValueError):
                continue

    @property
    def available(self) -> bool:
        return self.path is not None

    def set(self, percent: int):
        if self.path is None:
            raise OSError('No writable hardware backlight')
        # Keep actual backlight safely above zero, even for unusual max values.
        raw = max(1, round(clamp(percent) * self.maximum / 100))
        self.path.write_text(str(raw), encoding='ascii')
        self.current = clamp(percent)


class BrightnessController:
    """Manual dim, inactivity dim, gradual animation, and activity restoration.

    All calls occur on the Qt thread. The callback receives percentages for the
    software overlay; hardware updates are skipped if the value is unchanged.
    """

    def __init__(self, config: dict, software_callback: Callable[[int], None],
                 hardware: SysfsBacklight | None = None, clock=time.monotonic):
        self.clock = clock
        self.software_callback = software_callback
        self.hardware = hardware or SysfsBacklight(device=str(config.get('device', '') or ''))
        preference = str(config.get('backend', 'auto')).lower()
        self.backend = 'hardware' if preference != 'software' and self.hardware.available else 'software'
        self.normal = self.hardware.current if self.backend == 'hardware' else 100
        self.current = self.normal
        self.auto_dim = bool(config.get('auto_dim', True))
        self.delay = max(5, int(config.get('idle_seconds', 60)))
        self.target = clamp(config.get('dim_percent', 40))
        self.dimmed = False
        self.last_activity = self.clock()
        self.fade_start = None
        self.fade_from = self.current
        self.fade_to = self.current
        self.fade_seconds = 1.5
        self._applied = None
        self._apply(self.current)

    def _apply(self, percent: int):
        percent = clamp(percent)
        if self._applied == percent:
            return
        self.current = percent
        if self.backend == 'hardware':
            try:
                self.hardware.set(percent)
                self.software_callback(100)
            except OSError:
                self.backend = 'software'
                self.software_callback(percent)
        else:
            self.software_callback(percent)
        self._applied = percent

    def _fade(self, value: int, duration: float = 1.5, now=None):
        self.fade_start = self.clock() if now is None else now
        self.fade_from = self.current
        self.fade_to = clamp(value)
        self.fade_seconds = max(0.01, duration)
        if self.fade_from == self.fade_to:
            self.fade_start = None

    @property
    def animating(self):
        return self.fade_start is not None

    def configure(self, config: dict):
        self.auto_dim = bool(config.get('auto_dim', True))
        self.delay = max(5, int(config.get('idle_seconds', 60)))
        self.target = clamp(config.get('dim_percent', 40))
        # Config changes restore brightness and restart the idle deadline.
        self.activity(force=True)

    def activity(self, now=None, force=False):
        now = self.clock() if now is None else now
        self.last_activity = now
        if self.dimmed or force:
            self.dimmed = False
            self._fade(self.normal, duration=0.45, now=now)

    def set_level(self, percent: int):
        self.normal = clamp(percent)
        self.last_activity = self.clock()
        self.dimmed = False
        self.fade_start = None
        self._apply(self.normal)

    def toggle_dim(self, now=None):
        now = self.clock() if now is None else now
        self.last_activity = now
        if self.dimmed:
            self.dimmed = False
            self._fade(self.normal, duration=0.35, now=now)
        elif self.normal > 40:
            self.dimmed = True
            self._fade(40, duration=0.35, now=now)
        return self.dimmed

    def tick(self, now=None):
        now = self.clock() if now is None else now
        if (self.auto_dim and not self.dimmed and now - self.last_activity >= self.delay
                and self.normal > self.target):
            self.dimmed = True
            self._fade(self.target, now=now)
        if self.fade_start is not None:
            amount = min(1.0, max(0.0, (now - self.fade_start) / self.fade_seconds))
            # Cubic ease-in/out is smooth at both ends, with no busy loop.
            smooth = amount * amount * (3 - 2 * amount)
            self._apply(round(self.fade_from + (self.fade_to - self.fade_from) * smooth))
            if amount >= 1.0:
                self.fade_start = None
                self._apply(self.fade_to)

    def state(self) -> dict:
        return {'percent': self.current, 'normal_percent': self.normal,
                'dimmed': self.dimmed, 'backend': self.backend,
                'auto_dim': self.auto_dim, 'idle_seconds': self.delay, 'dim_percent': self.target}
