"""v1.3 backlight, auto-dim, power safety, and efficiency regressions."""
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import yaml

from touchplayer.brightness import BrightnessController, SysfsBacklight
from touchplayer.config import Config, StateStore
from touchplayer.library import Category, Entry, Library
from touchplayer.playback import SleepTimer


class Time:
    def __init__(self, current=0.0):
        self.now = current

    def __call__(self):
        return self.now


class FakeHardware:
    available = False
    current = 70

    def set(self, percent):
        raise OSError('No backlight')


def test_backward_compatible_defaults(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('web: {token: existing}\n')
    config = Config(path)
    assert config.data['display'] == {
        'auto_dim': True, 'idle_seconds': 60,
        'dim_percent': 40, 'backend': 'auto', 'device': ''}


@pytest.mark.parametrize('setting', [
    'idle_seconds: 1', 'idle_seconds: 86401', 'dim_percent: 0',
    'dim_percent: 101', 'backend: command', 'device: ../../etc',
])
def test_invalid_display_settings(tmp_path, setting):
    p = tmp_path / 'config.yaml'
    p.write_text('web: {token: existing}\ndisplay: {' + setting + '}\n')
    with pytest.raises(ValueError):
        Config(p)


def test_hardware_read_and_write(tmp_path):
    directory = tmp_path / 'rpi_dsi_backlight'
    directory.mkdir()
    (directory / 'max_brightness').write_text('255')
    (directory / 'brightness').write_text('178')
    device = SysfsBacklight(tmp_path)
    assert device.available and device.current == 70
    device.set(40)
    assert (directory / 'brightness').read_text() == '102'
    device.set(0)
    assert int((directory / 'brightness').read_text()) >= 1


def test_software_fallback_auto_dim_and_activity_restore():
    clock = Time(10)
    applied = []
    brightness = BrightnessController({'auto_dim': True, 'idle_seconds': 60, 'dim_percent': 40},
                                      applied.append, FakeHardware(), clock)
    assert brightness.backend == 'software'
    assert applied == [100]
    clock.now = 69.9
    brightness.tick()
    assert not brightness.dimmed
    clock.now = 70
    brightness.tick()
    assert brightness.dimmed and brightness.animating
    clock.now = 72
    brightness.tick()
    assert brightness.current == 40
    brightness.activity()
    clock.now = 73
    brightness.tick()
    assert brightness.current == 100 and not brightness.dimmed
    assert len(applied) < 10  # No repeated writes while idle.


def test_manual_toggle_40_and_previous_level():
    clock = Time(100)
    controller = BrightnessController({'auto_dim': False}, lambda _: None, FakeHardware(), clock)
    controller.set_level(75)
    assert controller.toggle_dim()
    clock.now = 101
    controller.tick()
    assert controller.current == 40
    assert not controller.toggle_dim()
    clock.now = 102
    controller.tick()
    assert controller.current == 75
    controller.set_level(30)
    assert not controller.toggle_dim()  # Must not brighten up to 40%.
    assert controller.current == 30


def test_auto_dim_does_not_override_lower_normal_level():
    clock = Time(0)
    controller = BrightnessController({'auto_dim': True, 'idle_seconds': 5, 'dim_percent': 40},
                                      lambda _: None, FakeHardware(), clock)
    controller.set_level(20)
    clock.now = 100
    controller.tick()
    assert not controller.dimmed and controller.current == 20


def test_save_state_only_when_changed(tmp_path):
    store = StateStore(str(tmp_path / 'state.yaml'))
    store.update(entry_id='A')
    first = store.path.stat().st_mtime_ns
    store.update(entry_id='A')
    assert store.path.stat().st_mtime_ns == first
    store.update(entry_id='B')
    assert yaml.safe_load(store.path.read_text())['entry_id'] == 'B'


def test_library_flattening_cached():
    library = Library(categories={'books': Category('Books', [Entry('one', '/tmp/a', 'a', 'Books')])})
    assert library.all_entries() is library.all_entries()
    assert library.all_entries()[0].id == 'one'


def test_ignored_delayed_sleep_tick_uses_original_deadline(monkeypatch):
    clock = Time(100)
    monkeypatch.setattr('touchplayer.playback.time.monotonic', clock)
    volume = [100]
    events = []
    timer = SleepTimer(lambda: volume[0], lambda v: volume.__setitem__(0, v), lambda: events.append('done'))
    timer.set(10)
    clock.now = 112  # Qt may be up to a few ticks late while doing other work.
    timer.tick()
    assert timer.fade_start == 110
    clock.now = 140
    timer.tick()
    assert events == ['done']


def test_new_icons_and_translation_keys():
    from touchplayer.i18n import Translator
    english = Translator('en')
    for key in ('screen_brightness', 'shutdown_confirm', 'auto_dim', 'auto_dim_delay',
                'auto_dim_target', 'brightness_backend', 'dim_toggle', 'system_controls',
                'sleep_active_short', 'sleep_fading_short'):
        assert key in english.translations and english.t(key, backend='software', time='1:10') != key
    for name in ('sun-dim', 'power', 'system', 'exit-app'):
        p = Path(__file__).resolve().parents[1] / 'assets' / (name + '.svg')
        assert ET.parse(p).getroot().tag.endswith('svg')
