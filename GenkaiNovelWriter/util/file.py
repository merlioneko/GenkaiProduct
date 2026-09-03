from pathlib import Path
import json

"""
ファイル操作を行う簡易メソッドのモジュール

TODO: ファイル操作に直接関係しない要素が含まれている者は別に取り出しておく
"""

def get_root():
    return Path(__file__).resolve().parent.parent

def read_prompt(file_name) -> str:
    base_dir = get_root()
    file_path = base_dir / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content

def read_pipeline_prompt(file_name) -> str:
    return read_prompt(file_name).format(pipeline=read_prompt("prompts/pipeline_structure.md"))

def read_json(json_file) -> dict:
    if not json_file:
        raise ValueError("Illegal argument json file input")
    base_dir = get_root()
    file_path = base_dir / json_file
    with open(file_path) as f:
        return json.load(f)
