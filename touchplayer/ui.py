"""Touch-friendly Qt interface and single-threaded controller for VLC actions."""
from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from functools import lru_cache
import time
import shutil
import subprocess
import threading

from PyQt5.QtCore import QObject, QDateTime, QEvent, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon, QKeyEvent, QPixmap, QImageReader
from PyQt5.QtWidgets import (
    QApplication, QAbstractItemView, QAbstractSpinBox, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QProgressBar, QScrollArea, QShortcut, QSizePolicy, QSlider, QSpinBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from .brightness import BrightnessController
from .config import Config, StateStore
from .i18n import Translator
from .library import Entry, Library, load_snapshot, save_snapshot, scan
from .playback import AudioPlayer, SleepTimer
from .web import WebServer, make_app
from .scale import UiMetrics, stylesheet, validate_scale

ASSETS = Path(__file__).resolve().parent.parent / 'assets'

def asset_icon(name: str) -> QIcon:
    """Crisp vector icons independent of the installed font."""
    return QIcon(str(ASSETS / (name + '.svg')))


def fit_dialog(dialog: QDialog, width: int, height: int, margin_x=28, margin_y=28):
    """Fit dialogs to the usable screen, including a 1280x600 desktop."""
    geometry = QApplication.primaryScreen().availableGeometry()
    dialog.resize(min(width, max(320, geometry.width() - margin_x)),
                  min(height, max(280, geometry.height() - margin_y)))


def scroll_tab(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setFrameShape(QFrame.NoFrame)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    area.setWidget(content)
    return area


def category_icon(name: str) -> QIcon:
    name = name.casefold()
    icon = ('book' if any(w in name for w in ('book', 'audio', 'story')) else
            'music' if any(w in name for w in ('music', 'song', 'album')) else
            'mask' if any(w in name for w in ('funny', 'comedy', 'humor', 'joke')) else
            'education' if any(w in name for w in ('education', 'learn', 'school', 'lesson')) else
            'folder')
    return QIcon(str(ASSETS / (icon + '.svg')))


def entry_icon(entry: Entry, size: int = 48) -> QIcon:
    if entry.cover:
        icon = cached_cover_icon(entry.cover, size)
        if not icon.isNull():
            return icon
    return category_icon(entry.category)


@lru_cache(maxsize=128)
def cached_cover_icon(path: str, size: int) -> QIcon:
    if path:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        orig = reader.size()
        if orig.isValid():
            orig.scale(size, size, Qt.KeepAspectRatio)
            reader.setScaledSize(orig)
        pix = QPixmap.fromImage(reader.read())
        if not pix.isNull():
            return QIcon(pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    return QIcon()


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
    return f'{seconds // 60}:{seconds % 60:02d}'


class TouchSpinBox(QWidget):
    """Large +/- step buttons around a normal spin box (works without a keyboard)."""

    def __init__(self, metrics: UiMetrics, translator, parent=None):
        super().__init__(parent)
        self.spin = QSpinBox(self)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setMinimumWidth(metrics.px(94))
        self.spin.setMinimumHeight(metrics.button_height)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(metrics.px(5))
        minus = QPushButton()
        minus.setIcon(asset_icon('minus'))
        minus.setToolTip(translator('decrease'))
        minus.setAccessibleName(translator('decrease'))
        minus.clicked.connect(self.spin.stepDown)
        plus = QPushButton()
        plus.setIcon(asset_icon('plus'))
        plus.setToolTip(translator('increase'))
        plus.setAccessibleName(translator('increase'))
        plus.clicked.connect(self.spin.stepUp)
        for button in (minus, plus):
            button.setMinimumSize(metrics.button_height, metrics.button_height)
            button.setIconSize(QSize(metrics.px(25), metrics.px(25)))
        row.addWidget(minus)
        row.addWidget(self.spin, 1)
        row.addWidget(plus)
        self.setFocusProxy(self.spin)

    def setRange(self, minimum, maximum):
        self.spin.setRange(minimum, maximum)

    def setValue(self, value):
        self.spin.setValue(value)

    def value(self):
        return self.spin.value()

    def setSingleStep(self, step):
        self.spin.setSingleStep(step)

    def setSuffix(self, suffix):
        self.spin.setSuffix(suffix)


class OptionsDialog(QDialog):
    """All settings, including additional category sources and display preferences."""

    def __init__(self, config: Config, translator: Translator, parent=None):
        super().__init__(parent)
        self.config = config
        self.t = translator.t
        self.metrics = parent.metrics if parent is not None else UiMetrics(config.data['ui_scale'], config.data['text_scale'])
        m = self.metrics
        self.setObjectName('settingsDialog')
        # Fonts in the settings panel get their own small boost; with 200% text
        # scaling this remains legible without imposing larger global controls.
        settings_font = round(m.font(15) * 1.17)
        self.setStyleSheet(stylesheet(m) + f"""
QDialog#settingsDialog QLabel, QDialog#settingsDialog QCheckBox,
QDialog#settingsDialog QLineEdit, QDialog#settingsDialog QPlainTextEdit,
QDialog#settingsDialog QComboBox, QDialog#settingsDialog QSpinBox,
QDialog#settingsDialog QTabBar::tab, QDialog#settingsDialog QPushButton,
QDialog#settingsDialog QTableWidget {{font-size:{settings_font}px;}}
""")
        self.setWindowTitle(self.t('options_title'))
        fit_dialog(self, max(1160, m.px(740)), max(760, m.px(530)), 12, 12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(m.px(9), m.px(9), m.px(9), m.px(9))
        tabs = QTabWidget()
        layout.addWidget(tabs)

        sources = QWidget()
        source_layout = QVBoxLayout(sources)
        source_layout.addWidget(QLabel(self.t('group_folders')))
        self.groups = QPlainTextEdit('\n'.join(map(str, config.data.get('group_folders', []))))
        self.groups.setMinimumHeight(m.px(85))
        source_layout.addWidget(self.groups)
        source_layout.addWidget(QLabel(self.t('direct_folders')))
        self.direct = self._source_table()
        for cat, folder in config.data.get('direct_folders', {}).items():
            self.add_row(self.direct, str(cat), str(folder))
        source_layout.addWidget(self.direct)
        source_layout.addLayout(self._source_buttons(self.direct))
        source_layout.addWidget(QLabel(self.t('category_folders')))
        self.category_folders = self._source_table()
        for cat, paths in config.data.get('category_folders', {}).items():
            for path in ([paths] if isinstance(paths, str) else paths):
                self.add_row(self.category_folders, str(cat), str(path))
        source_layout.addWidget(self.category_folders)
        source_layout.addLayout(self._source_buttons(self.category_folders))
        tabs.addTab(scroll_tab(sources), self.t('sources_tab'))

        display = QWidget()
        display_form = QFormLayout(display)
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.addItems(Translator.available())
        self.language.setCurrentText(str(config.data.get('language', 'en')))
        display_form.addRow(self.t('language'), self.language)
        self.fullscreen = QCheckBox(self.t('start_fullscreen'))
        self.fullscreen.setChecked(bool(config.data.get('fullscreen', True)))
        display_form.addRow(self.fullscreen)
        self.ui_scale = self._percent(config.data.get('ui_scale', 1.5))
        display_form.addRow(self.t('ui_scale'), self.ui_scale)
        self.text_scale = self._percent(config.data.get('text_scale', 1.5))
        display_form.addRow(self.t('text_scale'), self.text_scale)
        self.browse_text_scale = self._percent(config.data.get('browse_text_scale', 1.25))
        display_form.addRow(self.t('browse_text_scale'), self.browse_text_scale)
        display_options = config.data['display']
        self.auto_dim = QCheckBox(self.t('auto_dim'))
        self.auto_dim.setChecked(bool(display_options.get('auto_dim', True)))
        display_form.addRow(self.auto_dim)
        self.idle_seconds = TouchSpinBox(m, self.t)
        self.idle_seconds.setRange(5, 86400)
        self.idle_seconds.setSuffix(' s')
        self.idle_seconds.setValue(int(display_options.get('idle_seconds', 60)))
        display_form.addRow(self.t('auto_dim_delay'), self.idle_seconds)
        self.dim_percent = TouchSpinBox(m, self.t)
        self.dim_percent.setRange(10, 100)
        self.dim_percent.setSuffix('%')
        self.dim_percent.setValue(int(display_options.get('dim_percent', 40)))
        display_form.addRow(self.t('auto_dim_target'), self.dim_percent)
        self.brightness_backend = QComboBox()
        self.brightness_backend.addItem(self.t('brightness_auto'), 'auto')
        self.brightness_backend.addItem(self.t('brightness_hardware'), 'hardware')
        self.brightness_backend.addItem(self.t('brightness_software'), 'software')
        selection = self.brightness_backend.findData(display_options.get('backend', 'auto'))
        self.brightness_backend.setCurrentIndex(max(0, selection))
        display_form.addRow(self.t('brightness_backend'), self.brightness_backend)
        self.backlight_device = QLineEdit(str(display_options.get('device', '')))
        self.backlight_device.setPlaceholderText(self.t('backlight_device_hint'))
        display_form.addRow(self.t('backlight_device'), self.backlight_device)

        hint = QLabel(self.t('scale_hint'))
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        display_form.addRow(hint)
        self.categoryless = QCheckBox(self.t('categoryless'))
        self.categoryless.setChecked(config.data.get('categoryless', False))
        display_form.addRow(self.categoryless)
        self.scan_on_startup = QCheckBox(self.t('scan_on_startup'))
        self.scan_on_startup.setChecked(config.data.get('scan_on_startup', True))
        display_form.addRow(self.scan_on_startup)
        tabs.addTab(scroll_tab(display), self.t('display_tab'))

        metadata = QWidget()
        meta_layout = QVBoxLayout(metadata)
        self.metadata_checks = {}
        for key in ('folder_name', 'folder_album', 'folder_artist',
                    'file_name', 'file_title', 'file_artist'):
            check = QCheckBox(self.t('metadata_' + key))
            check.setChecked(config.data.get('metadata', {}).get(key, key != 'file_artist'))
            meta_layout.addWidget(check)
            self.metadata_checks[key] = check
        meta_layout.addStretch(1)
        tabs.addTab(scroll_tab(metadata), self.t('metadata_tab'))

        server = QWidget()
        server_form = QFormLayout(server)
        web = config.data['web']
        self.server_enabled = QCheckBox(self.t('web_enabled'))
        self.server_enabled.setChecked(bool(web.get('enabled', True)))
        server_form.addRow(self.server_enabled)
        self.host = QLineEdit(str(web.get('host', '0.0.0.0')))
        server_form.addRow(self.t('web_host'), self.host)
        self.port = TouchSpinBox(m, self.t)
        self.port.setRange(1024, 65535)
        self.port.setValue(int(web.get('port', 8765)))
        server_form.addRow(self.t('web_port'), self.port)
        self.token = QLineEdit(str(web.get('token', '')))
        self.token.setEchoMode(QLineEdit.Password)
        server_form.addRow(self.t('web_token'), self.token)
        show = QCheckBox(self.t('show_token'))
        show.toggled.connect(lambda yes: self.token.setEchoMode(QLineEdit.Normal if yes else QLineEdit.Password))
        server_form.addRow(show)
        tabs.addTab(scroll_tab(server), self.t('server_tab'))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(self.t('save'))
        buttons.button(QDialogButtonBox.Cancel).setText(self.t('cancel'))
        for button in buttons.buttons():
            button.setMinimumHeight(m.button_height)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _source_table(self):
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels([self.t('categories'), self.t('folder')])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setMinimumHeight(self.metrics.px(135))
        return table

    def _source_buttons(self, table):
        row = QHBoxLayout()
        add = QPushButton(self.t('add_row'))
        add.clicked.connect(lambda: self.add_row(table, '', ''))
        remove = QPushButton(self.t('remove_row'))
        remove.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        return row

    @staticmethod
    def add_row(table, name, folder):
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(name))
        table.setItem(row, 1, QTableWidgetItem(folder))

    def _percent(self, value):
        widget = TouchSpinBox(self.metrics, self.t)
        widget.setRange(75, 200)
        widget.setSingleStep(10)
        widget.setSuffix('%')
        widget.setValue(round(value * 100))
        return widget

    @staticmethod
    def _pairs(table):
        pairs = []
        for row in range(table.rowCount()):
            category = (table.item(row, 0).text() if table.item(row, 0) else '').strip()
            folder = (table.item(row, 1).text() if table.item(row, 1) else '').strip()
            if category and folder:
                pairs.append((category, folder))
            elif category or folder:
                raise ValueError('Every source entry requires both a category name and a path')
        return pairs

    def result_data(self):
        data = dict(self.config.data)
        data['group_folders'] = [line.strip() for line in self.groups.toPlainText().splitlines() if line.strip()]
        data['direct_folders'] = dict(self._pairs(self.direct))
        extra = {}
        for category, path in self._pairs(self.category_folders):
            extra.setdefault(category, []).append(path)
        data['category_folders'] = extra
        data['language'] = self.language.currentText().strip()
        Translator(data['language'])
        data['fullscreen'] = self.fullscreen.isChecked()
        for key in ('ui_scale', 'text_scale', 'browse_text_scale'):
            data[key] = validate_scale(getattr(self, key).value() / 100, key)
        data['categoryless'] = self.categoryless.isChecked()
        data['scan_on_startup'] = self.scan_on_startup.isChecked()
        data['display'] = {
            'auto_dim': self.auto_dim.isChecked(),
            'idle_seconds': self.idle_seconds.value(),
            'dim_percent': self.dim_percent.value(),
            'backend': self.brightness_backend.currentData(),
            'device': self.backlight_device.text().strip(),
        }
        if '/' in data['display']['device'] or data['display']['device'] in ('.', '..'):
            raise ValueError('Backlight device must be a name, not a path')
        data['metadata'] = {key: checkbox.isChecked() for key, checkbox in self.metadata_checks.items()}
        token = self.token.text().strip()
        if not token:
            raise ValueError('LAN access token cannot be empty')
        data['web'] = {'enabled': self.server_enabled.isChecked(),
                       'host': self.host.text().strip(), 'port': self.port.value(), 'token': token}
        if not data['web']['host']:
            raise ValueError('Listen address cannot be empty')
        return data


class SystemDialog(QDialog):
    """Large, clearly separated system actions for a touchscreen."""

    def __init__(self, window):
        super().__init__(window)
        self.main_window = window
        self.t = window.t
        m = window.metrics
        self.setWindowTitle(self.t('system_controls'))
        self.setStyleSheet(stylesheet(m))
        fit_dialog(self, m.px(480), m.px(365))
        outer = QVBoxLayout(self)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setSpacing(m.px(12))
        outer.addWidget(scroll_tab(content), 1)
        layout.addWidget(QLabel(self.t('screen_brightness')))
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(10, 100)
        self.slider.setValue(window.brightness.normal)
        self.slider.setMinimumHeight(m.button_height)
        self.value = QLabel(f'{self.slider.value()}%')
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        layout.addLayout(row)
        self.backend = QLabel(window.t('brightness_mode', backend=window.t('brightness_' + window.brightness.backend)))
        self.backend.setObjectName('muted')
        self.backend.setWordWrap(True)
        layout.addWidget(self.backend)
        self._pending_brightness = QTimer(self)
        self._pending_brightness.setSingleShot(True)
        self._pending_brightness.timeout.connect(self._apply_brightness)
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(self._apply_brightness)
        close_app = QPushButton(self.t('close_app'))
        close_app.setIcon(asset_icon('exit-app'))
        close_app.setIconSize(QSize(m.px(30), m.px(30)))
        close_app.setMinimumHeight(m.primary_height)
        close_app.clicked.connect(self._close_application)
        layout.addWidget(close_app)
        layout.addStretch(1)
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        outer.addWidget(separator)
        shutdown = QPushButton(self.t('shutdown_pc'))
        shutdown.setIcon(asset_icon('power'))
        shutdown.setIconSize(QSize(m.px(30), m.px(30)))
        shutdown.setObjectName('danger')
        shutdown.setMinimumHeight(m.primary_height)
        shutdown.clicked.connect(self._confirm_shutdown)
        outer.addWidget(shutdown)
        cancel = QPushButton(self.t('cancel'))
        cancel.setMinimumHeight(m.button_height)
        cancel.clicked.connect(self.reject)
        outer.addWidget(cancel)

    def _slider_changed(self, percent):
        self.value.setText(f'{percent}%')
        self._pending_brightness.start(75)  # Coalesce slider-move events.

    def _apply_brightness(self):
        self._pending_brightness.stop()
        self.main_window.set_brightness(self.slider.value())
        self.backend.setText(self.t('brightness_mode', backend=self.t('brightness_' + self.main_window.brightness.backend)))

    def _close_application(self):
        self.accept()
        QTimer.singleShot(0, self.main_window.close)

    def _confirm_shutdown(self):
        if self.main_window.confirm_shutdown():
            self.accept()


class TouchListDialog(QDialog):
    """Reusable, touch-scrollable, asynchronously populated full-height list."""

    def __init__(self, translator, parent, title, width=980):
        super().__init__(parent)
        self.t = translator.t
        self.metrics = parent.metrics
        self.dialog_scale = float(parent.config.data.get('browse_text_scale', 1.25))
        m = self.metrics
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setStyleSheet(stylesheet(m))
        # Frameless: all but a slim display margin remains available at 1280x600.
        fit_dialog(self, max(width, m.px(660)), 9999, margin_x=16, margin_y=8)
        self.list_font_size = max(m.font(15), round(m.font(15) * self.dialog_scale))
        self.row_icon_size = max(m.px(62), self.list_font_size * 2 + m.px(6))
        self.row_height = max(self.row_icon_size + m.px(14), self.list_font_size * 2 + m.px(28))
        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(m.px(9), m.px(7), m.px(9), m.px(7))
        self.heading = QLabel(title)
        self.heading.setObjectName('heading')
        self.layout_main.addWidget(self.heading)
        self.list = QListWidget()
        self.list.setStyleSheet(f'QListWidget {{font-size:{self.list_font_size}px}}')
        self.list.setIconSize(QSize(self.row_icon_size, self.row_icon_size))
        self.list.setSpacing(m.px(3))
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        try:
            from PyQt5.QtWidgets import QScroller
            QScroller.grabGesture(self.list.viewport(), QScroller.LeftMouseButtonGesture)
        except Exception:
            pass
        self.working = QProgressBar()
        self.working.setRange(0, 0)
        self.working.setFormat(self.t('working'))
        self.working.setTextVisible(True)
        self.layout_main.addWidget(self.working)
        self.layout_main.addWidget(self.list, 1)
        self._records = []
        self._next_record = 0
        self._generation = 0
        self._populate_timer = QTimer(self)
        self._populate_timer.setSingleShot(True)
        self._populate_timer.timeout.connect(self._add_batch)

    def begin_population(self, records):
        self._populate_timer.stop()
        self._records = records
        self._next_record = 0
        self._generation += 1
        self.list.clear()
        self.working.show()
        # Paint the busy indicator before loading cover thumbnails.
        self._populate_timer.start(45)

    def _add_batch(self):
        end = min(self._next_record + 12, len(self._records))
        for index in range(self._next_record, end):
            text, icon, payload = self._records[index]
            if isinstance(icon, Entry):
                icon = entry_icon(icon, self.row_icon_size)
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, payload)
            item.setSizeHint(QSize(0, self.row_height))
            self.list.addItem(item)
        self._next_record = end
        if end < len(self._records):
            self._populate_timer.start(0)
        else:
            self.working.hide()
            if self.list.count():
                self.list.setCurrentRow(0)


class EntryBrowser(TouchListDialog):
    def __init__(self, entries: list[Entry], translator: Translator, parent=None):
        super().__init__(translator, parent, translator.t('browse_title'), 985)
        self.entries = entries
        self.selected_id = None
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.t('search_placeholder'))
        self.filter.setMinimumHeight(self.metrics.button_height)
        self.layout_main.insertWidget(1, self.filter)
        self.filter.textChanged.connect(self.populate)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.t('open_entry'))
        for button in buttons.buttons():
            button.setMinimumHeight(self.metrics.button_height)
        buttons.accepted.connect(self.pick)
        buttons.rejected.connect(self.reject)
        self.layout_main.addWidget(buttons)
        self.list.itemDoubleClicked.connect(lambda _: self.pick())
        QTimer.singleShot(10, self.populate)

    def populate(self, *_):
        terms = self.filter.text().casefold().split()
        records = []
        for entry in self.entries:
            haystack = ' '.join((entry.folder_name, entry.album_title, entry.artist, entry.category)).casefold()
            if all(term in haystack for term in terms):
                title = entry.folder_name
                detail = entry.album_title or entry.artist or entry.category
                records.append((f'{title}\n{detail}', entry, entry.id))
        self.begin_population(records)

    def pick(self):
        if self.list.currentItem():
            self.selected_id = self.list.currentItem().data(Qt.UserRole)
            self.accept()


