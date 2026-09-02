from pathlib import Path

def read_prompt(file_name) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content

def read_pipeline_prompt(file_name) -> str:
    return read_prompt(file_name).format(pipeline=read_prompt("prompts/pipeline_structure.md"))

def read_model(file_name) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content

def read_env(file_name) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / ".env" / file_name
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
        return content