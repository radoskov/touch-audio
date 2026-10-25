"""v1.4.1 regression coverage for the modal-dialog backdrop."""
from pathlib import Path
import ast

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ui_tree():
    return ast.parse((ROOT / 'touchplayer/ui.py').read_text())


def test_every_main_window_dialog_uses_modal_shading():
    """Avoid silent regressions when adding new dialogs or message boxes."""
    tree = _ui_tree()
    direct_calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'exec_'):
            direct_calls.append(node.lineno)
    # The only raw exec_ is inside the wrapper that manages the shade.
    assert len(direct_calls) == 1
    source = (ROOT / 'touchplayer/ui.py').read_text()
    assert 'return dialog.exec_()' in source
    assert 'self.run_modal(box)' in source
    assert 'QMessageBox.question(' not in source
    assert 'QMessageBox.warning(' not in source
    assert 'QMessageBox.information(' not in source
    assert 'QMessageBox.critical(' not in source


def test_modal_backdrop_separate_from_brightness_dimmer():
    source = (ROOT / 'touchplayer/ui.py').read_text()
    assert 'self.modal_overlay = QWidget(self.centralWidget())' in source
    assert 'self.dim_overlay = QWidget(self.centralWidget())' in source
    assert 'self.modal_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)' in source
    assert 'self.modal_overlay.setFocusPolicy(Qt.NoFocus)' in source
    assert 'self.modal_overlay.setGeometry(self.centralWidget().rect())' in source
    assert 'self._modal_depth += 1' in source
    assert 'self._modal_depth -= 1' in source
    assert 'finally:' in source
    assert 'self.modal_overlay.hide()' in source


def test_dialogs_are_shaded_during_exec_if_qt_installed(monkeypatch):
    """Optional GUI smoke test, runs with Qt offscreen on a GUI-equipped CI."""
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    pytest.importorskip('PyQt5')
    pytest.importorskip('flask')
    pytest.importorskip('yaml')
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtWidgets import QApplication, QDialog, QWidget
    from touchplayer.ui import MainWindow

    app = QApplication.instance() or QApplication(['modal-test'])

    class Dummy:
        def __init__(self):
            self.root = QWidget()
            self.root.resize(800, 480)
            self.dim_overlay = QWidget(self.root)
            self.dim_overlay.hide()
            self.modal_overlay = QWidget(self.root)
            self.modal_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.modal_overlay.setGeometry(self.root.rect())
            self.modal_overlay.hide()
            self._modal_depth = 0
            self.seen = []

        def centralWidget(self):
            return self.root

        def _raise_overlays(self):
            self.seen.append(self._modal_depth)

    dummy = Dummy()
    dummy.root.show()
    dialog = QDialog(dummy.root)
    def inspect_and_close():
        assert dummy.modal_overlay.isVisible()
        assert dummy._modal_depth == 1
        assert dummy.modal_overlay.geometry() == dummy.root.rect()
        dialog.accept()
    QTimer.singleShot(0, inspect_and_close)
    assert MainWindow.run_modal(dummy, dialog) == QDialog.Accepted
    assert not dummy.modal_overlay.isVisible()
    assert dummy._modal_depth == 0
    dummy.root.close()
