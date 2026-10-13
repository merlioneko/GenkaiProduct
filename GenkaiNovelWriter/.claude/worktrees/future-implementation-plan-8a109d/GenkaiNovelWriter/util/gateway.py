"""OpenAI互換APIクライアント(D25)。

LM Studio と OpenRouter の差は base_url / api_key / model だけなので、クラスは1つ。
すべての呼び出しを calls.jsonl に記録する(D29)。検索など範囲外の機能は import しない(D28)。
"""

from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from util.log import append_call


def create_message(history: list | None = None, system: str = "", user: str = "") -> list:
    """system と user のメッセージ列を作る。history は変更しない。"""
    return list(history or []) + [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class GenerationError(RuntimeError):
    """応答が完成した本文として使えない(空・途中打ち切りなど)。"""


class OpenAICompatibleGateway:
    def __init__(self, model: str, *, base_url: str, api_key: str, log_path: Path | str,
                 phase: str, backend: str = "local", thinking: bool | None = None,
                 request_body: dict | None = None, timeout: float = 600, client=None):
        self.model = model
        self.phase = phase
        self.backend = backend
        self.thinking = thinking
        self.request_body = dict(request_body or {})
        self.log_path = Path(log_path)
        self.last_response = None
        if client is None:
            from openai import OpenAI
            # SDK の自動リトライは切る。1呼び出し=1記録にするため。
            client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    # ---- 公開API ----

    def text(self, messages: list) -> str:
        """本文をそのまま返す。"""
        return self.chat_response(messages).choices[0].message.content

    def parse(self, messages: list, model_cls: type[BaseModel]) -> BaseModel:
        """JSON Schema 制約付きで生成し、pydantic モデルにして返す。違反は ValidationError。"""
        return self._request(messages, response_schema=model_cls.model_json_schema(), model_cls=model_cls)

    def chat_response(self, messages: list, *, response_schema: dict | None = None):
        """SDK の生の応答を返す(検証スクリプト用)。"""
        return self._request(messages, response_schema=response_schema)

    # ---- 内部 ----

    def _request(self, messages: list, *, response_schema=None, model_cls=None):
        started = perf_counter()
        response = None
        self.last_response = None
        error_type = None
        error_usage = {}
        try:
            arguments: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
            if self.request_body:
                arguments["extra_body"] = self.request_body
            if response_schema is not None:
                name = model_cls.__name__ if model_cls is not None else "Output"
                arguments["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": name, "strict": True, "schema": response_schema},
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
            if model_cls is not None:
                return model_cls.model_validate_json(choice.message.content)
            return response
        except BaseException as error:
            error_type = type(error).__name__
            # 数値の usage だけ拾う。エラー本文・ヘッダ・鍵はログに書かない。
            body = getattr(error, "body", None)
            if isinstance(body, dict) and isinstance(body.get("usage"), dict):
                error_usage = body["usage"]
            error_response = getattr(error, "response", None)
            if not error_usage and error_response is not None:
                try:
                    payload = error_response.json()
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
