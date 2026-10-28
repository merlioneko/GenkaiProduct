"""操作単位の来歴。既存の履歴・成果物を推測で補完しない(D56)。"""

import hashlib
import json
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from util.config import PROJECT_ROOT, public_config, public_url

CURRENT = ContextVar("novel_operation", default=None)
HISTORY = "_history"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_hash(text: str) -> str:
    return digest(text.encode("utf-8"))


def read_source(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"), digest(data)


def save_json(path: Path, data) -> None:
    # 履歴は一度だけ作る。同じIDの記録を上書きしない。
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def fingerprints(directory: Path) -> dict:
    return {p.relative_to(directory).as_posix(): digest(p.read_bytes())
            for p in sorted(directory.rglob("*")) if p.is_file()
            and p.relative_to(directory).parts[0] not in (HISTORY, "_archive")
            and p.name != "calls.jsonl"}


def provenance(directory: Path, inputs: dict[str, str]) -> dict:
    """最新の一致する出力を探す。導入時の移行記録は生成者にしない。"""
    records = []
    for path in (directory / HISTORY).glob("*/result.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        records.append(record)
    records.sort(key=lambda item: item["finished_at"], reverse=True)
    result = {}
    for name, fingerprint in inputs.items():
        source = next((r["operation_id"] for r in records
                       if r.get("outputs", {}).get(name) == fingerprint), None)
        result[name] = {"operation_id": source,
                        "status": "recorded" if source else "external_or_unknown"}
    return result


def operation_statuses(directory: Path) -> list[dict]:
    """強制終了等でresultがない操作は、完了未確認のまま返す。"""
    records = []
    for path in (Path(directory) / HISTORY).glob("*/start.json"):
        start = json.loads(path.read_text(encoding="utf-8"))
        result_path = path.with_name("result.json")
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
        records.append({"operation_id": start["operation_id"], "started_at": start["started_at"],
                        "status": result["status"] if result is not None else "completion_unconfirmed"})
    return sorted(records, key=lambda item: item["started_at"])


def record_output(path: Path | str) -> None:
    operation = CURRENT.get()
    if operation is not None:
        path = Path(path)
        operation.outputs[path.relative_to(operation.directory).as_posix()] = digest(path.read_bytes())


class Operation:
    def __init__(self, directory: Path, name: str, *, config=None, backend="local",
                 first=None, inputs=None, prompts=None, request_bodies=None, new=False):
        self.directory = Path(directory)
        self.id = uuid4().hex
        self.name = name
        self.folder = self.directory / HISTORY / self.id
        self.archive = None
        self.outputs = {}
        self.step = "start"
        self.call_ids = []
        self.last_error_code = None
        # 呼び出し元が検証時に読んだ内容の指紋を渡す。
        self.start = {
            "schema_version": 1, "operation_id": self.id, "started_at": now(),
            "operation": name, "first_scene": first,
            "config": public_config(config, backend) if config is not None else None,
            "inputs": inputs or {}, "input_provenance": provenance(self.directory, inputs or {}),
            "prompts": {name: text_hash(text) for name, text in (prompts or {}).items()},
            "request_body_sha256": {name: text_hash(json.dumps(body, sort_keys=True, ensure_ascii=False))
                                    for name, body in (request_bodies or {}).items()},
            "code": {p.relative_to(PROJECT_ROOT).as_posix(): digest(p.read_bytes())
                     for p in [PROJECT_ROOT / "main.py", *sorted((PROJECT_ROOT / "novel").rglob("*.py")),
                               *sorted((PROJECT_ROOT / "util").rglob("*.py"))]},
        }
        self.migration = None
        if not new and not any((self.directory / HISTORY).glob("*/start.json")):
            snapshot = self.directory / "01_config.json"
            config_record = None
            if snapshot.is_file():
                # 旧設定は秘密を含む可能性がある。公開フィールドだけを複写する。
                try:
                    data = json.loads(snapshot.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        config_record = {key: data.get(key) for key in ("backend", "context_length")}
                        config_record["base_url"] = public_url(str(data.get("base_url", "")))
                        phases = data.get("phases", {})
                        config_record["phases"] = {key: {k: value.get(k) for k in ("model", "thinking")}
                                                   for key, value in phases.items() if isinstance(value, dict)}
                except (ValueError, AttributeError):
                    pass
            self.migration = {"status": "present_at_adoption_original_conditions_unrecorded",
                              "initial_config_is_known": False, "public_config_at_adoption": config_record,
                              "files": fingerprints(self.directory)}

    def __enter__(self):
        self.folder.mkdir(parents=True)
        if self.migration is not None:
            save_json(self.folder / "migration.json", self.migration)
        save_json(self.folder / "start.json", self.start)
        self.token = CURRENT.set(self)
        return self

    def __exit__(self, kind, error, traceback):
        try:
            status = "success" if kind is None else "interrupted" if issubclass(kind, (KeyboardInterrupt, SystemExit)) else "error"
            archive = self.archive.relative_to(self.directory).as_posix() if self.archive else None
            save_json(self.folder / "result.json", {
                "schema_version": 1, "operation_id": self.id, "status": status, "finished_at": now(),
                "archive": archive, "outputs": self.outputs, "call_ids": self.call_ids,
                "failure_step": self.step if kind else None,
                "error_type": kind.__name__ if kind else None,
                "error_code": (self.last_error_code or "operation_failed") if kind else None,
            })
        finally:
            CURRENT.reset(self.token)
        return False
