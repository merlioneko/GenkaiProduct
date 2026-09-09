from pathlib import Path
import json
from typing import TypeVar
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

"""
ファイル操作を行う簡易メソッドのモジュール

TODO: ファイル操作に直接関係しない要素が含まれている者は別に取り出しておく
"""

def get_root():
    return Path(__file__).resolve().parent.parent

def read_file(file_name) -> str:
    base_dir = get_root()
    file_path = base_dir / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content

def read_pipeline_prompt(file_name) -> str:
    return read_file(file_name).format(pipeline=read_file("prompts/pipeline_structure.md"))

def read_json(json_file) -> dict:
    if not json_file:
        raise ValueError("Illegal argument json file input")
    base_dir = get_root()
    file_path = base_dir / json_file
    with open(file_path, 'r', encoding="utf-8") as f:
        return json.load(f)

def output_creation(directory: str, file_name: str, content: str):
    base_dir = get_root()
    directory_path = base_dir / directory
    directory_path.mkdir(parents=True, exist_ok=True)
    file_path = directory_path / file_name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def output_model(directory: str, file_name: str, model: BaseModel):
    output_creation(directory, file_name, model.model_dump_json(indent=2))


def read_model(file_name, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate_json(read_file(file_name))
