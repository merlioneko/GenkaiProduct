import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from .models import Document, Profile, now, strict_json

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts'


@dataclass(frozen=True)
class Request:
    session: str
    revision: int
    target: tuple | None
    id: str


def messages(doc, target, instruction=''):
    prompt = (PROMPTS / ('generate.md' if target is None else 'regenerate.md')).read_text(encoding='utf-8')
    contract = {'character': doc.character.model_dump(),
                'custom_values': [{'id': f.id, 'value': '本文'} for f in doc.custom_fields]}
    if target:
        contract = {target[1] if target[0] == 'basic' else 'value':
                    ['台詞'] if target == ('basic', 'speech_examples') else '本文'}
    return [{'role': 'system', 'content': prompt + '\n応答の形式: ' + json.dumps(contract, ensure_ascii=False)},
            {'role': 'user', 'content': json.dumps({'idea': doc.idea,
             'current': doc.character.model_dump(),
             'custom_fields': [f.model_dump() for f in doc.custom_fields],
             'target': target, 'instruction': instruction}, ensure_ascii=False)}]


def generated_profile(data):
    if not isinstance(data, dict) or set(data) != set(Profile.model_fields):
        raise ValueError('生成された基本項目のキーが一致しません')
    p = Profile.model_validate(data)
    for key in ('name', 'persona', 'appearance', 'background'):
        if not getattr(p, key).strip():
            raise ValueError(f'{key}が空欄です')
    if not p.speech_examples or any(not x.strip() for x in p.speech_examples):
        raise ValueError('台詞は空白だけでない例が1件以上必要です')
    return p


def parse_response(envelope, doc, target):
    if not isinstance(envelope, dict) or not envelope.get('choices'):
        raise ValueError('API応答に生成結果がありません')
    choice = envelope['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('生成が完了しませんでした: ' + str(choice.get('finish_reason')) + '。出力上限や期限を確認してください')
    content = choice.get('message', {}).get('content')
    if not isinstance(content, str):
        raise ValueError('応答本文が文字列ではありません')
    match = re.fullmatch(r'\s*```(?:json)?\s*\n(.*?)\n```\s*', content, re.S)
    data = strict_json(match.group(1) if match else content)
    result = doc.model_copy(deep=True)
    if target is None:
        if not isinstance(data, dict) or set(data) != {'character', 'custom_values'}:
            raise ValueError('全体生成の応答形式が一致しません')
        result.character = generated_profile(data['character'])
        values = data['custom_values']
        if not isinstance(values, list) or len(values) != len(doc.custom_fields):
            raise ValueError('自由項目の件数が一致しません')
        mapped = {}
        for item in values:
            if not isinstance(item, dict) or set(item) != {'id', 'value'} or not isinstance(item['id'], str) or not isinstance(item['value'], str):
                raise ValueError('自由項目の候補形式が不正です')
            if item['id'] in mapped:
                raise ValueError('自由項目IDが重複しています')
            mapped[item['id']] = item['value']
        if set(mapped) != {f.id for f in doc.custom_fields}:
            raise ValueError('自由項目IDが一致しません')
        for f in result.custom_fields:
            f.value = mapped[f.id]
    else:
        kind, key = target
        expected = key if kind == 'basic' else 'value'
        if not isinstance(data, dict) or set(data) != {expected}:
            raise ValueError('対象以外の項目が含まれるか、対象が不足しています')
        if kind == 'basic':
            if key not in Profile.model_fields:
                raise ValueError('不明な基本項目')
            updated = result.character.model_dump()
            updated[key] = data[key]
            validated = Profile.model_validate(updated)
            if key == 'speech_examples':
                if not validated.speech_examples or any(not x.strip() for x in validated.speech_examples):
                    raise ValueError('台詞が空です')
            elif key != 'notes' and not getattr(validated, key).strip():
                raise ValueError('生成された項目が空です')
            result.character = validated
        elif kind == 'custom':
            if not isinstance(data['value'], str):
                raise ValueError('自由項目の本文は文字列にしてください')
            field = next((f for f in result.custom_fields if f.id == key), None)
            if field is None:
                raise ValueError('対象の自由項目がありません')
            field.value = data['value']
        else:
            raise ValueError('不明な対象です')
    return Document.model_validate(result.model_dump())


class Editor:
    def __init__(self):
        self.doc = Document()
        self.session = str(uuid4())
        self.revision = 0
        self.dirty = False
        self.request = None
        self.candidate = None

    def replace(self, doc):
        self.doc = doc
        self.session = str(uuid4())
        self.revision = 0
        self.dirty = False
        self.cancel()

    def change(self, data):
        if self.request:
            raise ValueError('候補を適用または破棄してください')
        doc = Document.model_validate(data)
        if doc != self.doc:
            doc.updated_at = now()
            self.doc = doc
            self.revision += 1
            self.dirty = True

    def begin(self, target):
        if self.request:
            raise ValueError('生成は一件ずつ実行してください')
        self.request = Request(self.session, self.revision, target, str(uuid4()))
        return self.request

    def receive(self, request, envelope):
        if request != self.request or request.session != self.session or request.revision != self.revision:
            return False
        self.candidate = parse_response(envelope, self.doc, request.target)
        return True

    def apply(self):
        request = self.request
        if not request or not self.candidate or request.session != self.session or request.revision != self.revision:
            raise ValueError('候補が古いか、存在しません')
        candidate = self.candidate
        self.cancel()
        self.change(candidate.model_dump())

    def cancel(self):
        self.request = None
        self.candidate = None
