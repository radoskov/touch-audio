from pathlib import Path
import os
import sqlite3
import tempfile

from touchplayer.config import Config, expand_path, load_yaml
from touchplayer.i18n import Translator
from touchplayer.library import scan
from touchplayer.playback import SleepTimer


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'not a real mp3: metadata fails gracefully')


def test_multi_source_categories_merge_and_search(tmp_path):
    root1, root2, direct = tmp_path / 'group1', tmp_path / 'group2', tmp_path / 'direct'
    touch(root1 / 'audiobooks' / 'Dune' / '01 Intro.mp3')
    touch(root2 / 'audiobooks' / 'Little Prince' / '02 Outro.mp3')
    touch(root2 / 'funny' / 'Jokes' / 'part 3.ogg')
    touch(direct / 'Bedtime' / '10 Sleep.mp3')
    touch(direct / 'Bedtime' / '2 Start.mp3')
    (direct / 'Bedtime' / 'cover.jpg').write_bytes(b'fake cover')
    cache = str(tmp_path / 'cache' / 'index.sqlite')
    library = scan([str(root1), str(root2)], {'audiobooks': str(direct)}, cache)
    assert set(library.categories) == {'audiobooks', 'funny'}
    assert len(library.category('audiobooks').entries) == 3
    assert len(library.category('funny').entries) == 1
    entry = next(e for e in library.category('audiobooks').entries if e.folder_name == 'Bedtime')
    assert [t.filename for t in entry.tracks] == ['2 Start.mp3', '10 Sleep.mp3']
    assert entry.cover.endswith('cover.jpg')
    matches = library.search('outro')
    assert len(matches) == 1 and matches[0]['type'] == 'track'
    again = scan([str(root1), str(root2)], {'audiobooks': str(direct)}, cache)
    assert set(again.by_id) == set(library.by_id)
    assert sqlite3.connect(cache).execute('SELECT COUNT(*) FROM tags').fetchone()[0] == 5


def test_duplicate_direct_and_group_path_not_duplicated(tmp_path):
    group = tmp_path / 'root'
    touch(group / 'music' / 'Record' / 'a.mp3')
    lib = scan([str(group)], {'music': str(group / 'music')}, str(tmp_path / 'db.sqlite'))
    assert len(lib.category('music').entries) == 1


def test_direct_audio_files_without_subfolders(tmp_path):
    album = tmp_path / 'single'
    touch(album / '1.mp3')
    touch(album / '2.mp3')
    lib = scan([], {'music': str(album)}, str(tmp_path / 'db.sqlite'))
    assert len(lib.category('music').entries) == 1
    assert len(lib.category('music').entries[0].tracks) == 2


def test_home_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert expand_path('~/audio') == tmp_path / 'audio'
    assert expand_path('$HOME/audio') == tmp_path / 'audio'


def test_config_generates_token_and_saves(tmp_path):
    path = tmp_path / 'settings.yaml'
    config = Config(path)
    assert len(config.data['web']['token']) >= 20
    assert load_yaml(path)['web']['token'] == config.data['web']['token']
    config.data['language'] = 'en'
    config.save()
    assert Config(path).data['web']['token'] == config.data['web']['token']


def test_translation_english_and_example():
    assert Translator('en').t('app_title') == 'Touch Audio'
    assert Translator('example').t('app_title') == 'Example Audio Player'
    assert Translator('example').t('sleep_off') == 'Sleep timer off'


def test_sleep_fade_and_shutdown(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('touchplayer.playback.time.monotonic', lambda: now[0])
    value = [80]
    actions = []
    timer = SleepTimer(lambda: value[0], lambda x: value.__setitem__(0, x), lambda: actions.append('shutdown'))
    timer.set(60)
    now[0] = 159
    timer.tick()
    assert value[0] == 80
    now[0] = 160
    timer.tick()
    assert timer.state()['fading']
    now[0] = 175
    timer.tick()
    assert value[0] == 40
    now[0] = 190
    timer.tick()
    assert value[0] == 0
    assert actions == ['shutdown']
    now[0] = 195
    timer.tick()
    assert actions == ['shutdown']


def test_cancel_during_fade_restores_volume(monkeypatch):
    now = [10.0]
    monkeypatch.setattr('touchplayer.playback.time.monotonic', lambda: now[0])
    value = [70]
    timer = SleepTimer(lambda: value[0], lambda x: value.__setitem__(0, x), lambda: None)
    timer.set(5)
    now[0] = 15
    timer.tick()
    now[0] = 30
    timer.tick()
    assert value[0] == 35
    timer.cancel()
    assert value[0] == 70
