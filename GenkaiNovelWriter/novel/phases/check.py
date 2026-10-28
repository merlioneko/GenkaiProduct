"""本文を変更しない項目別検査。D52の原文照合に失敗した応答も保存する。"""

import hashlib
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from novel import checks, run
from novel.context import complete_novel, draft_text
from novel.history import Operation, read_source, record_output
from novel.phases.structure import load_plot
from novel.schema import CheckResult, Novel, Plot
from util.config import PROJECT_ROOT, load_thinking_options, thinking_body, public_url
from util.gateway import OpenAICompatibleGateway, create_messages

LLM_ITEMS = ("elements", "consistency", "physical")
ITEMS = ("contamination", "length", *LLM_ITEMS)


class CheckFormatError(ValueError):
    def __init__(self, message, code="quote_mismatch"):
        super().__init__(message)
        self.code = code


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_output(path)


def load_inputs(directory: Path, *, fingerprints=None) -> tuple[Plot, Novel]:
    plot = load_plot(directory, fingerprints=fingerprints)
    novel = complete_novel(directory, plot, fingerprints=fingerprints)
    draft = directory / run.DRAFT
    if not draft.is_file():
        raise run.RunError("Draft does not match the completed scenes; assemble before Check.")
    text, fingerprint = read_source(draft)
    if text != draft_text(novel):
        raise run.RunError("Draft does not match the completed scenes; assemble before Check.")
    if fingerprints is not None:
        fingerprints[run.DRAFT] = fingerprint
    return plot, novel


def check_messages(plot: Plot, novel: Novel, system: str) -> list:
    # JSONのcontentに全文を格納し、原文と番号を曖昧に区切らない。
    user = json.dumps({"plot": plot.model_dump(), "scenes": [
        {"scene": s.index, "content": s.content} for s in novel.scenes
    ]}, ensure_ascii=False, indent=2)
    return create_messages(system=system, user=user)


def validate_result(result: CheckResult, item: str, novel: Novel) -> None:
    if result.item != item:
        raise CheckFormatError(f"Check item does not match {item}.", "item_mismatch")
    scenes = {s.index: s.content for s in novel.scenes}
    for issue in result.issues:
        if issue.scene not in scenes or not issue.quote.strip() or issue.quote not in scenes[issue.scene]:
            raise CheckFormatError(f"Check {item}: scene/quote does not match the original text.")


def save_report(directory: Path, results: dict, statuses: dict) -> None:
    lines = ["# 検査報告", "", "指摘は参考情報です。引用の一致は指摘の正しさを保証しません。人手で原文とPlotを確認してください。", "",
             "[Plot](03_plot.json) / [草稿](05_draft.md) / [実行条件・入力ハッシュ](06_check/metadata.json)", ""]
    for item in ITEMS:
        state = statuses[item]
        labels = {"pending": "未実行", "running": "実行中", "success": "完了", "error": "失敗"}
        lines.extend([f"## {item}: {state['status']} ({labels[state['status']]})", ""])
        if state.get("failure_step"):
            lines.extend([f"失敗段階: {state['failure_step']} / 分類: {state['error_code']} / 呼び出しID: {state.get('call_id')}", ""])
        result = results.get(item)
        if result is None:
            lines.extend(["結果なし。問題なし・検出率0とは扱いません。", ""])
            continue
        lines.extend([f"[JSON](06_check/{item}.json)", ""])
        if item == "length":
            lines.append(" / ".join(f"シーン{c.scene}: {c.characters}字" for c in result.counts) + f" / 合計: {result.total}字")
        if not result.issues:
            lines.append("指摘なし(品質の合格を意味しません)。")
        for issue in result.issues:
            # 原文の改行・Markdownをそのまま報告の構造に混入させない。
            quote = json.dumps(issue.quote, ensure_ascii=False)
            reason = " ".join(issue.reason.splitlines())
            lines.append(f"- [シーン{issue.scene}](04_scenes/scene_{issue.scene:02d}.md): {quote} — {reason}")
        lines.append("")
    (directory / run.CHECK_REPORT).write_text("\n".join(lines), encoding="utf-8")
    record_output(directory / run.CHECK_REPORT)


