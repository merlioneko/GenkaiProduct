import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from character_maker.ui.main_window import MainWindow
from character_maker.models import CustomField
from test.test_core import envelope

APP = QApplication.instance() or QApplication([])
APP.setApplicationName('GenkaiCharacterMakerTests')


class UiTests(unittest.TestCase):
    def setUp(self):
        with patch('character_maker.ui.main_window.read_settings', return_value={
                'base_url': 'http://127.0.0.1:8080/v1', 'model': 'test',
                'temperature': .7, 'max_tokens': 2048, 'timeout': 180}):
            self.window = MainWindow()
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.editor.dirty = False
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_edit_and_speech_multiline(self):
        w = self.window
        w.fields['name'].setText('魔女')
        speech = w.fields['speech_examples']
        speech.add()
        speech.text.setPlainText('台詞\n続き')
        self.assertEqual(w.editor.doc.character.speech_examples, ['台詞\n続き'])
        self.assertTrue(w.editor.dirty)

    def test_custom_add_rename_move_delete(self):
        w = self.window
        with patch('character_maker.ui.main_window.QInputDialog.getText', return_value=('特殊能力', True)):
            w.add_custom()
        first = w.editor.doc.custom_fields[0].id
        with patch('character_maker.ui.main_window.QInputDialog.getText', return_value=('所属', True)):
            w.add_custom()
        with patch('character_maker.ui.main_window.QInputDialog.getText', return_value=('固有魔法', True)):
            w.rename_custom(first)
        w.move_custom(first, 1)
        self.assertEqual(w.editor.doc.custom_fields[1].id, first)
        self.assertEqual(w.editor.doc.custom_fields[1].label, '固有魔法')
        with patch('character_maker.ui.main_window.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            w.delete_custom(first)
        self.assertEqual(len(w.editor.doc.custom_fields), 1)

    def test_generation_review_and_cancel(self):
        w = self.window
        with patch.object(w.gateway, 'send'), patch('character_maker.ui.main_window.QInputDialog.getMultiLineText', return_value=('補足を追加', True)):
            w.generate(('basic', 'notes'))
        self.assertTrue(w.idea.isReadOnly())
        self.assertTrue(w.body.widget(1).isEnabled())
        token = w.editor.request.id
        w.received(token, envelope({'notes': '候補'}))
        self.assertTrue(w.review.isVisible())
        self.assertEqual(w.editor.doc.character.notes, '')
        w.cancel()
        self.assertEqual(w.editor.doc.character.notes, '')
        self.assertTrue(w.body.isEnabled())
        self.assertFalse(w.idea.isReadOnly())
        w.received(token, envelope({'notes': '遅延'}))
        self.assertEqual(w.editor.doc.character.notes, '')

    def test_failed_save_does_not_allow_switch(self):
        w = self.window
        w.fields['name'].setText('編集中')
        w.path = Path('unwritable.json')
        with patch('character_maker.ui.main_window.QMessageBox.question', return_value=QMessageBox.StandardButton.Save), patch('character_maker.ui.main_window.save_document', side_effect=OSError('denied')), patch.object(w, 'error'):
            w.new()
        self.assertEqual(w.editor.doc.character.name, '編集中')
        self.assertTrue(w.editor.dirty)

    def test_invalid_open_keeps_current_document(self):
        w = self.window
        w.fields['name'].setText('保持する人物')
        before = w.editor.doc.model_dump()
        with patch('character_maker.ui.main_window.QFileDialog.getOpenFileName', return_value=('bad.json', '')), patch('character_maker.ui.main_window.read_document', side_effect=ValueError('bad JSON')), patch.object(w, 'error'):
            w.open()
        self.assertEqual(w.editor.doc.model_dump(), before)
        self.assertTrue(w.editor.dirty)

    def test_copy_does_not_mark_document_saved(self):
        w = self.window
        w.fields['name'].setText('コピー例')
        before = w.editor.doc.model_dump()
        w.copy_markdown()
        self.assertIn('コピー例', APP.clipboard().text())
        self.assertEqual(w.editor.doc.model_dump(), before)
        self.assertTrue(w.editor.dirty)


if __name__ == '__main__':
    unittest.main()
