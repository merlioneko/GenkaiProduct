from uuid import uuid4
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QDialogButtonBox, QLabel)
from ..gateway import Gateway, base_url
from ..settings import save_settings


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('接続設定')
        self.resize(570, 360)
        self.result_settings = None
        layout = QFormLayout(self)
        self.url = QLineEdit(settings['base_url'])
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setEditText(settings['model'])
        self.key = QLineEdit(settings.get('api_key', ''))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(.1)
        self.temperature.setValue(settings['temperature'])
        self.tokens = QSpinBox()
        self.tokens.setRange(64, 131072)
        self.tokens.setValue(settings['max_tokens'])
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 3600)
        self.timeout.setSuffix(' 秒')
        self.timeout.setValue(settings['timeout'])
        for name, widget in [('接続先', self.url), ('モデルID', self.model),
                             ('認証（今回の起動中のみ）', self.key), ('temperature', self.temperature),
                             ('出力上限', self.tokens), ('要求の期限', self.timeout)]:
            layout.addRow(name, widget)
        self.fetch = QPushButton('接続確認・モデル一覧を取得')
        self.fetch.clicked.connect(self.fetch_models)
        layout.addRow(self.fetch)
        self.status = QLabel('モデルは一覧から選択、またはIDを入力してください。')
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.gateway = Gateway(self)
        self.gateway.succeeded.connect(self.received)
        self.gateway.failed.connect(self.failed)
        self.finished.connect(lambda _: self.gateway.cancel())

    def values(self):
        return {'base_url': base_url(self.url.text()), 'model': self.model.currentText().strip(),
                'api_key': self.key.text(), 'temperature': self.temperature.value(),
                'max_tokens': self.tokens.value(), 'timeout': self.timeout.value()}

    def fetch_models(self):
        try:
            self.gateway.send(str(uuid4()), self.values())
            self.fetch.setEnabled(False)
            self.status.setText('モデル一覧を取得中…')
        except Exception as exc:
            self.status.setText(str(exc))

    def received(self, token, data):
        self.fetch.setEnabled(True)
        current = self.model.currentText()
        try:
            ids = [m['id'] for m in data['data'] if isinstance(m.get('id'), str)]
            self.model.clear()
            self.model.addItems(ids)
            self.model.setCurrentIndex(-1)
            self.model.setEditText(current)
            self.status.setText(f'接続成功：{len(ids)}件。使用するモデルを選択してください。')
        except (KeyError, TypeError, AttributeError):
            self.status.setText('モデル一覧の形式が不正です。IDを手入力することもできます。')

    def failed(self, token, error):
        self.fetch.setEnabled(True)
        self.status.setText(error)

    def commit(self):
        try:
            values = self.values()
            save_settings(values)
            self.result_settings = values
            self.accept()
        except Exception as exc:
            self.status.setText(str(exc))
