#!/usr/bin/env python3
"""Run the Raspberry Pi touchscreen player."""
import argparse
import os
from pathlib import Path
import sys

from touchplayer.config import Config


def main():
    parser = argparse.ArgumentParser(description='Touchscreen music and audiobook player')
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')),
                        help='Path to YAML configuration (created if absent)')
    parser.add_argument('--windowed', action='store_true', help='Override startup full-screen setting')
    parser.add_argument('--no-web', action='store_true', help='Disable the LAN controller for this run')
    args = parser.parse_args()
    try:
        config = Config(args.config)
    except Exception as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        return 2
    if args.no_web:
        config.data['web']['enabled'] = False
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import QApplication, QMessageBox
    # These flags must be configured before constructing QApplication in Qt 5.
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Touch Audio')
    try:
        from touchplayer.ui import MainWindow
        window = MainWindow(config)
    except Exception as exc:
        QMessageBox.critical(None, 'Touch Audio – startup error', f'{type(exc).__name__}: {exc}')
        print(f'Startup error: {exc}', file=sys.stderr)
        return 1
    if config.data.get('fullscreen', True) and not args.windowed:
        window.showFullScreen()
    else:
        available = app.primaryScreen().availableGeometry()
        width, height = min(1130, available.width() - 24), min(730, available.height() - 24)
        window.resize(max(400, width), max(300, height))
        window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
