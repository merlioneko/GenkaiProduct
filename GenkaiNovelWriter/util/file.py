from pathlib import Path
import json

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

def read_model(file_name) -> str:
    base_dir = get_root()
    file_path = base_dir / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content

def read_models(json_file=".env/model.json") -> dict:
    """
    modelを参照する関数。以下の構造から成る。
    ```
    {
        "writer": "modelA",
        "editor": "modelB"
    }
    ```
    @Exception: OSError
    """
    base_dir = get_root()
    file_path = base_dir / json_file
    with open(file_path) as f:
        return json.load(f)