class CategoryBrowser(TouchListDialog):
    def __init__(self, library: Library, translator: Translator, parent=None):
        super().__init__(translator, parent, translator.t('select_category'), 860)
        self.selected_key = None
        self.list.itemClicked.connect(lambda _: self.pick())
        self.list.itemActivated.connect(lambda _: self.pick())
        self.close_button = QPushButton(self.t('cancel'))
        self.close_button.setMinimumHeight(self.metrics.button_height)
        self.close_button.clicked.connect(self.reject)
        self.layout_main.addWidget(self.close_button)
        records = []
        for key, cat in sorted(library.categories.items()):
            description = f'{len(cat.entries)} {self.t("entries")}, {sum(len(e.tracks) for e in cat.entries)} {self.t("tracks")}'
            records.append((f'{cat.name}\n{description}', category_icon(cat.name), key))
        QTimer.singleShot(10, lambda: self.begin_population(records))

    def pick(self):
        if self.list.currentItem():
            self.selected_key = self.list.currentItem().data(Qt.UserRole)
            self.accept()


class SearchDialog(TouchListDialog):
    """Global album search with category-only and file-only switches."""

    def __init__(self, library: Library, current_category: str, translator: Translator, parent=None):
        super().__init__(translator, parent, translator.t('search'), 985)
        self.library = library
        self.category = current_category.casefold()
        self.selected_id = None
        self.selected_track = None
        self.query = QLineEdit()
        self.query.setPlaceholderText(self.t('search_placeholder'))
        self.query.setMinimumHeight(self.metrics.button_height)
        self.layout_main.insertWidget(1, self.query)
        mode_layout = QHBoxLayout()
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        for key in ('search_all', 'search_category', 'search_files'):
            button = QPushButton(self.t(key))
            button.setCheckable(True)
            button.setMinimumHeight(self.metrics.button_height)
            button.setProperty('mode', key)
            self.mode_buttons.addButton(button)
            mode_layout.addWidget(button)
            if key == 'search_all':
                button.setChecked(True)
            button.clicked.connect(self.populate)
        self.layout_main.insertLayout(2, mode_layout)
        self.query.textChanged.connect(self.populate)
        self.list.itemClicked.connect(lambda _: self.pick())
        self.list.itemActivated.connect(lambda _: self.pick())
        self.close_button = QPushButton(self.t('cancel'))
        self.close_button.setMinimumHeight(self.metrics.button_height)
        self.close_button.clicked.connect(self.reject)
        self.layout_main.addWidget(self.close_button)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        QTimer.singleShot(10, self.populate)

    def populate(self, *_):
        self._search_timer.start(120)

    def _do_search(self):
        button = self.mode_buttons.checkedButton()
        mode = button.property('mode') if button else 'search_all'
        terms = self.query.text().casefold().split()
        records = []
        for entry in self.library.all_entries():
            if mode == 'search_category' and entry.category.casefold() != self.category:
                continue
            if mode != 'search_files':
                text = ' '.join((entry.folder_name, entry.album_title, entry.artist, entry.category)).casefold()
                if all(term in text for term in terms):
                    records.append((f'{entry.folder_name}\n{entry.album_title or entry.category}',
                                    entry, (entry.id, None)))
            else:
                for index, track in enumerate(entry.tracks):
                    text = ' '.join((track.relative_path, track.title, track.artist,
                                     track.album, entry.folder_name, entry.album_title)).casefold()
                    if all(term in text for term in terms):
                        records.append((f'{track.relative_path}\n{track.title or entry.folder_name}',
                                        entry, (entry.id, index)))
        self.begin_population(records)

    def pick(self):
        if self.list.currentItem():
            self.selected_id, self.selected_track = self.list.currentItem().data(Qt.UserRole)
            self.accept()


