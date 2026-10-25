"""Pure Python and shell integration checks; no Qt display needed."""
from pathlib import Path
import os
import subprocess
import xml.etree.ElementTree as ET

import pytest
import yaml

from touchplayer.config import Config
from touchplayer.scale import UiMetrics, stylesheet, validate_scale
from touchplayer.i18n import Translator


PROJECT = Path(__file__).resolve().parent.parent


def test_scaling_defaults_in_new_and_preexisting_yaml(tmp_path):
    current = Config(tmp_path / 'new.yaml')
    assert current.data['ui_scale'] == current.data['text_scale'] == 1.5
    old = tmp_path / 'old.yaml'
    old.write_text('language: en\ngroup_folders: []\ndirect_folders: {}\nweb:\n  token: existing-secret\n')
    loaded = Config(old)
    assert loaded.data['ui_scale'] == 1.5
    assert loaded.data['text_scale'] == 1.5
    assert loaded.data['web']['token'] == 'existing-secret'
    assert 'ui_scale' not in yaml.safe_load(old.read_text())  # no unexpected rewriting
    loaded.data['ui_scale'] = 1.3
    loaded.data['text_scale'] = 1.8
    loaded.save()
    assert Config(old).data['ui_scale'] == 1.3
    assert Config(old).data['text_scale'] == 1.8


def test_independent_scaling_and_translation():
    baseline = UiMetrics(1.0, 1.0)
    large = UiMetrics(1.5, 1.5)
    text_only = UiMetrics(1.0, 2.0)
    assert large.px(40) == 60
    assert large.font(20) == 30
    assert text_only.px(40) == baseline.px(40)
    assert text_only.font(20) > baseline.font(20)
    assert text_only.button_height >= text_only.font(15)
    assert f'font-size:{large.font(15)}px' in stylesheet(large)
    assert Translator('en').t('ui_scale') == 'UI / button size (%)'
    assert Translator('example').t('text_scale') == 'Text size (%)'


@pytest.mark.parametrize('bad', [-0.1, 0, 0.74, 2.01, 'bogus', None, float('nan'), float('inf')])
def test_invalid_scaling_rejected(bad):
    with pytest.raises(ValueError):
        validate_scale(bad)


def test_svg_icons_well_formed():
    for filename in (PROJECT / 'assets').glob('*.svg'):
        assert ET.parse(filename).getroot().tag.endswith('svg')
    assert (PROJECT / 'assets/arrow-left.svg').is_file()
    assert (PROJECT / 'assets/arrow-right.svg').is_file()


def test_desktop_launcher_and_autostart_roundtrip(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / '.config'))
    runner = PROJECT / 'autostart.sh'
    subprocess.run([str(runner), 'enable'], check=True, env=env, capture_output=True)
    desktop = tmp_path / '.config/autostart/touch-audio.desktop'
    assert desktop.exists()
    value = desktop.read_text()
    assert 'Exec="' in value
    assert 'X-TouchAudio-Launcher=1' in value
    assert 'Icon=' in value
    status = subprocess.run([str(runner), 'status'], check=True, env=env, capture_output=True, text=True)
    assert 'Enabled' in status.stdout
    subprocess.run([str(runner), 'disable'], check=True, env=env, capture_output=True)
    assert not desktop.exists()
    assert not (tmp_path / 'touch-audio.desktop').exists()


def test_autostart_refuses_to_erase_unrelated_file(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / '.config'))
    dest = tmp_path / '.config/autostart/touch-audio.desktop'
    dest.parent.mkdir(parents=True)
    dest.write_text('[Desktop Entry]\nName=Unrelated\n')
    result = subprocess.run([str(PROJECT / 'autostart.sh'), 'disable'], env=env, capture_output=True)
    assert result.returncode != 0
    assert dest.exists()
