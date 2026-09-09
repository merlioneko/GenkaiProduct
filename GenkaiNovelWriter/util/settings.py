import os
from pathlib import Path

from dotenv import load_dotenv

from util.file import read_json


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_CONFIG = PROJECT_ROOT / "config" / "models.json"

# A missing .env file is valid for features that do not require external APIs.
load_dotenv(PROJECT_ROOT / ".env")


class ModelConfig:
    def __init__(self, config_file=DEFAULT_MODEL_CONFIG):
        self.config_file = config_file
        self.config_data = self.load_config()

    def load_config(self):
        return read_json(self.config_file)

    def get_model(self, role):
        if role not in self.config_data:
            raise ValueError(f"Role '{role}' not found in model configuration.")
        return self.config_data[role]

    def get_writer(self):
        return self.get_model("writer")

    def get_editor(self):
        return self.get_model("editor")


def get_required_secret(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not configured. "
            "Copy .env.example to .env and set the API key."
        )
    return value


def get_openrouter_base_url() -> str:
    return os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
