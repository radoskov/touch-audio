"""Media discovery and metadata index; safe to run in a background thread."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import sqlite3
from typing import Optional

from .config import expand_path

AUDIO_EXTS = {'.mp3', '.flac', '.ogg', '.opus', '.wav', '.m4a', '.mp4', '.aac', '.wma', '.aiff', '.aif', '.alac'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
COVER_STEMS = ('cover', 'folder', 'front', 'album', 'artwork', 'albumart')


def natural_key(text: str):
    return [int(s) if s.isdigit() else s.casefold() for s in re.split(r'(\d+)', text)]


def stable_id(path: Path, category: str = '') -> str:
    return hashlib.sha256((category.casefold() + '\0' + str(path.resolve())).encode('utf-8')).hexdigest()[:20]


@dataclass
class Track:
    path: str
    filename: str
    relative_path: str
    title: str = ''
    album: str = ''
    artist: str = ''
    duration: float = 0.0

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass
class Entry:
    id: str
    path: str
    folder_name: str
    category: str
    album_title: str = ''
    artist: str = ''
    cover: str = ''
    tracks: list[Track] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.album_title or self.folder_name

    @property
    def subtitle(self) -> str:
        detail = self.album_title if self.album_title and self.album_title.casefold() != self.folder_name.casefold() else ''
        return self.folder_name + (f'  |  {detail}' if detail else '')

    def as_dict(self, include_tracks: bool = False) -> dict:
        result = {'id': self.id, 'folder_name': self.folder_name,
                  'album_title': self.album_title, 'display_name': self.display_name,
                  'subtitle': self.subtitle, 'artist': self.artist,
                  'category': self.category, 'track_count': len(self.tracks),
                  'has_cover': bool(self.cover)}
        if include_tracks:
            result['tracks'] = [t.as_dict() for t in self.tracks]
        return result


@dataclass
class Category:
    name: str
    entries: list[Entry] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {'name': self.name, 'entry_count': len(self.entries),
                'track_count': sum(len(e.tracks) for e in self.entries)}


@dataclass
class Library:
    categories: dict[str, Category] = field(default_factory=dict)
    by_id: dict[str, Entry] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _entries_cache: list[Entry] | None = field(default=None, repr=False, compare=False)

    def category(self, name: str) -> Optional[Category]:
        return self.categories.get(name.casefold())

    def all_entries(self) -> list[Entry]:
        # Immutable catalogue between scans: one flattening instead of one per search.
        if self._entries_cache is None:
            self._entries_cache = [e for c in self.categories.values() for e in c.entries]
        return self._entries_cache

    def search(self, query: str, max_results: int = 60) -> list[dict]:
        terms = query.casefold().split()
        if not terms:
            return []
        matches = []
        for e in self.all_entries():
            entry_text = ' '.join((e.folder_name, e.album_title, e.artist, e.category)).casefold()
            if all(t in entry_text for t in terms):
                matches.append({'type': 'entry', 'entry': e.as_dict()})
            for i, track in enumerate(e.tracks):
                track_text = ' '.join((track.filename, track.relative_path, track.title,
                                       track.album, track.artist, e.folder_name, e.album_title)).casefold()
                if all(t in track_text for t in terms):
                    matches.append({'type': 'track', 'entry': e.as_dict(), 'file_index': i,
                                    'file': track.as_dict()})
            if len(matches) >= max_results:
                return matches[:max_results]
        return matches


class MetadataCache:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        # This index can be rebuilt if the device loses power; reduce SD writes.
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self.conn.execute('PRAGMA cache_size=-4096')
        self.conn.execute('CREATE TABLE IF NOT EXISTS tags ('
                          'path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER,'
                          'title TEXT, album TEXT, artist TEXT)')

    def read(self, path: Path) -> tuple[str, str, str]:
        stat = path.stat()
        key = str(path)
        row = self.conn.execute('SELECT size, mtime_ns, title, album, artist FROM tags WHERE path=?',
                                (key,)).fetchone()
        if row and row[0] == stat.st_size and row[1] == stat.st_mtime_ns:
            return row[2] or '', row[3] or '', row[4] or ''
        title = album = artist = ''
        try:
            from mutagen import File
            tags = File(path, easy=True)
            if tags:
                title = str(tags.get('title', [''])[0])
                album = str(tags.get('album', [''])[0])
                artist = str(tags.get('artist', [''])[0])
        except Exception:
            pass  # Unsupported or corrupt files remain playable by VLC if possible.
        self.conn.execute('INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?)',
                          (key, stat.st_size, stat.st_mtime_ns, title, album, artist))
        return title, album, artist

    def close(self):
        self.conn.commit()
        self.conn.close()


def find_cover(folder: Path) -> str:
    try:
        images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    except OSError:
        return ''
    images.sort(key=lambda p: (next((i for i, name in enumerate(COVER_STEMS)
                                     if p.stem.casefold().startswith(name)), 100),
                                natural_key(p.name)))
    return str(images[0]) if images else ''


def snapshot_path(cache_db: str) -> Path:
    return expand_path(cache_db).with_suffix('.library.json')


def save_snapshot(library: Library, cache_db: str) -> None:
    """Store last successful catalogue for quick/offline starts without a new scan."""
    path = snapshot_path(cache_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'version': 1, 'categories': [
        {'name': category.name, 'entries': [asdict(entry) for entry in category.entries]}
        for category in library.categories.values()]}
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.touch-audio-',
                                         dir=path.parent, delete=False) as handle:
            temp = handle.name
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def load_snapshot(cache_db: str) -> Library:
    library = Library()
    path = snapshot_path(cache_db)
    if not path.exists():
        return library
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('version') != 1:
            return library
        for raw in payload.get('categories', []):
            category = Category(str(raw['name']))
            for record in raw['entries']:
                tracks = [Track(**track) for track in record['tracks']]
                entry = Entry(**{k: v for k, v in record.items() if k != 'tracks'}, tracks=tracks)
                category.entries.append(entry)
                library.by_id[entry.id] = entry
            library.categories[category.name.casefold()] = category
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return Library(warnings=[f'Unable to restore previous library index: {error}'])
    return library


def scan(group_folders: list[str], direct_folders: dict[str, str], cache_db: str,
         category_folders: dict[str, str | list[str]] | None = None,
         progress=None) -> Library:
    """Merge all three source types, reporting completed entries / total entries.

    Progress can temporarily be (0, 0) during directory discovery: indeterminate UI.
    """
    library = Library()
    jobs: list[tuple[str, Path, Path]] = []
    seen_per_category: set[tuple[str, str]] = set()
    if progress:
        progress(0, 0, 'Discovering folders')

    def register(category_name: str, category_path: Path):
        category_name = str(category_name).strip()
        if not category_name:
            return
        key = category_name.casefold()
        category = library.categories.setdefault(key, Category(category_name))
        if not category_path.is_dir():
            library.warnings.append(f'Missing category folder: {category_path}')
            return
        try:
            children = sorted(category_path.iterdir(), key=lambda p: natural_key(p.name))
        except OSError as error:
            library.warnings.append(f'Unable to read {category_path}: {error}')
            return
        roots = [p for p in children if p.is_dir() and not p.is_symlink()]
        if any(p.is_file() and p.suffix.lower() in AUDIO_EXTS for p in children):
            roots.insert(0, category_path)
        for root in roots:
            fingerprint = (key, str(root.resolve()))
            if fingerprint in seen_per_category:
                continue
            seen_per_category.add(fingerprint)
            jobs.append((category.name, category_path, root))

    for parent_text in group_folders:
        parent = expand_path(parent_text)
        if not parent.is_dir():
            library.warnings.append(f'Missing group folder: {parent}')
            continue
        try:
            children = sorted((p for p in parent.iterdir() if p.is_dir() and not p.is_symlink()),
                              key=lambda p: natural_key(p.name))
            for child in children:
                register(child.name, child)
        except OSError as error:
            library.warnings.append(f'Unable to read group folder {parent}: {error}')
    for name, path in direct_folders.items():
        register(str(name), expand_path(str(path)))
    for name, paths in (category_folders or {}).items():
        for path in ([paths] if isinstance(paths, str) else paths):
            register(str(name), expand_path(path))

    cache = MetadataCache(expand_path(cache_db))
    total = len(jobs)
    if progress:
        progress(0, total or 1, 'Reading audio tags')
    try:
        for count, (name, category_path, root) in enumerate(jobs, 1):
            try:
                files = sorted((p for p in root.rglob('*') if p.is_file() and
                                p.suffix.lower() in AUDIO_EXTS and not p.is_symlink()),
                               key=lambda p: natural_key(str(p.relative_to(root))))
                if root == category_path:
                    files = [p for p in files if p.parent == root]
                tracks = []
                for path in files:
                    title, album, artist = cache.read(path)
                    tracks.append(Track(str(path), path.name, str(path.relative_to(root)), title, album, artist))
                if tracks:
                    key = name.casefold()
                    category = library.categories[key]
                    album_title = next((t.album for t in tracks if t.album), '')
                    artist = next((t.artist for t in tracks if t.artist), '')
                    entry = Entry(stable_id(root, key), str(root), root.name, category.name,
                                  album_title, artist, find_cover(root), tracks)
                    category.entries.append(entry)
                    library.by_id[entry.id] = entry
            except (OSError, PermissionError) as error:
                library.warnings.append(f'Unable to scan {root}: {error}')
            if progress:
                progress(count, total or 1, root.name)
        for category in library.categories.values():
            category.entries.sort(key=lambda e: natural_key(e.folder_name))
    finally:
        cache.close()
    return library
