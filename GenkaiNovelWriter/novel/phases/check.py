"""本文を変更しない項目別検査。D52の原文照合に失敗した応答も保存する。"""

import hashlib
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from novel import checks, run
from novel.context import load_novel
from novel.phases.structure import load_plot
from novel.schema import CheckResult, Novel, Plot
from util.config import PROJECT_ROOT, load_thinking_options, thinking_body
from util.gateway import OpenAICompatibleGateway, create_messages

LLM_ITEMS = ("elements", "consistency", "physical")
ITEMS = ("contamination", "length", *LLM_ITEMS)


class CheckFormatError(ValueError):
    pass


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_inputs(directory: Path) -> tuple[Plot, Novel]:
    plot = load_plot(directory)
    expected = [run.scene_path(directory, i) for i in range(1, len(plot.scenes) + 1)]
    if run.scene_paths(directory) != expected:
        raise run.RunError("Check requires exactly the completed scenes listed in Plot.")
    novel = load_novel(directory, plot)
    draft = directory / run.DRAFT
    if not draft.is_file() or draft.read_text(encoding="utf-8") != "\n\n".join(s.content for s in novel.scenes) + "\n":
        raise run.RunError("Draft does not match the completed scenes; assemble before Check.")
    return plot, novel


def check_messages(plot: Plot, novel: Novel, system: str) -> list:
    # JSONのcontentに全文を格納し、原文と番号を曖昧に区切らない。
    user = json.dumps({"plot": plot.model_dump(), "scenes": [
        {"scene": s.index, "content": s.content} for s in novel.scenes
    ]}, ensure_ascii=False, indent=2)
    return create_messages(system=system, user=user)


def validate_result(result: CheckResult, item: str, novel: Novel) -> None:
    if result.item != item:
        raise CheckFormatError(f"Check item does not match {item}.")
    scenes = {s.index: s.content for s in novel.scenes}
    for issue in result.issues:
        if issue.scene not in scenes or not issue.quote.strip() or issue.quote not in scenes[issue.scene]:
            raise CheckFormatError(f"Check {item}: scene/quote does not match the original text.")


def save_report(directory: Path, results: dict, statuses: dict) -> None:
    lines = ["# 検査報告", "", "指摘は参考情報です。引用の一致は指摘の正しさを保証しません。人手で原文とPlotを確認してください。", "",
             "[Plot](03_plot.json) / [草稿](05_draft.md) / [実行条件・入力ハッシュ](06_check/metadata.json)", ""]
    for item in ITEMS:
        lines.extend([f"## {item}: {statuses[item]}", ""])
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


def run_check(directory, config, *, backend="local", thinking_options=None, timeout=600,
              allowed_names=(), gateway_factory=OpenAICompatibleGateway) -> dict:
    directory = run.open_run(directory)
    # 入力不正・設定不正では過去の検査結果を移動しない。
    plot, novel = load_inputs(directory)
    phase = config.phase("check")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    prompts = {item: (PROJECT_ROOT / f"prompts/check/{item}.md").read_text(encoding="utf-8")
               for item in LLM_ITEMS}
    allowed_names = tuple(allowed_names)
    if any(not isinstance(name, str) or not name.strip() or not any(c.isascii() and c.isalpha() for c in name)
           for name in allowed_names):
        raise run.RunError("Allowed names must be nonempty names containing Latin letters.")
    run.archive_downstream(directory, "check")
    folder = directory / run.CHECK
    folder.mkdir()
    files = [directory / run.PLOT, directory / run.DRAFT, *run.scene_paths(directory)]
    save_json(folder / "metadata.json", {
        "backend": backend, "base_url": config.base_url, "phase": phase.model_dump(),
        "context_length": config.context_length, "allowed_names": allowed_names,
        "inputs": {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "prompts": {item: hashlib.sha256(text.encode("utf-8")).hexdigest() for item, text in prompts.items()},
    })
    results = {"contamination": checks.check_contamination(novel, allowed_names),
               "length": checks.check_length(novel)}
    statuses = {item: "完了" if item in results else "未実行" for item in ITEMS}
    for item, result in results.items():
        save_json(run.check_path(directory, item), result.model_dump())
    save_report(directory, results, statuses)
    for item in LLM_ITEMS:
        print(f"Check: {item}", file=sys.stderr, flush=True)
        gateway = None
        try:
            with gateway_factory(model=phase.model, base_url=config.base_url,
                                 api_key=config.api_key.get_secret_value(), phase=f"check_{item}",
                                 backend=backend, thinking=phase.thinking, request_body=body,
                                 log_path=directory / run.CALLS, timeout=timeout) as gateway:
                result = gateway.parse(check_messages(plot, novel, prompts[item]), CheckResult)
                validate_result(result, item, novel)
            save_json(run.check_path(directory, item), result.model_dump())
            results[item] = result
            statuses[item] = "完了"
        except Exception as error:
            response = getattr(gateway, "last_response", None)
            if response is not None and response.choices:
                raw = response.choices[0].message.content
                if isinstance(raw, str):
                    (folder / f"{item}_raw.txt").write_text(raw, encoding="utf-8")
            statuses[item] = "失敗"
            save_json(folder / "error.json", {"item": item, "error_type": type(error).__name__})
            save_report(directory, results, statuses)
            if isinstance(error, ValidationError):
                raise CheckFormatError(f"Check {item} did not match the schema; see {run.CHECK}/{item}_raw.txt.") from None
            raise
        save_report(directory, results, statuses)
    return results
