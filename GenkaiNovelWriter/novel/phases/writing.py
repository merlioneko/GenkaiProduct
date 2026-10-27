"""シーン単位の Writing(B'方式)と Assemble。ファイルを正として再開する。"""

import sys
from pathlib import Path

from novel import checks, run
from novel.context import load_novel, writing_messages
from novel.phases.structure import load_plot
from novel.schema import Novel, Plot
from util.config import PROJECT_ROOT, BackendConfig, load_thinking_options, thinking_body
from util.gateway import GenerationError, OpenAICompatibleGateway

SYSTEM_PROMPT = PROJECT_ROOT / "prompts/writing/system.md"


def validate_start(directory: Path | str, plot: Plot, first: int) -> None:
    """退避する前に、再開番号と再利用するファイルを検証する。"""
    if not 1 <= first <= len(plot.scenes):
        raise run.RunError(f"--from must be between 1 and {len(plot.scenes)}: {first}")
    load_novel(directory, plot, until=first)


def assemble(directory: Path | str, plot: Plot) -> Novel:
    """全シーンを空行で結合する。字数は空白・改行を除く。警告は本文に混ぜない。"""
    novel = load_novel(directory, plot)
    text = "\n\n".join(scene.content for scene in novel.scenes)
    (Path(directory) / run.DRAFT).write_text(text + "\n", encoding="utf-8")
    total = 0
    for scene in novel.scenes:
        count = checks.character_count(scene.content)
        total += count
        print(f"scene_{scene.index:02d}: {count}字")
        if count < 600:
            print(f"警告: scene_{scene.index:02d} は600字未満です ({count}字)。", file=sys.stderr)
    print(f"合計: {total}字")
    return novel


def run_writing(directory: Path | str, config: BackendConfig, *, first: int = 1,
                backend: str = "local", thinking_options=None, timeout: float = 600,
                gateway_factory=OpenAICompatibleGateway) -> Novel:
    directory = run.open_run(directory)
    plot = load_plot(directory)
    validate_start(directory, plot, first)
    phase = config.phase("writing")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")
    (directory / run.SCENES).mkdir(exist_ok=True)
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="writing", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        for number in range(first, len(plot.scenes) + 1):
            print(f"Writing: scene_{number:02d} ({number}/{len(plot.scenes)})", file=sys.stderr)
            # ログで最終シーンの usage を特定できるようにする。
            gateway.scene_index = number
            messages = writing_messages(directory, plot, number, system)
            text = gateway.text(messages)
            if not isinstance(text, str) or not text.strip():
                raise GenerationError(f"Scene {number} has no text content.")
            run.scene_path(directory, number).write_text(text, encoding="utf-8")
    return assemble(directory, plot)
