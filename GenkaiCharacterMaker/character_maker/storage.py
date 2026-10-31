from pathlib import Path
from PySide6.QtCore import QSaveFile, QIODevice
from .models import load_document


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file = QSaveFile(str(path))
    file.setDirectWriteFallback(False)
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    data = text.encode('utf-8')
    if file.write(data) != len(data):
        file.cancelWriting()
        raise OSError(file.errorString())
    if not file.commit():
        raise OSError(file.errorString())


def read_document(path):
    return load_document(Path(path).read_text(encoding='utf-8'))


def save_document(path, doc):
    # Validate the exact file representation before replacing an existing file.
    text = doc.model_dump_json(indent=2) + '\n'
    load_document(text)
    write_text(path, text)
