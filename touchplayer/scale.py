"""Size calculations shared by the desktop window and dialogs.

UI scale governs widget hit targets, padding and icons. Text scale separately
controls font size. A minimum target is chosen so larger fonts are never clipped.
"""
from dataclasses import dataclass
from pathlib import Path
import math

MIN_SCALE = 0.75
MAX_SCALE = 2.0
DEFAULT_SCALE = 1.5


def validate_scale(value, label='scale') -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number between 0.75 and 2.0') from exc
    if not math.isfinite(number) or not MIN_SCALE <= number <= MAX_SCALE:
        raise ValueError(f'{label} must be between 0.75 and 2.0')
    return number


@dataclass(frozen=True)
class UiMetrics:
    ui_scale: float = DEFAULT_SCALE
    text_scale: float = DEFAULT_SCALE

    def __post_init__(self):
        validate_scale(self.ui_scale, 'ui_scale')
        validate_scale(self.text_scale, 'text_scale')

    def px(self, value: float) -> int:
        return max(1, round(value * self.ui_scale))

    def font(self, value: float) -> int:
        return max(10, round(value * self.text_scale))

    @property
    def button_height(self) -> int:
        return max(self.px(42), self.font(15) + self.px(16))

    @property
    def primary_height(self) -> int:
        return max(self.px(52), self.font(18) + self.px(18))

    @property
    def row_height(self) -> int:
        return max(self.px(58), 2 * self.font(15) + self.px(16))


def stylesheet(m: UiMetrics) -> str:
    asset_dir = (Path(__file__).resolve().parent.parent / 'assets').as_posix()
    return f'''
QWidget {{background:#101b2a;color:#e6f1f9;font-family:"DejaVu Sans",sans-serif;font-size:{m.font(15)}px}}
QFrame#panel {{background:#182a3d;border:1px solid #38546a;border-radius:{m.px(12)}px}}
QPushButton {{background:#253e56;border:2px solid #46657d;border-radius:{m.px(9)}px;
             padding:{m.px(3)}px {m.px(8)}px;font-weight:600}}
QPushButton:checked {{background:#126f8a;border:3px solid #a7f6fc}}
QPushButton:hover {{background:#30516b}}
QPushButton:pressed {{background:#278ca9}}
QPushButton:focus {{border:3px solid #b9f1fb}}
/* Repeat mode is explicitly GREEN only when enabled, regardless of focus/hover. */
QPushButton#repeatToggle:!checked {{background:#253e56;border:2px solid #46657d}}
QPushButton#repeatToggle:!checked:focus {{background:#253e56;border:2px solid #7897a8}}
QPushButton#repeatToggle:checked,
QPushButton#repeatToggle:checked:focus,
QPushButton#repeatToggle:checked:hover,
QPushButton#repeatToggle:checked:pressed {{background:#208642;border:3px solid #a2f7b6;color:#ffffff}}

QPushButton#browse {{background:#087f9f;border:3px solid #8ae7fa;font-size:{m.font(17)}px;font-weight:800}}
QPushButton#browse:hover {{background:#0b9abd}}
QPushButton#primary {{background:#087f9f;border:3px solid #6ed9ef}}
QPushButton#danger {{background:#5a2028;border:3px solid #ed9198;color:#fff2f2}}
QPushButton#danger:pressed {{background:#842934}}
QPushButton:disabled {{color:#8199a9;background:#1b2c3e;border-color:#31485b}}
QLabel#muted {{color:#acc6d5}}
QLabel#heading {{font-size:{m.font(19)}px;font-weight:700}}
QLabel#clock {{font-size:{round(m.font(15) * 1.5)}px;font-weight:650}}
QLineEdit,QPlainTextEdit,QSpinBox,QComboBox,QTableWidget,QListWidget {{
 background:#0e1a29;border:2px solid #3b566d;border-radius:{m.px(8)}px;padding:{m.px(4)}px;
 selection-background-color:#197e9c}}
QLineEdit:focus,QPlainTextEdit:focus,QSpinBox:focus,QComboBox:focus,QListWidget:focus {{border:2px solid #91e2f1}}
QListWidget::item {{border-bottom:1px solid #25384a;padding:{m.px(4)}px;border-radius:{m.px(4)}px}}
QListWidget::item:selected {{background:#1c7898;color:white}}
QSlider::groove:horizontal {{height:{m.px(9)}px;background:#314b60;border-radius:{m.px(4)}px}}
QSlider::handle:horizontal {{background:#89e7f2;width:{m.px(24)}px;margin:-{m.px(10)}px 0;border-radius:{m.px(10)}px}}
QMenu {{background:#192d40;border:2px solid #36556a;padding:{m.px(6)}px}}
QMenu::item {{padding:{m.px(12)}px {m.px(19)}px;border-radius:{m.px(5)}px}}
QMenu::item:selected {{background:#287b9c}}
QDialog {{background:#162435}}
QTabWidget::pane {{border:1px solid #38546a}}
QTabBar::tab {{padding:{m.px(9)}px {m.px(13)}px;background:#253b50;margin:{m.px(2)}px;border-radius:{m.px(5)}px}}
QTabBar::tab:selected {{background:#107b9c}}
QScrollBar:vertical {{background:#1b2e40;width:{m.px(27)}px;margin:{m.px(33)}px 0 {m.px(33)}px 0}}
QScrollBar::handle:vertical {{background:#597f98;border-radius:{m.px(8)}px;min-height:{m.px(55)}px}}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{
 background:#355773;height:{m.px(33)}px;subcontrol-origin:margin;border:1px solid #6b9db8}}
QScrollBar::add-line:vertical {{subcontrol-position:bottom}}
QScrollBar::sub-line:vertical {{subcontrol-position:top}}
QScrollBar::up-arrow:vertical {{image:url({asset_dir}/scroll-up.svg);width:{m.px(20)}px;height:{m.px(20)}px}}
QScrollBar::down-arrow:vertical {{image:url({asset_dir}/scroll-down.svg);width:{m.px(20)}px;height:{m.px(20)}px}}
QScrollBar:horizontal {{background:#1b2e40;height:{m.px(27)}px}}
QScrollBar::handle:horizontal {{background:#597f98;border-radius:{m.px(8)}px}}
QToolTip {{background:#263c52;color:white;font-size:{m.font(14)}px}}
'''
