"""VLC playback and a fade-before-poweroff sleep timer.

All methods must be called from the GUI (Qt) thread. In particular, libVLC event
callbacks only set a thread-safe flag, which the Qt poll timer consumes.
"""
from __future__ import annotations
import threading
import time
from typing import Callable


class AudioPlayer:
    def __init__(self, volume: int = 70):
        import vlc
        self.vlc = vlc
        self.instance = vlc.Instance('--no-video', '--quiet', '--no-media-library')
        self.player = self.instance.media_player_new()
        self.paths: list[str] = []
        self.index = -1
        self.repeat_mode = 'off'  # off, file, album
        self._end_event = threading.Event()
        self._ignore_end_until = 0.0
        self._status = 'stopped'
        self.volume = max(0, min(100, int(volume)))
        self.player.audio_set_volume(self.volume)
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached,
                                                   self._on_end)

    def _on_end(self, event):
        self._end_event.set()

    def load(self, paths: list[str], index: int = 0, autoplay: bool = True):
        self.paths = list(paths)
        self.index = min(max(index, 0), len(self.paths) - 1) if paths else -1
        if self.index >= 0:
            self._open_current(autoplay)
        else:
            self.stop()

    def _open_current(self, autoplay: bool = True):
        self._end_event.clear()
        self._ignore_end_until = time.monotonic() + 0.7
        self.player.stop()
        media = self.instance.media_new_path(self.paths[self.index])
        self.player.set_media(media)
        if autoplay:
            self.player.play()
            self.player.audio_set_volume(self.volume)
            self._status = 'playing'
        else:
            self._status = 'stopped'

    def play(self):
        if self.index < 0:
            if self.paths:
                self.index = 0
                self._open_current(True)
            return
        self._end_event.clear()
        if self._status == 'stopped':
            self._open_current(True)
        else:
            self.player.set_pause(0)
            self._status = 'playing'

    def pause(self):
        if self._status == 'playing':
            self.player.set_pause(1)
            self._status = 'paused'

    def toggle(self):
        if self._status == 'playing':
            self.pause()
        else:
            self.play()

    def stop(self):
        self._end_event.clear()
        self._ignore_end_until = time.monotonic() + 0.7
        self.player.stop()
        self._status = 'stopped'

    def set_repeat(self, mode: str):
        if mode not in ('off', 'file', 'album'):
            raise ValueError('Repeat mode must be off, file or album')
        self.repeat_mode = mode

    def next(self):
        if self.index >= 0 and self.index + 1 < len(self.paths):
            self.index += 1
            self._open_current(True)
        elif self.index >= 0 and self.paths and self.repeat_mode == 'album':
            self.index = 0
            self._open_current(True)

    def previous(self):
        if self.index < 0:
            return
        if self.position_seconds() > 4:
            self.seek(0)
        elif self.index > 0:
            self.index -= 1
            self._open_current(True)
        else:
            self.seek(0)

    def poll(self):
        if self._end_event.is_set() and time.monotonic() >= self._ignore_end_until:
            self._end_event.clear()
            if self.repeat_mode == 'file' and self.index >= 0:
                self._open_current(True)
            elif self.index >= 0 and (self.index + 1 < len(self.paths) or self.repeat_mode == 'album'):
                self.next()
            else:
                self._status = 'stopped'

    def set_volume(self, value: int):
        self.volume = max(0, min(100, int(value)))
        self.player.audio_set_volume(self.volume)

    def duration_seconds(self) -> float:
        return max(0, self.player.get_length()) / 1000.0

    def position_seconds(self) -> float:
        return max(0, self.player.get_time()) / 1000.0

    def seek(self, seconds: float):
        if self.index >= 0:
            self.player.set_time(max(0, int(seconds * 1000)))

    def state(self) -> dict:
        return {'status': self._status, 'volume': self.volume,
                'file_index': self.index, 'repeat_mode': self.repeat_mode, 'position': round(self.position_seconds(), 1),
                'duration': round(self.duration_seconds(), 1)}

    def close(self):
        self.stop()
        self.player.release()
        self.instance.release()


class SleepTimer:
    """Start a 30-second linear fade exactly when the requested delay expires."""
    FADE_SECONDS = 30.0

    def __init__(self, volume_getter: Callable[[], int],
                 volume_setter: Callable[[int], None], shutdown: Callable[[], None]):
        self.volume_getter = volume_getter
        self.volume_setter = volume_setter
        self.shutdown = shutdown
        self.deadline: float | None = None
        self.fade_start: float | None = None
        self.fade_volume = 0
        self.shutdown_called = False

    def set(self, delay_seconds: int):
        if delay_seconds <= 0:
            self.cancel()
            return
        if self.fade_start is not None:
            self.cancel()  # Restore volume when replacing an active fade.
        self.deadline = time.monotonic() + delay_seconds
        self.fade_start = None
        self.shutdown_called = False

    def cancel(self):
        if self.fade_start is not None and not self.shutdown_called:
            self.volume_setter(self.fade_volume)
        self.deadline = None
        self.fade_start = None
        self.shutdown_called = False

    def tick(self, now: float | None = None):
        now = time.monotonic() if now is None else now
        if self.deadline is None or self.shutdown_called:
            return
        if now < self.deadline:
            return
        if self.fade_start is None:
            self.fade_start = self.deadline
            self.fade_volume = self.volume_getter()
        elapsed = now - self.fade_start
        if elapsed >= self.FADE_SECONDS:
            self.volume_setter(0)
            self.shutdown_called = True
            self.deadline = None
            self.shutdown()
        else:
            self.volume_setter(round(self.fade_volume * (1 - elapsed / self.FADE_SECONDS)))

    def state(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        if self.deadline is None:
            return {'active': False, 'fading': False, 'remaining_seconds': 0}
        fade_seconds = 0 if self.fade_start is None else max(0, now - self.fade_start)
        remaining = max(0, (self.deadline - now) + self.FADE_SECONDS) if self.fade_start is None else max(0, self.FADE_SECONDS - fade_seconds)
        return {'active': True, 'fading': self.fade_start is not None,
                'remaining_seconds': int(remaining + 0.99)}
