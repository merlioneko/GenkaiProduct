import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from character_maker.models import Document, CustomField, load_document, strict_json
from character_maker.generation import Editor, parse_response
from character_maker.exporters import markdown, novelwriter
from character_maker.storage import save_document, read_document

ROOT = Path(__file__).resolve().parents[1]


def envelope(data, reason='stop'):
    return {'choices': [{'finish_reason': reason, 'message': {'content': json.dumps(data, ensure_ascii=False)}}]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.doc = read_document(ROOT / 'examples/character.gcm.json')

    def test_examples_match_exports(self):
        self.assertEqual(markdown(self.doc), (ROOT / 'examples/character.md').read_text(encoding='utf-8'))
        self.assertEqual(novelwriter(self.doc), json.loads((ROOT / 'examples/character.novelwriter.json').read_text(encoding='utf-8')))

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '日本語.json'
            save_document(path, self.doc)
            self.assertEqual(read_document(path), self.doc)

    def test_legacy_and_empty_draft(self):
        data = Document().model_dump()
        del data['custom_fields']
        self.assertEqual(load_document(json.dumps(data)).custom_fields, [])

    def test_invalid_documents(self):
        base = self.doc.model_dump()
        cases = []
        for key, val in [('schema_version', True), ('schema_version', 2), ('unknown', 1), ('custom_fields', None)]:
            data = copy.deepcopy(base)
            data[key] = val
            cases.append(data)
        for key, val in [('label', '  '), ('label', 'a\nb'), ('value', 1), ('id', 'bad')]:
            data = copy.deepcopy(base)
            data['custom_fields'][0][key] = val
            cases.append(data)
        for key in ('id', 'label'):
            data = copy.deepcopy(base)
            data['custom_fields'][1][key] = data['custom_fields'][0][key]
            cases.append(data)
        data = copy.deepcopy(base)
        del data['character']['notes']
        cases.append(data)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                load_document(json.dumps(case))

    def test_duplicate_json(self):
        with self.assertRaises(ValueError):
            strict_json('{"a":1,"a":2}')

    def test_each_basic_target_preserves_other_data(self):
        for key in type(self.doc.character).model_fields:
            value = ['新台詞\n二行目'] if key == 'speech_examples' else '新設定'
            result = parse_response(envelope({key: value}), self.doc, ('basic', key))
            expected = self.doc.model_dump()
            expected['character'][key] = value
            self.assertEqual(result.model_dump(), expected)

    def test_custom_target(self):
        field = self.doc.custom_fields[0]
        result = parse_response(envelope({'value': ''}), self.doc, ('custom', field.id))
        expected = self.doc.model_dump()
        expected['custom_fields'][0]['value'] = ''
        self.assertEqual(result.model_dump(), expected)

    def test_invalid_single_responses(self):
        for value in ({'background': '新', 'persona': '変更'}, {'background': 1}, {'background': ''}, {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_response(envelope(value), self.doc, ('basic', 'background'))
        for reason in ('length', 'tool_calls', None):
            with self.assertRaises(ValueError):
                parse_response(envelope({'background': '新'}, reason), self.doc, ('basic', 'background'))

    def whole(self):
        return {'character': self.doc.character.model_dump(),
                'custom_values': [{'id': f.id, 'value': '新' + f.label} for f in reversed(self.doc.custom_fields)]}

    def test_full_keeps_definitions_and_order(self):
        result = parse_response(envelope(self.whole()), self.doc, None)
        self.assertEqual([(f.id, f.label) for f in result.custom_fields], [(f.id, f.label) for f in self.doc.custom_fields])
        self.assertEqual([f.value for f in result.custom_fields], ['新' + f.label for f in self.doc.custom_fields])

    def test_full_rejects_unknown_duplicate_missing_ids(self):
        for mode in ('unknown', 'duplicate', 'missing', 'extra'):
            data = self.whole()
            if mode == 'unknown':
                data['custom_values'][0]['id'] = 'unknown'
            elif mode == 'duplicate':
                data['custom_values'][0]['id'] = data['custom_values'][1]['id']
            elif mode == 'missing':
                data['custom_values'].pop()
            else:
                data['custom_values'][0]['label'] = 'unexpected'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                parse_response(envelope(data), self.doc, None)

    def test_empty_custom_full(self):
        self.doc.custom_fields = []
        result = parse_response(envelope(self.whole()), self.doc, None)
        self.assertEqual(result.custom_fields, [])

    def test_stale_and_cancelled_response(self):
        editor = Editor()
        editor.replace(self.doc)
        req = editor.begin(('basic', 'notes'))
        editor.cancel()
        newer = editor.begin(('basic', 'notes'))
        self.assertFalse(editor.receive(req, envelope({'notes': 'old'})))
        self.assertEqual(editor.request, newer)
        editor.replace(self.doc)
        self.assertFalse(editor.receive(newer, envelope({'notes': 'old'})))

    def test_candidate_not_applied_until_apply(self):
        editor = Editor()
        editor.replace(self.doc)
        req = editor.begin(('basic', 'notes'))
        editor.receive(req, envelope({'notes': '新補足'}))
        self.assertEqual(editor.doc, self.doc)
        editor.apply()
        self.assertEqual(editor.doc.character.notes, '新補足')
        self.assertTrue(editor.dirty)
        self.assertEqual(editor.doc.id, self.doc.id)

    def test_save_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'doc.json'
            save_document(path, self.doc)
            before = path.read_bytes()
            with patch('character_maker.storage.QSaveFile') as factory:
                factory.return_value.open.return_value = False
                factory.return_value.errorString.return_value = 'denied'
                with self.assertRaises(OSError):
                    save_document(path, Document())
            self.assertEqual(path.read_bytes(), before)

    def test_export_empty_and_heading_escape(self):
        doc = Document(custom_fields=[CustomField(label='<魔法> & #能力', value='')])
        with self.assertRaises(ValueError):
            novelwriter(doc)
        doc.character.speech_examples = ['台詞']
        before = doc.model_dump()
        self.assertEqual(novelwriter(doc)['notes'], '## 自由項目\n\n### &lt;魔法&gt; &amp; \\#能力\n')
        self.assertIn('### &lt;魔法&gt;', markdown(doc))
        self.assertEqual(doc.model_dump(), before)


if __name__ == '__main__':
    unittest.main()
