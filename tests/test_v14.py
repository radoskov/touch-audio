"""v1.4 regressions: comment-safe settings, launcher registration, GUI contracts."""
from pathlib import Path
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from ruamel.yaml import YAML

from touchplayer.config import Config

ROOT = Path(__file__).resolve().parent.parent


def test_config_save_preserves_comments_and_quoting(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('''# Personal notes: never delete
language: "en" # UI language
group_folders: # folders grouped by category
  - "~/music" # USB backup goes here
metadata:
  file_artist: false # keep track rows short
web:
  token: "a-set-secret" # don't lose this token
# Keep this trailing comment
''')
    settings = Config(config_path)
    settings.data['display']['idle_seconds'] = 90
    settings.data['language'] = 'cs'
    settings.save()
    content = config_path.read_text()
    for comment in ('# Personal notes: never delete', '# UI language',
                    '# folders grouped by category', '# USB backup goes here',
                    '# keep track rows short', '# don\'t lose this token',
                    '# Keep this trailing comment'):
        assert comment in content
    assert 'language: "cs"' in content
    assert YAML(typ='safe').load(content)['display']['idle_seconds'] == 90


def test_config_keeps_unused_custom_keys(tmp_path):
    file = tmp_path / 'config.yaml'
    file.write_text('''web: {token: existing}
# custom app notes
custom_future_key: "foo" # keep it
''')
    config = Config(file)
    config.data['volume'] = 42
    config.save()
    content = file.read_text()
    assert '# custom app notes' in content
    assert '# keep it' in content
    assert 'custom_future_key: "foo"' in content


def test_no_overwrite_if_ruamel_not_installed(monkeypatch, tmp_path):
    # Don't accidentally degrade to PyYAML on systems with missing dependencies.
    import builtins
    from touchplayer.config import save_config_yaml
    file = tmp_path / 'config.yaml'
    file.write_text('# preserve\nweb: {token: existing}\n')
    orig = builtins.__import__

    def fail_ruamel(name, *args, **kwargs):
        if name == 'ruamel.yaml':
            raise ImportError('unavailable for test')
        return orig(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fail_ruamel)
    with pytest.raises(RuntimeError, match='ruamel.yaml'):
        save_config_yaml(file, {'web': {'token': 'new'}})
    assert file.read_text().startswith('# preserve')


def test_application_menu_and_desktop_registration(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path),
               XDG_DATA_HOME=str(tmp_path / '.local' / 'share'),
               PATH='/usr/bin:/bin')
    result = subprocess.run([str(ROOT / 'create_desktop_icon.sh')],
                            check=True, env=env, text=True, capture_output=True)
    menu = tmp_path / '.local/share/applications/touch-audio.desktop'
    desktop = tmp_path / 'Desktop/touch-audio.desktop'
    for entry in (menu, desktop):
        assert entry.exists()
        assert '[Desktop Entry]' in entry.read_text()
        assert 'Type=Application' in entry.read_text()
        assert 'Terminal=false' in entry.read_text()
        assert 'Exec="' in entry.read_text()
        assert os.access(entry, os.X_OK)
    assert 'application-menu entry' in result.stdout


def test_options_clock_and_dialog_regressions_source_contract():
    source = (ROOT / 'touchplayer/ui.py').read_text()
    system_dialog = source.split('class SystemDialog(QDialog):')[1].split('class TouchListDialog')[0]
    assert 'self.window = window' not in system_dialog
    assert 'self.main_window = window' in system_dialog
    assert 'QWidget.window(obj)' in source
    assert 'QDateTime.currentDateTime()' in source
    assert 'self.tl.format_date(now.date().toPyDate())' in source
    assert "now.toString('HH:mm:ss')" in source
    assert 'class TouchSpinBox(QWidget)' in source
    assert source.count('TouchSpinBox(') >= 5
    for icon in ('plus.svg', 'minus.svg'):
        assert ET.parse(ROOT / 'assets' / icon).getroot().tag.endswith('svg')


def test_clock_scaling_is_relative_to_regular_text():
    from touchplayer.scale import UiMetrics, stylesheet
    normal = UiMetrics(1.5, 1.5)
    css = stylesheet(normal)
    assert f'QLabel#clock {{font-size:{round(normal.font(15) * 1.5)}px' in css