class ButtonNavigationFilter(QObject):
    """Let arrows traverse buttons while preserving native list/text navigation."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.KeyPress and isinstance(obj, QPushButton)
                and obj.window() is self.window and event.modifiers() == Qt.NoModifier):
            if event.key() in (Qt.Key_Right, Qt.Key_Down):
                self.window.focusNextPrevChild(True)
                return True
            if event.key() in (Qt.Key_Left, Qt.Key_Up):
                self.window.focusNextPrevChild(False)
                return True
        return False


class ScreenActivityFilter(QObject):
    """Global UI event filter; does not poll /dev/input or wake on timers."""

    _ACTIVITY = {QEvent.MouseButtonPress, QEvent.Wheel, QEvent.TouchBegin,
                 QEvent.KeyPress, QEvent.TabletPress, QEvent.MouseMove}

    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() in self._ACTIVITY and isinstance(obj, QWidget):
            # Ignore input sent to other applications/windows.
            try:
                owner = QWidget.window(obj)
                is_ours = owner is self.window or (isinstance(owner, QDialog) and owner.parent() is self.window)
                if is_ours and (obj is not self.window.dim_button or event.type() == QEvent.MouseMove):
                    self.window.screen_activity()
            except RuntimeError:
                # Qt can deliver the final event during widget destruction.
                pass
        return False


class CommandBridge(QObject):
    requested = pyqtSignal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.requested.connect(self.process)

    @pyqtSlot(object, object)
    def process(self, command, future):
        try:
            future.set_result(self.window.handle_command(command))
        except Exception as exc:
            future.set_exception(exc)

    def call(self, command):
        future = Future()
        self.requested.emit(command, future)
        return future.result(timeout=8)


class MainWindow(QMainWindow):
    scan_finished = pyqtSignal(object)
    scan_progress = pyqtSignal(int, int, str)
    shutdown_error = pyqtSignal(str)

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.state_store = StateStore(config.data['state_file'])
        self.tl = Translator(config.data.get('language', 'en'))
        self.t = self.tl.t
        self.library = (load_snapshot(str(config.data['cache_db']))
                        if not config.data.get('scan_on_startup', True) else Library())
        self.current_category = str(self.state_store.data.get('category', ''))
        self.current_entry_id = str(self.state_store.data.get('entry_id', ''))
        self.audio = AudioPlayer(int(self.state_store.data.get('volume', config.data['volume'])))
        self.audio.set_repeat(self.state_store.data.get('repeat_mode', 'off'))
        self.sleep = SleepTimer(lambda: self.audio.volume, self._set_volume, self._poweroff)
        self.scanning = False
        self.rescan_pending = False
        self.webserver = None
        self._web_error_seen = False
        self.build_ui()
        self.dim_overlay = QWidget(self.centralWidget())
        self.dim_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.dim_overlay.setGeometry(self.centralWidget().rect())
        self.dim_overlay.hide()
        # Separate from the screen-brightness overlay: dialogs must shade the
        # inactive player even when hardware brightness is available. A plain
        # widget is inexpensive and does not consume touch/mouse events.
        self.modal_overlay = QWidget(self.centralWidget())
        self.modal_overlay.setObjectName('modalBackdrop')
        self.modal_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.modal_overlay.setFocusPolicy(Qt.NoFocus)
        self.modal_overlay.setStyleSheet('QWidget#modalBackdrop { background-color: rgba(0, 0, 0, 84); }')
        self.modal_overlay.setGeometry(self.centralWidget().rect())
        self.modal_overlay.hide()
        self._modal_depth = 0
        self.brightness = BrightnessController(self.config.data['display'], self._software_dim)
        self.bright_timer = QTimer(self)
        self.bright_timer.timeout.connect(self.brightness_tick)
        self.bright_timer.start(1000)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()
        self.activity_filter = ScreenActivityFilter(self)
        QApplication.instance().installEventFilter(self.activity_filter)
        self.navigation_filter = ButtonNavigationFilter(self)
        QApplication.instance().installEventFilter(self.navigation_filter)
        self.bridge = CommandBridge(self)
        self.scan_finished.connect(self.on_scan_finished)
        self.scan_progress.connect(self.on_scan_progress)
        self.shutdown_error.connect(self._show_shutdown_error)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.tick)
        self.poll_timer.start(1000)
        self.start_server()
        if self.config.data.get('scan_on_startup', True):
            self.refresh_library()
        else:
            self.on_scan_finished(self.library)  # Retain cached index until Refresh is pressed.
            self.status_label.setText(self.t('scan_skipped'))

    def build_ui(self):
        self.metrics = UiMetrics(self.config.data['ui_scale'], self.config.data['text_scale'])
        self.setWindowTitle(self.t('app_title'))
        self.setWindowIcon(asset_icon('app'))
        # Never demand a logical window larger than the actual touchscreen.
        self.setMinimumSize(480, 280)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        self.root_layout = layout

        clock_row = QHBoxLayout()
        self.clock_row = clock_row
        self.date_label = QLabel()
        self.date_label.setObjectName('clock')
        self.date_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.time_label = QLabel()
        self.time_label.setObjectName('clock')
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        clock_row.addWidget(self.date_label, 1)
        clock_row.addWidget(self.time_label, 0)
        layout.addLayout(clock_row)

        header = QHBoxLayout()
        self.header_layout = header
        self.dim_button = QPushButton()
        self.dim_button.setIcon(asset_icon('sun-dim'))
        self.dim_button.setToolTip(self.t('dim_toggle'))
        self.dim_button.setAccessibleName(self.t('dim_toggle'))
        self.dim_button.clicked.connect(self.toggle_dim)
        header.addWidget(self.dim_button)
        self.brand = QLabel(self.t('app_title'))
        self.brand.setObjectName('heading')
        header.addWidget(self.brand)
        header.addStretch(1)
        self.category_button = QPushButton(self.t('categories'))
        self.category_button.clicked.connect(self.open_categories)
        header.addWidget(self.category_button)
        self.refresh_button = QPushButton(self.t('refresh'))
        self.refresh_button.setIcon(asset_icon('refresh'))
        self.refresh_button.clicked.connect(self.refresh_library)
        header.addWidget(self.refresh_button)
        self.fullscreen_button = QPushButton(self.t('fullscreen'))
        self.fullscreen_button.setIcon(asset_icon('fullscreen'))
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        header.addWidget(self.fullscreen_button)
        self.options_button = QPushButton(self.t('options'))
        self.options_button.setIcon(asset_icon('options'))
        self.options_button.clicked.connect(self.show_options)
        header.addWidget(self.options_button)
        self.system_button = QPushButton()
        self.system_button.setIcon(asset_icon('system'))
        self.system_button.setToolTip(self.t('system_controls'))
        self.system_button.setAccessibleName(self.t('system_controls'))
        self.system_button.clicked.connect(self.system_dialog)
        header.addWidget(self.system_button)
        layout.addLayout(header)

        panes = QSplitter(Qt.Horizontal)
        panes.setChildrenCollapsible(False)
        self.panes = panes
        layout.addWidget(panes, 1)
        left = QFrame()
        left.setObjectName('panel')
        left_l = QVBoxLayout(left)
        self.left_layout = left_l

        nav = QHBoxLayout()
        self.left_arrow = QPushButton()
        self.left_arrow.setIcon(asset_icon('arrow-left'))
        self.left_arrow.setToolTip(self.t('previous_entry'))
        self.left_arrow.setAccessibleName(self.t('previous_entry'))
        self.left_arrow.clicked.connect(lambda: self.advance_entry(-1))
        nav.addWidget(self.left_arrow)
        self.entry_label = QLabel('—')
        self.entry_label.setAlignment(Qt.AlignCenter)
        self.entry_label.setWordWrap(True)
        self.entry_label.setObjectName('heading')
        nav.addWidget(self.entry_label, 1)
        self.right_arrow = QPushButton()
        self.right_arrow.setIcon(asset_icon('arrow-right'))
        self.right_arrow.setToolTip(self.t('next_entry'))
        self.right_arrow.setAccessibleName(self.t('next_entry'))
        self.right_arrow.clicked.connect(lambda: self.advance_entry(1))
        nav.addWidget(self.right_arrow)
        left_l.addLayout(nav)

        # Large, visually primary Browse All and a modal Search action.
        chooser = QHBoxLayout()
        self.chooser_layout = chooser
        self.browse_btn = QPushButton(self.t('browse'))
        self.browse_btn.setObjectName('browse')
        self.browse_btn.setIcon(asset_icon('folder'))
        self.browse_btn.clicked.connect(self.browse_entries)
        chooser.addWidget(self.browse_btn)
        self.search_button = QPushButton(self.t('search'))
        self.search_button.setIcon(asset_icon('search'))
        self.search_button.clicked.connect(self.open_search)
        chooser.addWidget(self.search_button)
        left_l.addLayout(chooser)

        # Centre the artwork, then display folder/album metadata underneath.
        self.entry_content = QVBoxLayout()
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.entry_content.addWidget(self.cover, 0, Qt.AlignHCenter)
        self.folder_info = QLabel('')
        self.folder_info.setWordWrap(True)
        self.folder_info.setAlignment(Qt.AlignCenter)
        self.folder_info.setObjectName('muted')
        self.entry_content.addWidget(self.folder_info)
        self.album_info = QLabel('')
        self.album_info.setWordWrap(True)
        self.album_info.setAlignment(Qt.AlignCenter)
        self.entry_content.addWidget(self.album_info)
        left_l.addLayout(self.entry_content)
        left_l.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)
        self.left_scroll = left_scroll
        try:
            from PyQt5.QtWidgets import QScroller
            QScroller.grabGesture(left_scroll.viewport(), QScroller.LeftMouseButtonGesture)
        except Exception:
            pass
        panes.addWidget(left_scroll)

        right = QFrame()
        right.setObjectName('panel')
        right_l = QVBoxLayout(right)
        self.right_layout = right_l
        self.files_heading = QLabel(self.t('files'))
        self.files_heading.setObjectName('heading')
        right_l.addWidget(self.files_heading)
        self.track_list = QListWidget()
        self.track_list.itemClicked.connect(self.play_selected_track)
        self.track_list.itemActivated.connect(self.play_selected_track)
        right_l.addWidget(self.track_list)
        panes.addWidget(right)
        panes.setSizes([475, 755])

        footer = QFrame()
        footer.setObjectName('panel')
        controls = QVBoxLayout(footer)
        self.footer_layout = controls
        seekrow = QHBoxLayout()
        self.position_label = QLabel('0:00')
        seekrow.addWidget(self.position_label)
        self.seek_bar = QSlider(Qt.Horizontal)
        self.seek_bar.setRange(0, 1000)
        self.seek_bar.sliderReleased.connect(self.seek_from_ui)
        seekrow.addWidget(self.seek_bar, 1)
        self.duration_label = QLabel('0:00')
        seekrow.addWidget(self.duration_label)
        controls.addLayout(seekrow)

        buttons = QHBoxLayout()
        self.transport_layout = buttons
        self.prev_btn = QPushButton()
        self.prev_btn.setIcon(asset_icon('media-previous'))
        self.prev_btn.setToolTip(self.t('previous'))
        self.prev_btn.setAccessibleName(self.t('previous'))
        self.prev_btn.clicked.connect(self.previous_track)
        buttons.addWidget(self.prev_btn)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName('primary')
        self.play_btn.setIcon(asset_icon('play'))
        self.play_btn.setToolTip(self.t('play_pause'))
        self.play_btn.setAccessibleName(self.t('play_pause'))
        self.play_btn.clicked.connect(self.toggle_play)
        buttons.addWidget(self.play_btn)
        self.next_btn = QPushButton()
        self.next_btn.setIcon(asset_icon('media-next'))
        self.next_btn.setToolTip(self.t('next'))
        self.next_btn.setAccessibleName(self.t('next'))
        self.next_btn.clicked.connect(self.next_track)
        buttons.addWidget(self.next_btn)
        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(asset_icon('stop'))
        self.stop_btn.setToolTip(self.t('stop'))
        self.stop_btn.setAccessibleName(self.t('stop'))
        self.stop_btn.clicked.connect(self.stop_play)
        buttons.addWidget(self.stop_btn)
        buttons.addSpacing(self.metrics.px(15))
        self.repeat_file_btn = QPushButton()
        self.repeat_file_btn.setIcon(asset_icon('repeat-file'))
        self.repeat_file_btn.setObjectName('repeatToggle')
        self.repeat_file_btn.setCheckable(True)
        self.repeat_file_btn.clicked.connect(lambda: self.toggle_repeat('file'))
        buttons.addWidget(self.repeat_file_btn)
        self.repeat_album_btn = QPushButton()
        self.repeat_album_btn.setIcon(asset_icon('repeat-album'))
        self.repeat_album_btn.setObjectName('repeatToggle')
        self.repeat_album_btn.setCheckable(True)
        self.repeat_album_btn.clicked.connect(lambda: self.toggle_repeat('album'))
        buttons.addWidget(self.repeat_album_btn)
        buttons.addStretch(1)
        self.vol_label = QLabel(self.t('volume'))
        buttons.addWidget(self.vol_label)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.audio.volume)
        self.volume_slider.valueChanged.connect(self.user_set_volume)
        buttons.addWidget(self.volume_slider, 1)
        self.volume_number = QLabel(f'{self.audio.volume}%')
        buttons.addWidget(self.volume_number)
        self.timer_btn = QPushButton(self.t('sleep'))
        self.timer_btn.setIcon(asset_icon('clock'))
        self.timer_btn.clicked.connect(self.timer_dialog)
        buttons.addWidget(self.timer_btn)
        controls.addLayout(buttons)
        # On narrow displays, the volume/timer group moves to a second row.
        self.secondary_controls = QHBoxLayout()
        controls.addLayout(self.secondary_controls)
        self._stacked_controls = False
        layout.addWidget(footer)
        self.status_label = QLabel(self.t('refreshing'))
        self.status_label.setObjectName('muted')
        self.status_label.setWordWrap(False)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        self.scan_bar = QProgressBar()
        self.scan_bar.setTextVisible(True)
        self.scan_bar.setMinimumWidth(self.metrics.px(125))
        self.scan_bar.setMaximumWidth(self.metrics.px(240))
        self.scan_bar.setVisible(False)
        status_row.addWidget(self.scan_bar)
        self.timer_label = QLabel(self.t('sleep_off'))
        self.timer_label.setObjectName('muted')
        self.timer_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timer_label.setWordWrap(False)
        status_row.addWidget(self.timer_label, 0)
        layout.addLayout(status_row)

        # Input device agnostic keyboard shortcuts (GPIO can send the same keys).
        from PyQt5.QtGui import QKeySequence
        for keys, fn in (('F11', self.toggle_fullscreen),
                         ('Ctrl+Right', self.next_track), ('Ctrl+Left', self.previous_track),
                         ('[', lambda: self.user_set_volume(self.audio.volume - 5)),
                         (']', lambda: self.user_set_volume(self.audio.volume + 5))):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(fn)
        for list_widget in (self.track_list,):
            list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            try:
                from PyQt5.QtWidgets import QScroller
                QScroller.grabGesture(list_widget.viewport(), QScroller.LeftMouseButtonGesture)
            except Exception:
                pass
        self._last_play_icon = ''
        self.update_repeat_buttons()
        self.apply_scaling()

    def apply_scaling(self):
        """Apply independent text and touch-control scales without rebuilding playback."""
        self.metrics = UiMetrics(self.config.data['ui_scale'], self.config.data['text_scale'])
        m = self.metrics
        self.setStyleSheet(stylesheet(m))
        self.root_layout.setContentsMargins(m.px(9), m.px(7), m.px(9), m.px(6))
        self.root_layout.setSpacing(m.px(6))
        self.header_layout.setSpacing(m.px(7))
        self.clock_row.setSpacing(m.px(12))
        self.time_label.setMinimumWidth(m.px(110))
        self.left_layout.setContentsMargins(m.px(11), m.px(9), m.px(11), m.px(8))
        self.left_layout.setSpacing(m.px(7))
        self.right_layout.setContentsMargins(m.px(10), m.px(9), m.px(10), m.px(8))
        self.right_layout.setSpacing(m.px(6))
        self.footer_layout.setContentsMargins(m.px(9), m.px(5), m.px(9), m.px(7))
        self.footer_layout.setSpacing(m.px(3))
        self.transport_layout.setSpacing(m.px(6))
        self.chooser_layout.setSpacing(m.px(7))
        self.entry_content.setSpacing(m.px(10))
        for button in (self.dim_button, self.system_button, self.category_button, self.refresh_button, self.fullscreen_button,
                       self.options_button, self.browse_btn, self.search_button, self.left_arrow,
                       self.right_arrow, self.prev_btn, self.play_btn,
                       self.next_btn, self.stop_btn, self.timer_btn,
                       self.repeat_file_btn, self.repeat_album_btn):
            button.setMinimumHeight(m.button_height)
            button.setIconSize(QSize(m.px(24), m.px(24)))
        self.browse_btn.setMinimumHeight(m.primary_height)
        self.browse_btn.setMinimumWidth(m.px(110 if self.width() <= 1350 else 144))
        self.browse_btn.setIconSize(QSize(m.px(27), m.px(27)))
        for button in (self.left_arrow, self.right_arrow,
                       self.prev_btn, self.next_btn, self.stop_btn,
                       self.repeat_file_btn, self.repeat_album_btn):
            button.setFixedWidth(max(m.px(49), m.font(16) + m.px(18)))
            button.setIconSize(QSize(m.px(32), m.px(32)))
        self.play_btn.setFixedWidth(m.px(66))
        self.play_btn.setMinimumHeight(m.primary_height)
        self.play_btn.setIconSize(QSize(m.px(38), m.px(38)))
        self.category_button.setIconSize(QSize(m.px(29), m.px(29)))
        self.search_button.setMinimumHeight(m.primary_height)
        self.search_button.setIconSize(QSize(m.px(27), m.px(27)))
        self.seek_bar.setMinimumHeight(m.px(27))
        self.volume_slider.setMinimumHeight(m.px(28))
        self.volume_slider.setMinimumWidth(m.px(95))
        self.volume_slider.setMaximumWidth(m.px(220))
        self.track_list.setSpacing(m.px(3))
        self.track_list.setIconSize(QSize(m.px(29), m.px(29)))
        self.scan_bar.setMinimumWidth(m.px(100))
        self.dim_button.setFixedWidth(m.px(48))
        self.system_button.setFixedWidth(m.px(48))
        self.dim_button.setIconSize(QSize(m.px(29), m.px(29)))
        self.system_button.setIconSize(QSize(m.px(29), m.px(29)))
        self.update_responsive()
        for row in range(self.track_list.count()):
            item = self.track_list.item(row)
            lines = item.text().count('\n') + 1
            item.setSizeHint(QSize(0, max(m.row_height, m.font(15) * lines + m.px(14))))
        if self.current_entry():
            self.draw_cover(self.current_entry())

    def update_responsive(self):
        """Use available space; keep transport usable on short touchscreens."""
        m = self.metrics
        narrow = self.width() < max(1080, round(980 * m.ui_scale / 1.5))
        compact = self.height() < 700
        self.brand.setVisible(not narrow)
        self.refresh_button.setText('' if narrow else self.t('refresh'))
        self.system_button.setText('')
        self.dim_button.setText('')
        self.options_button.setText('' if narrow else self.t('options'))
        self.fullscreen_button.setText('' if narrow else
                                       self.t('windowed' if self.isFullScreen() else 'fullscreen'))
        self.refresh_button.setToolTip(self.t('refresh'))
        self.options_button.setToolTip(self.t('options'))
        self.fullscreen_button.setToolTip(self.t('windowed' if self.isFullScreen() else 'fullscreen'))
        if narrow != self._stacked_controls:
            destination = self.secondary_controls if narrow else self.transport_layout
            for item in (self.vol_label, self.volume_slider, self.volume_number, self.timer_btn):
                destination.addWidget(item, 1 if item is self.volume_slider else 0)
            self._stacked_controls = narrow
        self.vol_label.setVisible(True)
        self.timer_label.setVisible(True)  # A single-line footer is always visible.
        self.category_button.setMaximumWidth(m.px(230))
        self.search_button.setMinimumWidth(m.px(60 if self.width() <= 1350 else 92))
        self.category_button.setVisible(not self.config.data.get('categoryless', False))
        self.category_button.setToolTip(self.current_category or self.t('categories'))
        size = m.px(112 if compact else 155)
        self.cover.setFixedSize(size, size)
        # During the first layout pass, widths can be zero. Don't clip the menu.
        self.panes.setHandleWidth(m.px(8))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setIcon(asset_icon('fullscreen'))
            self.update_responsive()
            event.accept()
            return
        if event.key() == Qt.Key_Space and not isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)):
            self.toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'vol_label') and hasattr(self, 'cover') and hasattr(self, 'metrics'):
            self.update_responsive()
            if hasattr(self, 'dim_overlay'):
                self.dim_overlay.setGeometry(self.centralWidget().rect())
            if hasattr(self, 'modal_overlay'):
                self.modal_overlay.setGeometry(self.centralWidget().rect())
            self._raise_overlays()
            if self.current_entry():
                self.draw_cover(self.current_entry())

    def update_clock(self):
        """Show date names from the selected YAML translation and local system time."""
        now = QDateTime.currentDateTime()
        date = self.tl.format_date(now.date().toPyDate())
        moment = now.toString('HH:mm:ss')
        if self.date_label.text() != date:
            self.date_label.setText(date)
        if self.time_label.text() != moment:
            self.time_label.setText(moment)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.fullscreen_button.setIcon(asset_icon('windowed' if self.isFullScreen() else 'fullscreen'))
        self.update_responsive()

    def _raise_overlays(self):
        """Keep the modal shade above software dimming, but below top-level dialogs."""
        if hasattr(self, 'dim_overlay') and self.dim_overlay.isVisible():
            self.dim_overlay.raise_()
        if hasattr(self, 'modal_overlay') and self._modal_depth:
            self.modal_overlay.raise_()

    def _software_dim(self, percent: int):
        if not hasattr(self, 'dim_overlay'):
            return
        if percent >= 100:
            self.dim_overlay.hide()
            return
        # Software dimmer covers this application's window only. Always input-transparent.
        alpha = min(230, round((100 - percent) * 2.55))
        self.dim_overlay.setStyleSheet(f'background-color: rgba(0, 0, 0, {alpha});')
        self.dim_overlay.show()
        self._raise_overlays()

    def run_modal(self, dialog: QDialog) -> int:
        """Run a modal dialog with an input-transparent shade over the player.

        The dialog is a separate top-level Qt window, so it stays fully lit.
        A nesting counter avoids flicker when a confirmation opens on top of
        an already-open dialog, and finally handles Escape and window closing.
        """
        self._modal_depth += 1
        try:
            self.modal_overlay.setGeometry(self.centralWidget().rect())
            self.modal_overlay.show()
            self._raise_overlays()
            return dialog.exec_()
        finally:
            self._modal_depth -= 1
            try:
                if self._modal_depth == 0:
                    self.modal_overlay.hide()
                else:
                    self._raise_overlays()
            except RuntimeError:
                # The main window may have been destroyed while closing Qt.
                pass

    def show_message(self, icon, title: str, message: str,
                     buttons=QMessageBox.Ok, default=QMessageBox.NoButton) -> int:
        """Show informational/confirmation messages with the same modal shade."""
        # Parent nested confirmations to the currently active dialog (e.g.
        # System Controls), so the confirmation remains above that dialog.
        parent = QApplication.activeModalWidget() or self
        box = QMessageBox(icon, title, message, buttons, parent)
        box.setStyleSheet(stylesheet(self.metrics))
        if default != QMessageBox.NoButton:
            box.setDefaultButton(default)
        return self.run_modal(box)

    def brightness_tick(self):
        self.brightness.tick()
        interval = 120 if self.brightness.animating else 1000
        if self.bright_timer.interval() != interval:
            self.bright_timer.setInterval(interval)

    def screen_activity(self):
        if not hasattr(self, 'brightness'):
            return
        self.brightness.activity()
        if self.brightness.animating:
            self.bright_timer.setInterval(120)

    def set_brightness(self, level):
        self.brightness.set_level(level)
        self.bright_timer.setInterval(1000)

    def toggle_dim(self):
        self.brightness.toggle_dim()
        self.bright_timer.setInterval(120)

    def system_dialog(self):
        dialog = SystemDialog(self)
        self.run_modal(dialog)

    def confirm_shutdown(self):
        answer = self.show_message(QMessageBox.Question, self.t('shutdown_pc'),
                                   self.t('shutdown_confirm'),
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._poweroff()
            return True
        return False

    def refresh_library(self):
        if self.scanning:
            self.rescan_pending = True
            return
        self.scanning = True
        self.refresh_button.setEnabled(False)
        self.scan_bar.setRange(0, 0)
        self.scan_bar.show()
        self.status_label.setText(self.t('refreshing'))
        data = self.config.data
        groups = list(data['group_folders'])
        direct = dict(data['direct_folders'])
        extra = dict(data.get('category_folders', {}))
        cache = str(data['cache_db'])

        def worker():
            last_report = [0.0]

            def progress(done, total, label):
                # Coalesce fast scans: don't queue thousands of GUI repaints.
                now = time.monotonic()
                if done == 0 or done == total or now - last_report[0] >= 0.12:
                    self.scan_progress.emit(done, total, label)
                    last_report[0] = now

            try:
                result = scan(groups, direct, cache, extra, progress)
                save_snapshot(result, cache)
            except Exception as exc:
                result = exc
            self.scan_finished.emit(result)
        threading.Thread(target=worker, daemon=True, name='library-scanner').start()

    def on_scan_progress(self, done: int, total: int, label: str):
        if not self.scanning:
            return
        if total <= 0:
            self.scan_bar.setRange(0, 0)
            self.status_label.setText(self.t('discovering'))
        else:
            self.scan_bar.setRange(0, total)
            self.scan_bar.setValue(done)
            self.status_label.setText(self.t('scan_progress', done=done, total=total, folder=label))

    def on_scan_finished(self, result):
        self.scanning = False
        self.refresh_button.setEnabled(True)
        self.scan_bar.hide()
        if self.rescan_pending:
            self.rescan_pending = False
            self.refresh_library()
            return
        if isinstance(result, Exception):
            self.status_label.setText(str(result))
            self.show_message(QMessageBox.Warning, self.t('scan_warnings'), str(result))
            return
        old_entry = self.current_entry_id
        self.library = result
        cached_cover_icon.cache_clear()  # Cover files may have changed during Refresh.
        self._cover_signature = None
        self._all_nav_entries = None
        self._category_summaries = [c.as_dict() for c in self.library.categories.values()]
        if not self.library.category(self.current_category):
            self.current_category = next(iter(self.library.categories), '')
        entries = self.category_entries()
        ids = {e.id for e in entries}
        self.current_entry_id = old_entry if old_entry in ids else (entries[0].id if entries else '')
        self.update_categories_button()
        self.show_entry(autoplay=False, preserve_audio=True)
        counts = len(self.library.all_entries()), len(self.library.categories)
        message = self.t('refreshed', entries=counts[0], categories=counts[1])
        if self.library.warnings:
            message += f'  ·  {len(self.library.warnings)} warning(s)'
        self.status_label.setText(message)

    def current_entry(self) -> Entry | None:
        return self.library.by_id.get(self.current_entry_id)

    def category_entries(self) -> list[Entry]:
        if self.config.data.get('categoryless', False):
            if getattr(self, '_all_nav_entries', None) is None:
                from .library import natural_key
                self._all_nav_entries = sorted(self.library.all_entries(), key=lambda e: (natural_key(e.folder_name), e.id))
            return self._all_nav_entries
        category = self.library.category(self.current_category)
        return category.entries if category else []

    def update_categories_button(self):
        cat = self.library.category(self.current_category)
        if cat:
            self.category_button.setIcon(category_icon(cat.name))
            self.category_button.setIconSize(QSize(self.metrics.px(29), self.metrics.px(29)))
            self.category_button.setText(f'{cat.name} ({len(cat.entries)})')
        else:
            self.category_button.setIcon(QIcon())
            self.category_button.setText(self.t('categories'))

    def open_categories(self):
        if not self.library.categories:
            self.show_message(QMessageBox.Information, self.t('categories'), self.t('no_categories'))
            return
        dlg = CategoryBrowser(self.library, self.tl, self)
        if self.run_modal(dlg) == QDialog.Accepted and dlg.selected_key:
            self.select_category(dlg.selected_key)

    def select_category(self, key: str):
        self.current_category = key.casefold()
        entries = self.category_entries()
        self.current_entry_id = entries[0].id if entries else ''
        self.update_categories_button()
        self.show_entry(autoplay=False)

    def advance_entry(self, delta: int):
        entries = self.category_entries()
        if not entries:
            return
        ids = [e.id for e in entries]
        idx = ids.index(self.current_entry_id) if self.current_entry_id in ids else 0
        self.select_entry(ids[(idx + delta) % len(ids)])

    def select_entry(self, entry_id: str, track_index: int | None = None, autoplay: bool = False):
        entry = self.library.by_id.get(entry_id)
        if not entry:
            raise ValueError('Entry not found')
        self.current_entry_id = entry_id
        self.current_category = entry.category.casefold()
        self.update_categories_button()
        self.show_entry(autoplay=autoplay, track_index=track_index or 0)

    def draw_cover(self, entry: Entry):
        size = max(48, min(self.cover.width(), self.cover.height()) - self.metrics.px(6))
        signature = (entry.cover, entry.category, size)
        if getattr(self, '_cover_signature', None) == signature:
            return
        self._cover_signature = signature
        if entry.cover:
            icon = cached_cover_icon(entry.cover, size)
            pix = (icon if not icon.isNull() else category_icon(entry.category)).pixmap(size, size)
        else:
            pix = category_icon(entry.category).pixmap(size, size)
        if not pix.isNull():
            self.cover.setPixmap(pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.clear()

    def show_entry(self, autoplay=False, track_index=0, preserve_audio=False):
        entry = self.current_entry()
        self.track_list.clear()
        if not entry:
            self._cover_signature = None
            self.entry_label.setText(self.t('no_entries') if self.library.categories else self.t('no_categories'))
            self.folder_info.setText('')
            self.album_info.setText('')
            self.cover.clear()
            self.audio.load([])
            self.state_store.update(category=self.current_category, entry_id='')
            return
        self.entry_label.setText(entry.display_name)
        md = self.config.data.get('metadata', {})
        self.folder_info.setText(f'{self.t("folder")}: {entry.folder_name}' if md.get('folder_name', True) else '')
        album_bits = []
        if md.get('folder_album', True) and entry.album_title:
            album_bits.append(f'{self.t("album")}: {entry.album_title}')
        if md.get('folder_artist', True) and entry.artist:
            album_bits.append(f'{self.t("artist")}: {entry.artist}')
        self.album_info.setText('  ·  '.join(album_bits))
        self.draw_cover(entry)
        for i, track in enumerate(entry.tracks):
            parts = []
            if md.get('file_name', True):
                parts.append(track.relative_path)
            if md.get('file_title', True) and track.title:
                parts.append(track.title)
            if md.get('file_artist', False) and track.artist:
                parts.append(track.artist)
            item = QListWidgetItem('\n'.join(parts) or track.filename)
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(0, max(self.metrics.row_height, self.metrics.font(15) * len(parts) + self.metrics.px(14))))
            self.track_list.addItem(item)
        desired = max(0, min(track_index, len(entry.tracks) - 1))
        self.track_list.setCurrentRow(desired)
        paths = [t.path for t in entry.tracks]
        if not preserve_audio or self.audio.paths != paths:
            self.audio.load(paths, desired, autoplay)
        self.state_store.update(category=self.current_category, entry_id=entry.id)


    def open_search(self):
        dlg = SearchDialog(self.library, self.current_category, self.tl, self)
        if self.run_modal(dlg) == QDialog.Accepted and dlg.selected_id:
            self.select_entry(dlg.selected_id, dlg.selected_track, autoplay=dlg.selected_track is not None)

    def update_repeat_buttons(self):
        """Keep exclusive repeat indicators and accessible state in sync."""
        for button, mode, key in ((self.repeat_file_btn, 'file', 'repeat_file'),
                                  (self.repeat_album_btn, 'album', 'repeat_album')):
            enabled = self.audio.repeat_mode == mode
            button.setChecked(enabled)
            state = self.t('repeat_enabled' if enabled else 'repeat_disabled')
            button.setToolTip(f'{self.t(key)} — {state}')
            button.setAccessibleName(f'{self.t(key)} — {state}')

    def toggle_repeat(self, requested: str):
        mode = 'off' if self.audio.repeat_mode == requested else requested
        self.audio.set_repeat(mode)
        self.update_repeat_buttons()
        self.state_store.update(repeat_mode=mode)

    def browse_entries(self):
        # Show immediately, then populate in batches to keep the working animation alive.
        dialog = EntryBrowser(self.category_entries(), self.tl, self)
        if self.run_modal(dialog) == QDialog.Accepted and dialog.selected_id:
            self.select_entry(dialog.selected_id)

    def play_selected_track(self, item):
        entry = self.current_entry()
        if entry:
            index = item.data(Qt.UserRole)
            self.audio.load([t.path for t in entry.tracks], int(index), True)

    def next_track(self):
        self.audio.next()
        self.tick()

    def previous_track(self):
        self.audio.previous()
        self.tick()

    def toggle_play(self):
        self.audio.toggle()
        self.tick()

    def stop_play(self):
        self.audio.stop()
        self.tick()

    def _set_volume(self, volume):
        self.audio.set_volume(volume)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self.audio.volume)
        self.volume_slider.blockSignals(False)
        self.volume_number.setText(f'{self.audio.volume}%')

    def user_set_volume(self, volume):
        self._set_volume(volume)
        self.state_store.update(volume=self.audio.volume)

    def seek_from_ui(self):
        duration = self.audio.duration_seconds()
        if duration:
            self.audio.seek(duration * self.seek_bar.value() / 1000)

    def timer_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t('sleep'))
        dialog.setStyleSheet(stylesheet(self.metrics))
        fit_dialog(dialog, self.metrics.px(390), self.metrics.px(230))
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.t('sleep_minutes')))
        minutes = TouchSpinBox(self.metrics, self.t)
        minutes.setRange(1, 1440)
        minutes.setValue(30)
        minutes.setMinimumHeight(self.metrics.button_height)
        layout.addWidget(minutes)
        buttons = QHBoxLayout()
        start = QPushButton(self.t('sleep_set'))
        cancel = QPushButton(self.t('sleep_cancel'))
        close = QPushButton(self.t('cancel'))
        start.clicked.connect(lambda: (self.sleep.set(minutes.value() * 60), dialog.accept()))
        cancel.clicked.connect(lambda: (self.sleep.cancel(), dialog.accept()))
        close.clicked.connect(dialog.reject)
        for b in (start, cancel, close):
            b.setMinimumHeight(self.metrics.button_height)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.run_modal(dialog)
        self.tick()

    @pyqtSlot(str)
    def _show_shutdown_error(self, error):
        self.show_message(QMessageBox.Critical, self.t('system_error'), self.t('shutdown_failed', error=error))

    def _poweroff(self):
        """Never block Qt's event loop while asking systemd to power off."""
        binary = shutil.which('systemctl')
        if binary is None:
            self.shutdown_error.emit('systemctl is unavailable')
            return

        def worker():
            try:
                completed = subprocess.run([binary, 'poweroff'], capture_output=True, text=True, timeout=12)
                if completed.returncode:
                    raise RuntimeError(completed.stderr.strip() or str(completed.returncode))
            except Exception as exc:
                self.shutdown_error.emit(str(exc))
        threading.Thread(target=worker, daemon=True, name='system-poweroff').start()

    def tick(self):
        if self.webserver and self.webserver.error and not self._web_error_seen:
            self._web_error_seen = True
            self.status_label.setText('LAN controller unavailable: ' + self.webserver.error)
        self.audio.poll()
        self.sleep.tick()
        playing = self.audio.state()
        playback_icon = 'pause' if playing['status'] == 'playing' else 'play'
        if self._last_play_icon != playback_icon:
            self.play_btn.setIcon(asset_icon(playback_icon))
            self._last_play_icon = playback_icon
        if not self.seek_bar.isSliderDown():
            self.seek_bar.setValue(int(1000 * playing['position'] / playing['duration']) if playing['duration'] else 0)
        position_string = format_time(playing['position'])
        duration_string = format_time(playing['duration'])
        if self.position_label.text() != position_string:
            self.position_label.setText(position_string)
        if self.duration_label.text() != duration_string:
            self.duration_label.setText(duration_string)
        if self.track_list.count() and 0 <= self.audio.index < self.track_list.count():
            if self.track_list.currentRow() != self.audio.index:
                self.track_list.blockSignals(True)
                self.track_list.setCurrentRow(self.audio.index)
                self.track_list.blockSignals(False)
        timer = self.sleep.state()
        timer_string = (self.t('sleep_fading_short' if timer['fading'] else 'sleep_active_short',
                               time=format_time(timer['remaining_seconds']))
                        if timer['active'] else self.t('sleep_off'))
        if self.timer_label.text() != timer_string:
            self.timer_label.setText(timer_string)
        desired_poll = 400 if playing['status'] == 'playing' or timer['fading'] else (1000 if timer['active'] else 1500)
        if self.poll_timer.interval() != desired_poll:
            self.poll_timer.setInterval(desired_poll)
        if self.height() < 700:
            self.timer_btn.setText(format_time(timer['remaining_seconds']) if timer['active'] else self.t('sleep'))
        else:
            self.timer_btn.setText(self.t('sleep'))

    def show_options(self):
        dlg = OptionsDialog(self.config, self.tl, self)
        if self.run_modal(dlg) != QDialog.Accepted:
            return
        try:
            old_web = dict(self.config.data['web'])
            old_sources = (self.config.data['group_folders'], self.config.data['direct_folders'],
                           self.config.data.get('category_folders'))
            old_display = dict(self.config.data['display'])
            new_data = dlg.result_data()
            self.config.data = new_data
            self.config.save()
            self.tl = Translator(new_data['language'])
            self.t = self.tl.t
            self.apply_scaling()
            self.retranslate()
            if old_web != new_data['web']:
                self.start_server(restart=True)
            if old_display.get('backend') != new_data['display']['backend'] or old_display.get('device') != new_data['display']['device']:
                previous_normal = self.brightness.normal
                self.brightness.set_level(previous_normal)
                self.brightness = BrightnessController(new_data['display'], self._software_dim)
                self.brightness.set_level(previous_normal)
            else:
                self.brightness.configure(new_data['display'])
            if old_sources != (new_data['group_folders'], new_data['direct_folders'], new_data.get('category_folders')):
                self.refresh_library()
            self.status_label.setText(self.t('settings_saved'))
        except Exception as exc:
            self.show_message(QMessageBox.Warning, self.t('settings_error'), str(exc))

    def retranslate(self):
        self.setWindowTitle(self.t('app_title'))
        self.brand.setText(self.t('app_title'))
        self.dim_button.setToolTip(self.t('dim_toggle'))
        self.dim_button.setAccessibleName(self.t('dim_toggle'))
        self.system_button.setToolTip(self.t('system_controls'))
        self.system_button.setAccessibleName(self.t('system_controls'))
        self.browse_btn.setText(self.t('browse'))
        self.search_button.setText(self.t('search'))
        self.files_heading.setText(self.t('files'))
        self.vol_label.setText(self.t('volume'))
        self.left_arrow.setToolTip(self.t('previous_entry'))
        self.right_arrow.setToolTip(self.t('next_entry'))
        for button, key in ((self.prev_btn, 'previous'), (self.next_btn, 'next'),
                            (self.play_btn, 'play_pause'), (self.stop_btn, 'stop')):
            button.setToolTip(self.t(key))
            button.setAccessibleName(self.t(key))
        self.update_repeat_buttons()
        self.search_button.setToolTip(self.t('search'))
        self.update_categories_button()
        self.update_responsive()
        self.update_clock()
        self.show_entry(preserve_audio=True)

    def start_server(self, restart=False):
        self._web_error_seen = False
        if restart and self.webserver:
            self.webserver.close()
            self.webserver = None
        web = self.config.data['web']
        if not web.get('enabled', True):
            return
        app = make_app(self.bridge.call, str(web['token']))
        self.webserver = WebServer(str(web['host']), int(web['port']), app)
        self.webserver.start()

    def handle_command(self, data: dict):
        action = data.get('action')
        if action == 'state':
            entry = self.current_entry()
            playing = self.audio.state()
            track = entry.tracks[self.audio.index].as_dict() if entry and 0 <= self.audio.index < len(entry.tracks) else None
            return {'entry': entry.as_dict() if entry else None,
                    'track': track, 'playback': playing, 'timer': self.sleep.state(),
                    'categories': getattr(self, '_category_summaries', []),
                    'brightness': self.brightness.state(), 'scanning': self.scanning}
        if action == 'search':
            return {'results': self.library.search(str(data.get('query', ''))[:160])}
        if action == 'cover_path':
            entry = self.library.by_id.get(str(data.get('entry_id', '')))
            return {'path': entry.cover if entry else ''}
        if action == 'select':
            index = int(data.get('file_index', 0))
            entry_id = str(data.get('entry_id', ''))
            entry = self.library.by_id.get(entry_id)
            if not entry or not 0 <= index < len(entry.tracks):
                raise ValueError('Unknown entry or track index')
            self.select_entry(entry_id, index, True)
        elif action == 'play':
            self.audio.play()
        elif action == 'pause':
            self.audio.pause()
        elif action == 'toggle':
            self.audio.toggle()
        elif action == 'stop':
            self.audio.stop()
        elif action == 'next':
            self.audio.next()
        elif action == 'previous':
            self.audio.previous()
        elif action == 'volume':
            self.user_set_volume(int(data['value']))
        elif action == 'repeat':
            self.audio.set_repeat(str(data.get('mode', 'off')))
            self.update_repeat_buttons()
            self.state_store.update(repeat_mode=self.audio.repeat_mode)
        elif action == 'seek':
            self.audio.seek(float(data['seconds']))
        elif action == 'timer':
            seconds = int(data['seconds'])
            if seconds < 0 or seconds > 86400:
                raise ValueError('Timer must be between 0 and 86400 seconds')
            self.sleep.set(seconds)
        elif action == 'refresh':
            self.refresh_library()
        elif action == 'dim':
            self.toggle_dim()
        elif action == 'brightness':
            level = int(data['value'])
            if not 10 <= level <= 100:
                raise ValueError('Brightness must be between 10% and 100%')
            self.set_brightness(level)
        elif action == 'shutdown':
            if data.get('confirm') is not True:
                raise ValueError('Shutdown requires confirm: true')
            self._poweroff()
        elif action in {'nav_up', 'nav_down', 'nav_left', 'nav_right', 'activate'}:
            self.navigation_action(action)
        else:
            raise ValueError('Unknown command')
        if action in ('play', 'pause', 'toggle', 'stop', 'next', 'previous', 'select', 'timer', 'repeat'):
            self.tick()
        return {'ok': True}

    def navigation_action(self, action: str):
        """GPIO integration point: map physical joystick events to these actions."""
        code = {'nav_up': Qt.Key_Up, 'nav_down': Qt.Key_Down,
                'nav_left': Qt.Key_Left, 'nav_right': Qt.Key_Right,
                'activate': Qt.Key_Return}[action]
        widget = QApplication.focusWidget() or self.category_button
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))
        QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, code, Qt.NoModifier))

    def closeEvent(self, event):
        self.poll_timer.stop()
        self.bright_timer.stop()
        self.clock_timer.stop()
        self.brightness.set_level(self.brightness.normal)
        self.sleep.cancel()
        if self.webserver:
            self.webserver.close()
        QApplication.instance().removeEventFilter(self.activity_filter)
        QApplication.instance().removeEventFilter(self.navigation_filter)
        self.audio.close()
        super().closeEvent(event)
