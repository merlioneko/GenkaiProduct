"""LM Studio のロード状態を確認し、別モデルを lms で解放する(D27, D39)。"""

import subprocess
from urllib.parse import urlsplit, urlunsplit

import httpx


class ModelSwitchError(RuntimeError):
    pass


def prepare_local_model(base_url: str, api_key: str, model: str) -> None:
    """プロセスを跨ぐ stage 実行でも、実際のロード状態を基準に切り替える。

    次モデルのロードは従来どおり JIT に任せる。解放失敗時は生成を始めない。
    状態 API: https://lmstudio.ai/docs/developer/rest/list
    """
    url = urlsplit(base_url)
    if url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ModelSwitchError("local backend must point to loopback for lms model switching.")
    endpoint = urlunsplit((url.scheme, url.netloc, "/api/v1/models", "", ""))

    def instances(client):
        try:
            response = client.get(endpoint, headers={"Authorization": "Bearer " + api_key})
            response.raise_for_status()
            models = response.json()["models"]
            if not isinstance(models, list):
                raise ValueError
            return [(item["key"], instance["id"])
                    for item in models if item["type"] == "llm"
                    for instance in item["loaded_instances"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ModelSwitchError("Cannot read LM Studio loaded models; check the local server.") from None

    with httpx.Client(timeout=15, trust_env=False) as client:
        loaded = instances(client)
        previous = [identifier for key, identifier in loaded if model not in (key, identifier)]
        for identifier in previous:
            try:
                subprocess.run(["lms", "unload", identifier], check=True, capture_output=True,
                               timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.SubprocessError):
                raise ModelSwitchError(
                    "lms unload failed; check lms installation and loaded models before retrying."
                ) from None
        if previous and any(model not in (key, identifier) for key, identifier in instances(client)):
            raise ModelSwitchError("Previous model is still loaded after lms unload; generation stopped.")
