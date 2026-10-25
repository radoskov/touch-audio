"""v1.4.2 date formatting, translations and repeat-mode indicators."""
from datetime import date, timedelta
from pathlib import Path
from string import Formatter

import yaml

from touchplayer.i18n import Translator
from touchplayer.playback import AudioPlayer

ROOT = Path(__file__).resolve().parent.parent


def _placeholders(text):
    return {name for _, name, _, _ in Formatter().parse(text) if name}


def test_czech_slovak_translations_complete_and_app_name_stays_original():
    reference = yaml.safe_load((ROOT / 'translations/en.yaml').read_text(encoding='utf-8'))
    for language in ('cs', 'sk'):
        translations = yaml.safe_load((ROOT / 'translations' / f'{language}.yaml').read_text(encoding='utf-8'))
        assert translations.keys() == reference.keys()
        assert translations['app_title'] == 'Touch Audio'
        for key in reference:
            assert isinstance(translations[key], str) and translations[key]
            assert _placeholders(translations[key]) == _placeholders(reference[key]), (language, key)
        assert Translator(language).t('app_title') == 'Touch Audio'
        assert language in Translator.available()


def test_date_brackets_day_month_and_weekday_names():
    expected = {
        'en': 'Sunday | 25. 10. [October] 2026',
        'cs': 'neděle | 25. 10. [říjen] 2026',
        'sk': 'nedeľa | 25. 10. [október] 2026',
    }
    for language, want in expected.items():
        assert Translator(language).format_date(date(2026, 10, 25)) == want


def test_all_weekdays_and_months_have_real_translations():
    for language in ('en', 'cs', 'sk'):
        tr = Translator(language)
        # 2026-10-26 is a Monday.
        days = [tr.format_date(date(2026, 10, 26) + timedelta(days=i)) for i in range(7)]
        assert len({day.split(' | ')[0] for day in days}) == 7
        months = [tr.format_date(date(2026, month, 1)) for month in range(1, 13)]
        assert len({item.split('[')[1].split(']')[0] for item in months}) == 12
        assert all(item.count('[') == item.count(']') == 1 for item in months)


def test_repeat_styles_persist_in_checked_hover_focus_and_release():
    from touchplayer.scale import UiMetrics, stylesheet
    qss = stylesheet(UiMetrics())
    assert 'QPushButton#repeatToggle:!checked' in qss
    for pseudo in (':checked', ':checked:focus', ':checked:hover', ':checked:pressed'):
        assert f'QPushButton#repeatToggle{pseudo}' in qss
    assert '#208642' in qss  # green, not the ordinary blue focus color
    ui = (ROOT / 'touchplayer/ui.py').read_text(encoding='utf-8')
    assert ui.count("setObjectName('repeatToggle')") == 2
    assert "mode = 'off' if self.audio.repeat_mode == requested else requested" in ui
    assert ui.count('self.update_repeat_buttons()') >= 3  # init, touch, LAN, language changes


def test_repeat_player_exclusive_toggle_and_remote_synced_if_qt_available():
    # Exercise the actual MainWindow method without initializing libVLC if Qt is available.
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import pytest
    pytest.importorskip('PyQt5')
    pytest.importorskip('flask')
    from PyQt5.QtWidgets import QApplication, QPushButton
    from touchplayer.ui import MainWindow
    app = QApplication.instance() or QApplication(['repeat-test'])

    class DummyAudio:
        repeat_mode = 'off'

        def set_repeat(self, mode):
            assert mode in ('file', 'album', 'off')
            self.repeat_mode = mode

    class DummyState:
        def update(self, **kwargs):
            self.last = kwargs

    class Dummy:
        audio = DummyAudio()
        state_store = DummyState()

        def __init__(self):
            self.repeat_file_btn = QPushButton()
            self.repeat_album_btn = QPushButton()
            for button in (self.repeat_file_btn, self.repeat_album_btn):
                button.setCheckable(True)

        def t(self, key):
            return key

        def update_repeat_buttons(self):
            MainWindow.update_repeat_buttons(self)

    test = Dummy()
    for requested, mode, file_active, album_active in (
        ('file', 'file', True, False),
        ('file', 'off', False, False),
        ('album', 'album', False, True),
        ('file', 'file', True, False),
        ('file', 'off', False, False),
    ):
        MainWindow.toggle_repeat(test, requested)
        assert test.audio.repeat_mode == mode
        assert test.repeat_file_btn.isChecked() is file_active
        assert test.repeat_album_btn.isChecked() is album_active
        assert test.state_store.last['repeat_mode'] == mode
