"""One OpenAI-compatible client for local and remote backends (no search imports)."""

import json
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel

from util.log import append_call

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "creations/legacy/calls.jsonl"


def create_message(history: list | None = None, system: str = "", user: str = "") -> list:
    return list(history or []) + [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class GenerationError(RuntimeError):
    """The response cannot be used as a completed piece of writing."""


class OpenAICompatibleGateway:
    def __init__(self, model: str, *, base_url: str, api_key: str,
                 phase: str = "legacy", backend: str = "legacy", thinking: bool | None = None,
                 request_body: dict | None = None, log_path=DEFAULT_LOG,
                 timeout: float = 600, client=None):
        self.model = model
        self.phase = phase
        self.backend = backend
        self.thinking = thinking
        self.request_body = dict(request_body or {})
        self.log_path = Path(log_path)
        self.last_response = None
        if client is None:
            from openai import OpenAI
            # Hidden SDK retries would hide individual requests and their costs.
            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _request(self, messages: list, *, response_schema=None, base_model=None):
        started = perf_counter()
        response = None
        self.last_response = None
        error_type = None
        error_usage = {}
        try:
            arguments = dict(model=self.model, messages=messages, stream=False)
            if self.request_body:
                arguments["extra_body"] = self.request_body
            if response_schema is not None:
                arguments["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "Plot" if base_model is None else base_model.__name__,
                                    "strict": True, "schema": response_schema},
                }
            response = self.client.chat.completions.create(**arguments)
            self.last_response = response
            if not response.choices:
                raise GenerationError("Response has no choices.")
            choice = response.choices[0]
            if choice.finish_reason != "stop":
                raise GenerationError("Generation did not finish normally.")
            if not isinstance(choice.message.content, str) or not choice.message.content.strip():
                raise GenerationError("Response has no text content.")
            if base_model is not None:
                return base_model.model_validate_json(choice.message.content)
            return response
        except BaseException as error:
            error_type = type(error).__name__
            # Only numeric usage metadata; never log raw errors, headers or bodies.
            body = getattr(error, "body", None)
            if isinstance(body, dict):
                error_usage = body.get("usage", {})
                if not isinstance(error_usage, dict):
                    error_usage = {}
            if not error_usage and getattr(error, "response", None) is not None:
                try:
                    payload = error.response.json()
                    if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
                        error_usage = payload["usage"]
                except (ValueError, TypeError):
                    pass
            raise
        finally:
            elapsed = perf_counter() - started
            usage = getattr(response, "usage", None)
            def tokens(name):
                value = getattr(usage, name, None) if usage else error_usage.get(name)
                return value if isinstance(value, int) and not isinstance(value, bool) else None
            output_tokens = tokens("completion_tokens")
            stats = getattr(response, "stats", None)
            append_call(self.log_path, {
                "phase": self.phase, "backend": self.backend,
                "model": self.model, "thinking": self.thinking,
                "thinking_request_supplied": bool(self.request_body),
                "input_tokens": tokens("prompt_tokens"), "output_tokens": output_tokens,
                "total_tokens": tokens("total_tokens"), "duration_seconds": elapsed,
                "output_tokens_per_second_end_to_end": (
                    output_tokens / elapsed if output_tokens is not None and elapsed > 0 else None
                ),
                "server_tokens_per_second": (
                    stats.get("tokens_per_second") if isinstance(stats, dict) else None
                ),
                "status": "error" if error_type else "success", "error_type": error_type,
            })

    def chat_response(self, message: list, *, response_schema=None):
        return self._request(message, response_schema=response_schema)

    def chat(self, messages: list):
        return self.chat_response(messages)

    def text(self, messages: list) -> str:
        return self.chat_response(messages).choices[0].message.content

    def chat_formated(self, message: list, base_model: type[BaseModel]) -> BaseModel:
        return self._request(message, response_schema=base_model.model_json_schema(), base_model=base_model)


# Existing experimental scripts keep their helpers, but use the same client class.
# No connection-test generation is performed implicitly.
def connect_lm_studio(model: str):
    return OpenAICompatibleGateway(model, base_url="http://localhost:1234/v1", api_key="lm-studio")


def connect_openrouter(model: str):
    from util.settings import get_openrouter_base_url, get_required_secret
    return OpenAICompatibleGateway(model, base_url=get_openrouter_base_url(),
                                   api_key=get_required_secret("OPENROUTER_API_KEY"))


def generate_text(gateway, system: str, user: str, history: list | None = None) -> str:
    return gateway.text(create_message(history=history, system=system, user=user))


def generate_formated(gateway, system: str, user: str, base_model: type[BaseModel],
                      history: list | None = None) -> BaseModel:
    return gateway.chat_formated(create_message(history=history, system=system, user=user), base_model)


def _compact_search_result(result) -> str:
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)[:6000]
    results = [{"title": item.get("title", ""), "content": str(item.get("content", ""))[:1000],
                "url": item.get("url", "")}
               for item in result.get("results", [])[:5] if isinstance(item, dict)]
    return json.dumps({"results": results}, ensure_ascii=False)[:6000]


def generate_with_search(gateway, system, user, search_tool):
    messages = create_message(system=system, user=user)
    messages.append({"role": "user", "content": "検索結果:\n" + _compact_search_result(search_tool.execute(user))})
    return gateway.text(messages)
