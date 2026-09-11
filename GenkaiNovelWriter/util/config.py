"""M1 backend configuration. Private configuration is never printed."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / ".env" / "backends.json"
PHASES = ("concept", "structure", "writing", "check", "baseline")


class ConfigError(ValueError):
    pass


class PhaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1)
    thinking: bool


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base_url: str = Field(min_length=1)
    api_key: SecretStr
    context_length: int = Field(gt=0)
    phases: dict[str, PhaseConfig]

    def phase(self, name: str) -> PhaseConfig:
        if name not in PHASES or name not in self.phases:
            raise ConfigError(f"Phase '{name}' is not configured.")
        phase = self.phases[name]
        if name == "baseline" and phase != self.phase("writing"):
            raise ConfigError("baseline and writing must use the same model and thinking setting.")
        return phase


def load_backend(path: Path | str = DEFAULT_CONFIG, backend: str = "local") -> BackendConfig:
    """Validate only the selected backend; a remote key is not needed locally."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError(
            "Cannot read backend JSON. Copy config/backends.example.json to "
            ".env/backends.json (or use --config), then set the model identifiers."
        ) from None
    if not isinstance(data, dict) or backend not in data:
        raise ConfigError(f"Backend '{backend}' is not configured.")
    try:
        config = BackendConfig.model_validate(data[backend])
    except ValidationError as error:
        locations = [".".join(map(str, item["loc"])) for item in error.errors()]
        raise ConfigError("Invalid backend fields: " + ", ".join(locations)) from None
    if not config.api_key.get_secret_value().strip():
        raise ConfigError("The selected backend requires a nonempty api_key.")
    return config


def load_thinking_options(path: Path | str | None) -> dict[str, Any]:
    """Experimental request bodies by model and on/off; no assumed U2 mechanism."""
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError("Cannot read --thinking-options JSON.") from None
    if not isinstance(data, dict):
        raise ConfigError("--thinking-options must contain an object keyed by model.")
    return data


def thinking_body(options: dict, phase: PhaseConfig) -> dict:
    mode = "on" if phase.thinking else "off"
    entry = options.get(phase.model)
    body = entry.get(mode) if isinstance(entry, dict) else None
    if not isinstance(body, dict) or not body:
        raise ConfigError(
            f"Thinking request for '{phase.model}' ({mode}) is unconfigured. "
            "Supply --thinking-options with the request bodies to verify for U2; "
            "do not assume the server default implements the requested mode."
        )
    reserved = {"model", "messages", "response_format", "stream", "n", "tools", "tool_choice"}
    if reserved.intersection(body):
        raise ConfigError("Thinking options must not override model, messages, output format or tools.")
    return dict(body)
