import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'重複したJSONキー: {key}')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class Profile(StrictModel):
    name: str = ''
    persona: str = ''
    appearance: str = ''
    speech_examples: list[str] = Field(default_factory=list)
    background: str = ''
    notes: str = ''


class CustomField(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    label: str
    value: str = ''

    @field_validator('id')
    @classmethod
    def valid_id(cls, value):
        UUID(value)
        return value

    @field_validator('label')
    @classmethod
    def valid_label(cls, value):
        if not value.strip() or '\n' in value or '\r' in value:
            raise ValueError('項目名は空白だけにせず、1行で入力してください')
        return value


class Document(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    idea: str = ''
    character: Profile = Field(default_factory=Profile)
    custom_fields: list[CustomField] = Field(default_factory=list)

    @field_validator('id')
    @classmethod
    def valid_id(cls, value):
        UUID(value)
        return value

    @field_validator('created_at', 'updated_at')
    @classmethod
    def utc_date(cls, value):
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
            raise ValueError('日時はUTCで指定してください')
        return value

    @model_validator(mode='after')
    def unique_fields(self):
        ids = [UUID(f.id) for f in self.custom_fields]
        labels = [f.label.strip() for f in self.custom_fields]
        if len(ids) != len(set(ids)) or len(labels) != len(set(labels)):
            raise ValueError('自由項目のIDまたは項目名が重複しています')
        return self


def load_document(text):
    data = strict_json(text)
    required = {'schema_version', 'id', 'created_at', 'updated_at', 'idea', 'character'}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError('保存文書の必須項目が不足しています')
    if type(data['schema_version']) is not int:
        raise ValueError('schema_versionは整数で指定してください')
    if not isinstance(data['character'], dict) or set(data['character']) != set(Profile.model_fields):
        raise ValueError('基本六項目が不足しているか、余分な項目があります')
    if not isinstance(data.get('custom_fields', []), list):
        raise ValueError('自由項目は配列で指定してください')
    for item in data.get('custom_fields', []):
        if not isinstance(item, dict) or set(item) != {'id', 'label', 'value'}:
            raise ValueError('自由項目の形式が不正です')
    return Document.model_validate(data)
