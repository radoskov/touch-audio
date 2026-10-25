"""Regression tests for v1.2 source modes, snapshots, progress and repeat."""
from pathlib import Path
import threading
import time
import xml.etree.ElementTree as ET

import pytest
import yaml

from touchplayer.config import Config
from touchplayer.i18n import Translator
from touchplayer.library import load_snapshot, save_snapshot, scan
from touchplayer.playback import AudioPlayer
from touchplayer.scale import stylesheet, UiMetrics


def audio_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'test mp3 without tags')


def test_third_source_type_merges_multiple_explicit_category_paths(tmp_path):
    group = tmp_path / 'group'
    direct = tmp_path / 'old-direct'
    extra = tmp_path / 'explicit-other'
    audio_file(group / 'audiobooks' / 'A' / '01.mp3')
    audio_file(direct / 'B' / '02.mp3')
    audio_file(extra / 'C' / '03.mp3')
    cache = str(tmp_path / 'index.sqlite')
    observed = []
    lib = scan([str(group)], {'audiobooks': str(direct)}, cache,
               {'audiobooks': [str(direct), str(extra)]},
               lambda done, total, name: observed.append((done, total, name)))
    assert {x.folder_name for x in lib.category('audiobooks').entries} == {'A', 'B', 'C'}
    assert observed[0][:2] == (0, 0)  # discovery/indeterminate phase
    assert observed[-1][:2] == (4, 4) or observed[-1][:2] == (3, 3)
    assert [x[0] for x in observed[2:]] == list(range(1, observed[1][1] + 1))
    save_snapshot(lib, cache)
    restored = load_snapshot(cache)
    assert set(lib.by_id) == set(restored.by_id)
    assert [t.path for t in restored.category('audiobooks').entries[0].tracks] == [
        t.path for t in lib.category('audiobooks').entries[0].tracks]


def test_snapshot_missing_or_invalid(tmp_path):
    cache = str(tmp_path / 'cache.sqlite')
    assert not load_snapshot(cache).by_id
    Path(cache).with_suffix('.library.json').write_text('bad json')
    restored = load_snapshot(cache)
    assert not restored.by_id and restored.warnings
    Path(cache).with_suffix('.library.json').write_text('[]')
    restored = load_snapshot(cache)
    assert not restored.by_id and restored.warnings


def test_new_config_defaults_and_backward_compatibility(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('''
language: en
group_folders: []
direct_folders:
  audiobooks: ~/old
category_folders:
  audiobooks:
    - ~/new
  music: /mnt/albums
web:
  token: existing
metadata:
  folder_artist: false
''')
    config = Config(path)
    assert config.data['category_folders']['audiobooks'] == ['~/new']
    assert config.data['category_folders']['music'] == '/mnt/albums'
    assert config.data['browse_text_scale'] == 1.25
    assert config.data['scan_on_startup'] is True
    assert config.data['categoryless'] is False
    assert config.data['metadata']['folder_artist'] is False
    assert config.data['metadata']['file_artist'] is False
    assert config.data['metadata']['file_title'] is True
    assert yaml.safe_load(path.read_text())['web']['token'] == 'existing'
    config.data['categoryless'] = True
    config.data['scan_on_startup'] = False
    config.save()
    again = Config(path)
    assert again.data['categoryless'] and not again.data['scan_on_startup']


@pytest.mark.parametrize('source', [
    'category_folders: [not_a_mapping]',
    'category_folders: {audiobooks: 500}',
    'category_folders: {audiobooks: [a, 3]}',
])
def test_invalid_extra_sources_rejected(tmp_path, source):
    p = tmp_path / 'test.yaml'
    p.write_text('web:\n  token: existing\n' + source + '\n')
    with pytest.raises(ValueError):
        Config(p)


def mock_player():
    player = object.__new__(AudioPlayer)
    player.paths = ['a.mp3', 'b.mp3']
    player.index = 1
    player._end_event = threading.Event()
    player._ignore_end_until = time.monotonic() - 1
    player._status = 'playing'
    player._open_calls = []
    player._open_current = lambda autoplay: player._open_calls.append((player.index, autoplay))
    return player


def test_repeat_modes_and_manual_navigation():
    player = mock_player()
    player.set_repeat('file')
    player._end_event.set()
    player.poll()
    assert player.index == 1
    assert player._open_calls == [(1, True)]
    player.set_repeat('album')
    player._end_event.set()
    player.poll()
    assert player.index == 0 and player._open_calls[-1] == (0, True)
    player.index = 1
    player.set_repeat('off')
    player._end_event.set()
    player.poll()
    assert player._status == 'stopped'
    with pytest.raises(ValueError):
        player.set_repeat('random')
    player.set_repeat('album')
    player._open_calls.clear()
    player.next()
    assert player.index == 0 and player._open_calls == [(0, True)]


def test_new_translations_icons_and_scrollbar_sizes():
    tr = Translator('en')
    for key in ('category_folders', 'search', 'search_all', 'search_files',
                'scan_on_startup', 'metadata_file_artist', 'repeat_file',
                'repeat_album', 'working', 'scan_progress', 'browse_text_scale'):
        assert key in tr.translations and tr.translations[key] != key
    style = stylesheet(UiMetrics(1.5, 2.0))
    assert 'width:40px' in style or 'width:41px' in style
    assert 'scroll-up.svg' in style
    for name in ('repeat-file', 'repeat-album', 'search', 'scroll-up', 'scroll-down'):
        icon = Path(__file__).resolve().parents[1] / 'assets' / (name + '.svg')
        assert ET.parse(icon).getroot().tag.endswith('svg')
