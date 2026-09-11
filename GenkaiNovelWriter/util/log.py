"""Append one metadata-only record per API request, including failures."""

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
