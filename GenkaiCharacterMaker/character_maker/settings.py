from pathlib import Path
from PySide6.QtCore import QStandardPaths
from .models import strict_json
from .storage import write_text
import json

DEFAULTS = {'base_url': 'http://127.0.0.1:8080/v1', 'model': '',
            'temperature': 0.7, 'max_tokens': 8192, 'timeout': 300}


def settings_path():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)) / 'settings.json'


def read_settings():
    result = dict(DEFAULTS)
    try:
        data = strict_json(settings_path().read_text(encoding='utf-8'))
        for key, default in DEFAULTS.items():
            if key in data and type(data[key]) is type(default):
                result[key] = data[key]
    except (OSError, ValueError, TypeError):
        pass
    return result


def save_settings(settings):
    write_text(settings_path(), json.dumps({k: settings[k] for k in DEFAULTS}, ensure_ascii=False, indent=2))