def run_check(directory, config, *, backend="local", thinking_options=None, timeout=600,
              allowed_names=(), gateway_factory=OpenAICompatibleGateway) -> dict:
    directory = run.open_run(directory)
    # 入力不正・設定不正では過去の検査結果を移動しない。
    hashes = {}
    plot, novel = load_inputs(directory, fingerprints=hashes)
    phase = config.phase("check")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    prompts = {item: (PROJECT_ROOT / f"prompts/check/{item}.md").read_text(encoding="utf-8")
               for item in LLM_ITEMS}
    allowed_names = tuple(allowed_names)
    if any(not isinstance(name, str) or not name.strip() or not any(c.isascii() and c.isalpha() for c in name)
           for name in allowed_names):
        raise run.RunError("Allowed names must be nonempty names containing Latin letters.")
    with Operation(directory, "stage check", config=config, backend=backend, inputs=hashes,
                   prompts={f"prompts/check/{item}.md": text for item, text in prompts.items()},
                   request_bodies={"check": body}) as operation:
        operation.step = "archive"
        operation.archive = run.archive_downstream(directory, "check")
        return execute_check(directory, config, phase, body, prompts, plot, novel, hashes,
                             allowed_names, backend, timeout, gateway_factory, operation)


def execute_check(directory, config, phase, body, prompts, plot, novel, hashes,
                  allowed_names, backend, timeout, gateway_factory, operation):
    folder = directory / run.CHECK
    folder.mkdir()
    results = {"contamination": checks.check_contamination(novel, allowed_names),
               "length": checks.check_length(novel)}
    statuses = {item: {"status": "success" if item in results else "pending",
                       "call_id": None, "failure_step": None, "error_code": None} for item in ITEMS}
    metadata = {
        "operation_id": operation.id, "backend": backend, "base_url": public_url(config.base_url),
        "phase": phase.model_dump(), "context_length": config.context_length,
        "allowed_names": allowed_names, "inputs": hashes,
        "prompts": {item: hashlib.sha256(text.encode("utf-8")).hexdigest() for item, text in prompts.items()},
        "items": statuses,
    }

    def save_state():
        save_json(folder / "metadata.json", metadata)
        save_report(directory, results, statuses)

    for item, result in results.items():
        save_json(run.check_path(directory, item), result.model_dump())
    save_state()
    for item in LLM_ITEMS:
        print(f"Check: {item}", file=sys.stderr, flush=True)
        gateway = None
        state = statuses[item]
        state["status"] = "running"
        save_state()
        failure_step = "request"
        operation.step = f"check_{item}"
        try:
            with gateway_factory(model=phase.model, base_url=config.base_url,
                                 api_key=config.api_key.get_secret_value(), phase=f"check_{item}",
                                 backend=backend, thinking=phase.thinking, request_body=body,
                                 log_path=directory / run.CALLS, timeout=timeout) as gateway:
                result = gateway.parse(check_messages(plot, novel, prompts[item]), CheckResult)
                state["call_id"] = getattr(gateway, "last_call_id", None)
                failure_step = "quote_validation"
                validate_result(result, item, novel)
            failure_step = "save_result"
            save_json(run.check_path(directory, item), result.model_dump())
            results[item] = result
            state["status"] = "success"
        except BaseException as error:
            response = getattr(gateway, "last_response", None)
            if response is not None and response.choices:
                raw = response.choices[0].message.content
                if isinstance(raw, str):
                    (folder / f"{item}_raw.txt").write_text(raw, encoding="utf-8")
                    record_output(folder / f"{item}_raw.txt")
            code = ("schema_invalid" if isinstance(error, ValidationError)
                    else error.code if isinstance(error, CheckFormatError)
                    else getattr(gateway, "last_error_code", None) or "operation_failed")
            state.update(status="error", failure_step="schema_validation" if isinstance(error, ValidationError) else failure_step,
                         call_id=getattr(gateway, "last_call_id", None), error_code=code)
            operation.last_error_code = code
            save_json(folder / "error.json", {"item": item, "error_type": type(error).__name__,
                                              "operation_id": operation.id, **state})
            save_state()
            if isinstance(error, ValidationError):
                raise CheckFormatError(f"Check {item} did not match the schema; see {run.CHECK}/{item}_raw.txt.", "schema_invalid") from None
            raise
        save_state()
    return results
