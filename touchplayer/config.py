"""YAML settings and per-user UI state."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import secrets
import tempfile
import yaml

from .scale import DEFAULT_SCALE, validate_scale

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    'language': 'en',
    'group_folders': ['~/audio'],
    'direct_folders': {},
    'category_folders': {},  # Extra folders under a named category; paths may be lists.
    'categoryless': False,
    'scan_on_startup': True,
    'display': {'auto_dim': True, 'idle_seconds': 60, 'dim_percent': 40, 'backend': 'auto', 'device': ''},
    'browse_text_scale': 1.25,
    'metadata': {
        'folder_name': True, 'folder_album': True, 'folder_artist': True,
        'file_name': True, 'file_title': True, 'file_artist': False,
    },
    'fullscreen': True,
    'ui_scale': DEFAULT_SCALE,
    'text_scale': DEFAULT_SCALE,
    'volume': 70,
    'cache_db': '~/.cache/touch_audio_player/library.sqlite3',
    'state_file': '~/.local/state/touch_audio_player/state.yaml',
    'web': {'enabled': True, 'host': '0.0.0.0', 'port': 8765, 'token': ''},
}


def expand_path(value: str) -> Path:
    """Resolve ~ and environment variables, without needing the path to exist."""
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def atomic_yaml_save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)



def _merge_roundtrip(current, desired):
    """Modify only settings that changed; preserve comments, spacing and order."""
    from collections.abc import MutableMapping, MutableSequence
    if isinstance(current, MutableMapping) and isinstance(desired, dict):
        for key in list(current):
            if key not in desired:
                del current[key]
        for key, value in desired.items():
            if key not in current:
                current[key] = value
            elif current[key] != value:
                if isinstance(current[key], MutableMapping) and isinstance(value, dict):
                    _merge_roundtrip(current[key], value)
                elif isinstance(current[key], MutableSequence) and isinstance(value, list):
                    current[key][:] = value
                else:
                    current[key] = value


def save_config_yaml(path: Path, data: dict) -> None:
    """Atomically save settings while preserving user-supplied YAML comments.

    ruamel.yaml is required: falling back to PyYAML would silently discard
    comments, so missing installations are reported clearly instead.
    """
    try:
        from ruamel.yaml import YAML
    except ImportError as exc:
        raise RuntimeError('Comment-preserving YAML requires ruamel.yaml. '
                           'Install with: sudo apt install python3-ruamel.yaml') from exc
    parser = YAML(typ='rt')
    parser.preserve_quotes = True
    parser.width = 4096
    original = path.read_text(encoding='utf-8') if path.exists() else ''
    document = parser.load(original) if original.strip() else None
    if document is None:
        from ruamel.yaml.comments import CommentedMap
        document = CommentedMap()
    if not isinstance(document, dict):
        raise ValueError(f'Expected a YAML mapping in {path}')
    _merge_roundtrip(document, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            parser.dump(document, handle)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f'Expected a YAML mapping in {path}')
    return data


class Config:
    def __init__(self, path: str | Path):
        self.path = expand_path(str(path))
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            save_config_yaml(self.path, self.data)
        loaded = load_yaml(self.path)
        for k, v in loaded.items():
            if k in ('web', 'metadata', 'display') and isinstance(v, dict):
                self.data[k].update(v)
            else:
                self.data[k] = v
        if not isinstance(self.data.get('group_folders'), list):
            raise ValueError('group_folders must be a YAML list')
        if not isinstance(self.data.get('direct_folders'), dict):
            raise ValueError('direct_folders must be a YAML dictionary')
        if not isinstance(self.data.get('category_folders'), dict):
            raise ValueError('category_folders must be a YAML mapping of category to path or list of paths')
        for category, paths in self.data['category_folders'].items():
            if not str(category).strip() or not isinstance(paths, (str, list)) or (isinstance(paths, list) and not all(isinstance(p, str) for p in paths)):
                raise ValueError('category_folders values must be a path or list of paths')
        if not isinstance(self.data.get('metadata'), dict):
            raise ValueError('metadata must be a YAML dictionary')
        if not isinstance(self.data.get('web'), dict):
            raise ValueError('web must be a YAML dictionary')
        self.data['ui_scale'] = validate_scale(self.data.get('ui_scale'), 'ui_scale')
        self.data['text_scale'] = validate_scale(self.data.get('text_scale'), 'text_scale')
        self.data['browse_text_scale'] = validate_scale(self.data.get('browse_text_scale'), 'browse_text_scale')
        if not isinstance(self.data.get('display'), dict):
            raise ValueError('display must be a YAML mapping')
        disp = self.data['display']
        disp['auto_dim'] = bool(disp.get('auto_dim', True))
        disp['idle_seconds'] = int(disp.get('idle_seconds', 60))
        disp['dim_percent'] = int(disp.get('dim_percent', 40))
        if not 5 <= disp['idle_seconds'] <= 86400:
            raise ValueError('display.idle_seconds must be between 5 and 86400')
        if not 10 <= disp['dim_percent'] <= 100:
            raise ValueError('display.dim_percent must be between 10 and 100')
        if disp.get('backend', 'auto') not in ('auto', 'hardware', 'software'):
            raise ValueError('display.backend must be auto, hardware or software')
        disp['device'] = str(disp.get('device', '') or '')
        if '/' in disp['device'] or disp['device'] in ('.', '..'):
            raise ValueError('display.device must be a device name, not a path')
        self.data['categoryless'] = bool(self.data.get('categoryless', False))
        self.data['scan_on_startup'] = bool(self.data.get('scan_on_startup', True))
        if not str(self.data['web'].get('token') or '').strip():
            self.data['web']['token'] = secrets.token_urlsafe(28)
            self.save()

    def save(self) -> None:
        save_config_yaml(self.path, self.data)


class StateStore:
    def __init__(self, path: str):
        self.path = expand_path(path)
        self.data = load_yaml(self.path)

    def update(self, **kwargs) -> None:
        changed = {key: value for key, value in kwargs.items() if self.data.get(key) != value}
        if changed:
            self.data.update(changed)
            atomic_yaml_save(self.path, self.data)
