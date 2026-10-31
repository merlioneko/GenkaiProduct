import os
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase


def configure_font(app):
    # Qt's offscreen Windows plugin has no system font enumeration. Load the
    # installed Japanese font explicitly so previews and the app use the same text.
    if os.name == 'nt':
        if 'Meiryo UI' not in QFontDatabase.families():
            font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'meiryo.ttc'
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
        if 'Meiryo UI' in QFontDatabase.families():
            app.setFont(QFont('Meiryo UI', 10))
