"""Translations loaded from translations/<language>.yaml."""
from __future__ import annotations
from pathlib import Path
from datetime import date
import yaml

TRANSLATIONS = Path(__file__).resolve().parent.parent / 'translations'


class Translator:
    def __init__(self, language: str = 'en'):
        self.language = language
        self.translations = self._read('en')
        if language != 'en':
            self.translations.update(self._read(language))

    @staticmethod
    def _read(language: str) -> dict[str, str]:
        if not language or not all(c.isalnum() or c in '_-' for c in language):
            raise ValueError('Invalid language identifier')
        path = TRANSLATIONS / f'{language}.yaml'
        if not path.is_file():
            if language == 'en':
                raise FileNotFoundError(path)
            raise FileNotFoundError(f'Language file not found: {path}')
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if not isinstance(data, dict):
            raise ValueError(f'Translation must be a YAML mapping: {path}')
        return {str(k): str(v) for k, v in data.items()}

    def t(self, key: str, **kwargs) -> str:
        return self.translations.get(key, key).format(**kwargs)

    def format_date(self, value: date) -> str:
        """Date with translated day/month names, independent of installed OS locales.

        Use literal square brackets around the month name as requested.
        Python's weekday(): Monday=0, Sunday=6.
        """
        weekdays = ('monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday')
        months = ('january', 'february', 'march', 'april', 'may', 'june',
                  'july', 'august', 'september', 'october', 'november', 'december')
        weekday_name = self.t(f'weekday_{weekdays[value.weekday()]}')
        month_name = self.t(f'month_{months[value.month - 1]}')
        return f'{weekday_name} | {value.day}. {value.month}. [{month_name}] {value.year}'

    @staticmethod
    def available() -> list[str]:
        return sorted(x.stem for x in TRANSLATIONS.glob('*.yaml') if x.stem != 'example')
