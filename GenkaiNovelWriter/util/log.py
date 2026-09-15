"""LLM呼び出しごとに1行、メタデータだけを calls.jsonl に追記する(D29)。失敗も記録する。"""

import json
from datetime import datetime, timezone
from pathlib import Path


def append_call(path: Path | str, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(
            {"timestamp": datetime.now(timezone.utc).isoformat(), **record},
            ensure_ascii=False,
        ) + "\n")
