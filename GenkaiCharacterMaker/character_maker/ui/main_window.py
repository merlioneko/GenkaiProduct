import json
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QElapsedTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QScrollArea, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QListWidget, QInputDialog, QMessageBox, QFileDialog)
from ..models import Document, CustomField
from ..generation import Editor, messages
from ..gateway import Gateway
from ..storage import save_document, read_document, write_text
from ..exporters import LABELS, markdown, novelwriter
from ..settings import read_settings
from .settings_dialog import SettingsDialog
from .theme import configure_font

ROOT = Path(__file__).resolve().parents[2]


class SpeechEditor(QWidget):
    def __init__(self, values, changed):
        super().__init__()
        self.changed = changed
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        self.items.setMaximumHeight(110)
        self.items.addItems(values)
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(90)
        self.items.currentRowChanged.connect(self.select)
        self.text.textChanged.connect(self.edit)
        layout.addWidget(self.items)
        layout.addWidget(self.text)
        buttons = QHBoxLayout()
        for label, callback in [('台詞を追加', self.add), ('台詞を削除', self.remove)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.items.setCurrentRow(0)

    def values(self):
        return [self.items.item(i).text() for i in range(self.items.count())]

    def select(self, row):
        self.text.blockSignals(True)
        self.text.setPlainText(self.items.item(row).text() if row >= 0 else '')
        self.text.setEnabled(row >= 0)
        self.text.blockSignals(False)

    def edit(self):
        item = self.items.currentItem()
        if item:
            item.setText(self.text.toPlainText())
            self.changed()

    def add(self):
        self.items.addItem('')
        self.items.setCurrentRow(self.items.count() - 1)
        self.changed()

    def remove(self):
        self.items.takeItem(self.items.currentRow())
        self.changed()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        configure_font(QApplication.instance())
        self.editor = Editor()
        self.path = None
        self.settings = read_settings()
        self.gateway = Gateway(self)
        self.gateway.succeeded.connect(self.received)
        self.gateway.failed.connect(self.failed)
        self.setMinimumSize(850, 650)
        self.resize(1200, 900)
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.progress)
        self.render()

    def button(self, label, callback, layout):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def render(self):
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()
        central = QWidget()
        layout = QVBoxLayout(central)
        self.toolbar = QWidget()
        tools = QHBoxLayout(self.toolbar)
        for label, callback in [('新規', self.new), ('開く', self.open), ('保存', self.save),
                ('名前を付けて保存', lambda: self.save(True)),
                ('Markdown出力', lambda: self.export('md')),
                ('Markdownコピー', self.copy_markdown), ('5項目JSON', lambda: self.export('json')),
                ('接続設定', self.configure)]:
            self.button(label, callback, tools)
        layout.addWidget(self.toolbar)
        self.body = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel('人物イメージ'))
        self.idea = QPlainTextEdit(self.editor.doc.idea)
        self.idea.setPlaceholderText('明るく人懐っこい魔女。ただし、自分の命にはほとんど執着がない')
        self.idea.textChanged.connect(self.sync)
        left_layout.addWidget(self.idea)
        self.button('全体を生成', lambda: self.generate(None), left_layout)
        self.body.addWidget(left)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form = QWidget()
        form_layout = QVBoxLayout(form)
        self.fields = {}
        self.custom_text = {}
        for key, label in LABELS.items():
            box = QGroupBox(label)
            bl = QVBoxLayout(box)
            self.button('生成・再生成', lambda _=False, k=key: self.generate(('basic', k)), bl)
            value = getattr(self.editor.doc.character, key)
            if key == 'speech_examples':
                widget = SpeechEditor(value, self.sync)
            elif key == 'name':
                widget = QLineEdit(value)
                widget.textChanged.connect(self.sync)
            else:
                widget = QPlainTextEdit(value)
                widget.setMinimumHeight(90)
                widget.setMaximumHeight(160)
                widget.textChanged.connect(self.sync)
            self.fields[key] = widget
            bl.addWidget(widget)
            form_layout.addWidget(box)
        self.button('＋自由項目を追加', self.add_custom, form_layout)
        for item in self.editor.doc.custom_fields:
            box = QGroupBox(item.label)
            bl = QVBoxLayout(box)
            row = QHBoxLayout()
            for label, callback in [
                ('生成・再生成', lambda _=False, i=item.id: self.generate(('custom', i))),
                ('改名', lambda _=False, i=item.id: self.rename_custom(i)),
                ('↑', lambda _=False, i=item.id: self.move_custom(i, -1)),
                ('↓', lambda _=False, i=item.id: self.move_custom(i, 1)),
                ('削除', lambda _=False, i=item.id: self.delete_custom(i))]:
                self.button(label, callback, row)
            bl.addLayout(row)
            widget = QPlainTextEdit(item.value)
            widget.setMinimumHeight(90)
            widget.setMaximumHeight(160)
            widget.textChanged.connect(self.sync)
            self.custom_text[item.id] = widget
            bl.addWidget(widget)
            form_layout.addWidget(box)
        form_layout.addStretch()
        scroll.setWidget(form)
        self.body.addWidget(scroll)
        self.body.setSizes([300, 850])
        layout.addWidget(self.body, 1)
        self.review = QGroupBox('生成候補の確認')
        rl = QVBoxLayout(self.review)
        pair = QHBoxLayout()
        self.before = QPlainTextEdit()
        self.after = QPlainTextEdit()
        for title, widget in [('現在の内容', self.before), ('提案された内容', self.after)]:
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            widget.setReadOnly(True)
            col.addWidget(widget)
            pair.addLayout(col)
        rl.addLayout(pair)
        row = QHBoxLayout()
        self.button('適用', self.apply, row)
        self.button('破棄', self.cancel, row)
        rl.addLayout(row)
        layout.addWidget(self.review)
        self.review.hide()
        self.cancel_button = self.button('生成をキャンセル', self.cancel, layout)
        self.cancel_button.hide()
        self.setCentralWidget(central)
        self.update_title()
        self.statusBar().showMessage(self.connection_text())

    def connection_text(self):
        return f"{self.settings['base_url']} / {self.settings['model'] or 'モデル未選択'}"

    def update_title(self):
        self.setWindowTitle(f"GenkaiCharacterMaker — {self.editor.doc.character.name or '未命名'}" +
                            (' ＊未保存' if self.editor.dirty else ''))

    def error(self, exc, detail=''):
        box = QMessageBox(QMessageBox.Icon.Warning, '操作を完了できませんでした', str(exc), parent=self)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def sync(self):
        if self.editor.request:
            return
        data = self.editor.doc.model_dump()
        data['idea'] = self.idea.toPlainText()
        for key, widget in self.fields.items():
            data['character'][key] = (widget.values() if key == 'speech_examples' else
                                      widget.text() if key == 'name' else widget.toPlainText())
        for item in data['custom_fields']:
            item['value'] = self.custom_text[item['id']].toPlainText()
        self.editor.change(data)
        self.update_title()

    def mutate_custom(self, change):
        try:
            data = self.editor.doc.model_dump()
            change(data['custom_fields'])
            self.editor.change(data)
            self.render()
        except Exception as exc:
            self.error(exc)

    def add_custom(self):
        label, ok = QInputDialog.getText(self, '自由項目を追加', '項目名')
        if ok:
            try:
                item = CustomField(label=label)
                self.mutate_custom(lambda fields: fields.append(item.model_dump()))
            except Exception as exc:
                self.error(exc)

    def rename_custom(self, field_id):
        item = next(f for f in self.editor.doc.custom_fields if f.id == field_id)
        label, ok = QInputDialog.getText(self, '項目名を変更', '項目名', text=item.label)
        if ok:
            self.mutate_custom(lambda fields: next(f for f in fields if f['id'] == field_id).update(label=label))

    def move_custom(self, field_id, delta):
        def move(fields):
            i = next(i for i, f in enumerate(fields) if f['id'] == field_id)
            j = i + delta
            if 0 <= j < len(fields):
                fields[i], fields[j] = fields[j], fields[i]
        self.mutate_custom(move)

    def delete_custom(self, field_id):
        if QMessageBox.question(self, '自由項目を削除', 'この項目と本文を削除しますか？') == QMessageBox.StandardButton.Yes:
            self.mutate_custom(lambda fields: fields.remove(next(f for f in fields if f['id'] == field_id)))

    def guard(self):
        if not self.editor.dirty:
            return True
        result = QMessageBox.question(self, '未保存の変更', '変更を保存しますか？',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return self.save() if result == QMessageBox.StandardButton.Save else result == QMessageBox.StandardButton.Discard

    def new(self):
        if self.guard():
            self.editor.replace(Document())
            self.path = None
            self.render()

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, 'キャラクターを開く', str(ROOT / 'creations/characters'), 'JSON (*.json)')
        if path:
            try:
                doc = read_document(path)
                if self.guard():
                    self.editor.replace(doc)
                    self.path = Path(path)
                    self.render()
            except Exception as exc:
                self.error(exc)

    def save(self, save_as=False):
        path = None if save_as else self.path
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, 'JSONを保存',
                str(ROOT / 'creations/characters' / (self.editor.doc.id + '.gcm.json')), 'JSON (*.json)')
        if not path:
            return False
        try:
            save_document(path, self.editor.doc)
            self.path = Path(path)
            self.editor.dirty = False
            self.update_title()
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def export(self, kind):
        try:
            text = markdown(self.editor.doc) if kind == 'md' else json.dumps(novelwriter(self.editor.doc), ensure_ascii=False, indent=2) + '\n'
            path, _ = QFileDialog.getSaveFileName(self, '外部出力',
                str(ROOT / 'creations' / (self.editor.doc.id + ('.md' if kind == 'md' else '.novelwriter.json'))),
                'Markdown (*.md)' if kind == 'md' else 'JSON (*.json)')
            if path:
                if self.path and Path(path).resolve() == self.path.resolve():
                    raise ValueError('保存用JSONとは別のファイル名を指定してください')
                write_text(path, text)
                self.statusBar().showMessage('出力しました: ' + path)
        except Exception as exc:
            self.error(exc)

    def copy_markdown(self):
        QApplication.clipboard().setText(markdown(self.editor.doc))
        self.statusBar().showMessage('Markdownをコピーしました')

    def configure(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.result_settings
            self.statusBar().showMessage(self.connection_text())

    def lock(self, busy):
        # Keep scrolling and text selection available during generation/review.
        for button in self.body.findChildren(QPushButton):
            button.setEnabled(not busy)
        for widget in self.body.findChildren(QPlainTextEdit):
            widget.setReadOnly(busy)
        for widget in self.body.findChildren(QLineEdit):
            widget.setReadOnly(busy)
        self.toolbar.setEnabled(not busy)
        self.cancel_button.setVisible(busy and self.editor.candidate is None)

    def generate(self, target):
        if not self.settings['model']:
            self.configure()
            if not self.settings['model']:
                return
        instruction = ''
        if target:
            instruction, ok = QInputDialog.getMultiLineText(self, '生成・再生成', 'この項目への指示（空欄でも生成できます）')
            if not ok:
                return
        elif not self.editor.doc.idea.strip():
            self.error('人物イメージを入力してください')
            return
        try:
            req = self.editor.begin(target)
            payload = {k: self.settings[k] for k in ('model', 'temperature', 'max_tokens')}
            payload.update(stream=False, messages=messages(self.editor.doc, target, instruction))
            self.gateway.send(req.id, self.settings, payload)
            self.lock(True)
            self.elapsed.start()
            self.timer.start(1000)
            self.progress()
        except Exception as exc:
            self.cancel()
            self.error(exc)

    def progress(self):
        self.statusBar().showMessage(f'生成中… {self.elapsed.elapsed() // 1000}秒 / {self.connection_text()}')

    def received(self, token, data):
        req = self.editor.request
        if not req or req.id != token:
            return
        self.timer.stop()
        try:
            if not self.editor.receive(req, data):
                return
            def display(doc):
                if req.target is None:
                    return markdown(doc)
                kind, key = req.target
                value = getattr(doc.character, key) if kind == 'basic' else next(f.value for f in doc.custom_fields if f.id == key)
                return '\n\n'.join(value) if isinstance(value, list) else value
            self.before.setPlainText(display(self.editor.doc))
            self.after.setPlainText(display(self.editor.candidate))
            label = '全体'
            if req.target:
                kind, key = req.target
                label = LABELS[key] if kind == 'basic' else next(f.label for f in self.editor.doc.custom_fields if f.id == key)
            self.review.setTitle('生成候補の確認 — ' + label)
            self.review.show()
            self.cancel_button.hide()
            self.statusBar().showMessage('候補を確認して、適用または破棄してください')
        except Exception as exc:
            self.cancel()
            self.error(exc, json.dumps(data, ensure_ascii=False, indent=2))

    def failed(self, token, error):
        if self.editor.request and self.editor.request.id == token:
            self.cancel()
            self.error(error)

    def cancel(self):
        self.editor.cancel()
        self.gateway.cancel()
        self.timer.stop()
        self.review.hide()
        self.lock(False)
        self.statusBar().showMessage(self.connection_text())

    def apply(self):
        try:
            self.editor.apply()
            self.render()
        except Exception as exc:
            self.cancel()
            self.error(exc)

    def closeEvent(self, event):
        self.cancel()
        if self.guard():
            event.accept()
        else:
            event.ignore()
