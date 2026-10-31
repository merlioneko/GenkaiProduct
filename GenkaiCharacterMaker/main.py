import sys
from PySide6.QtWidgets import QApplication
from character_maker.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName('GenkaiProduct')
    app.setApplicationName('GenkaiCharacterMaker')
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
