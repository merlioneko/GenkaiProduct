"""Explicit live-server verification (not included in unittest discovery)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from character_maker.gateway import Gateway
from character_maker.generation import Editor, messages
from character_maker.models import CustomField
from character_maker.storage import save_document, read_document, write_text
from character_maker.exporters import markdown, novelwriter
from character_maker.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])
APP.setApplicationName('GenkaiCharacterMakerVerification')
OUT = ROOT / 'creations' / 'verification'
OUT.mkdir(parents=True, exist_ok=True)
settings = {'base_url': 'http://127.0.0.1:8080/v1', 'model': '',
            'temperature': .7, 'max_tokens': 8192, 'timeout': 300}
gateway = Gateway()


def call(payload=None):
    loop = QEventLoop()
    result = {}
    def success(token, data):
        result['data'] = data
        loop.quit()
    def failure(token, error):
        result['error'] = error
        loop.quit()
    gateway.succeeded.connect(success)
    gateway.failed.connect(failure)
    start = monotonic()
    gateway.send(str(uuid4()), settings, payload)
    loop.exec()
    gateway.succeeded.disconnect(success)
    gateway.failed.disconnect(failure)
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result['data'], round(monotonic() - start, 2)


report = {'server': settings['base_url'], 'mode': 'plain JSON, stream=false', 'steps': []}
try:
    models, seconds = call()
    settings['model'] = models['data'][0]['id']
    report['model'] = settings['model']
    editor = Editor()
    data = editor.doc.model_dump()
    data['idea'] = '明るく人懐っこい魔女。ただし、自分の命にはほとんど執着がない'
    data['custom_fields'] = [CustomField(label='特殊能力').model_dump(), CustomField(label='所属組織').model_dump()]
    editor.change(data)
    targets = [(None, ''), (('basic', 'background'), '診療所育ちではなく、港町で育った過去にしてください'),
               (('custom', editor.doc.custom_fields[0].id), '能力の発動に明確な制約を追加してください')]
    for index, (target, instruction) in enumerate(targets):
        before = editor.doc.model_dump()
        request = editor.begin(target)
        payload = {k: settings[k] for k in ('model', 'temperature', 'max_tokens')}
        payload.update(stream=False, messages=messages(editor.doc, target, instruction))
        envelope, seconds = call(payload)
        write_text(OUT / f'response-{index}.json', json.dumps(envelope, ensure_ascii=False, indent=2))
        editor.receive(request, envelope)
        assert editor.doc.model_dump() == before
        editor.apply()
        after = editor.doc.model_dump()
        if target:
            expected = json.loads(json.dumps(before))
            expected['updated_at'] = after['updated_at']
            if target[0] == 'basic':
                expected['character'][target[1]] = after['character'][target[1]]
            else:
                expected['custom_fields'][0]['value'] = after['custom_fields'][0]['value']
            assert after == expected, 'Target-external data changed'
        report['steps'].append({'target': target or 'full', 'seconds': seconds, 'result': 'PASS'})
        print(json.dumps(report['steps'][-1], ensure_ascii=False), flush=True)
    save_document(OUT / 'character.gcm.json', editor.doc)
    assert read_document(OUT / 'character.gcm.json') == editor.doc
    write_text(OUT / 'character.md', markdown(editor.doc))
    write_text(OUT / 'character.novelwriter.json', json.dumps(novelwriter(editor.doc), ensure_ascii=False, indent=2))
    window = MainWindow()
    window.editor.replace(editor.doc)
    window.render()
    window.show()
    APP.processEvents()
    assert window.grab().save(str(OUT / 'window.png'))
    window.editor.dirty = False
    window.close()
    report['result'] = 'PASS'
except Exception as exc:
    report['result'] = 'FAIL'
    report['error'] = str(exc)
    raise
finally:
    write_text(OUT / 'report.json', json.dumps(report, ensure_ascii=False, indent=2))
