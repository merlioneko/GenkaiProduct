"""シーン単位の Writing(B'方式)と Assemble。ファイルを正として再開する。"""

import sys
from dataclasses import dataclass
from pathlib import Path

from novel import checks, run
from novel.context import complete_novel, draft_text, load_novel, writing_messages
from novel.history import CURRENT, record_output
from novel.phases.structure import load_plot
from novel.schema import Novel, NovelScene, Plot
from util.config import PROJECT_ROOT, BackendConfig, PhaseConfig, load_thinking_options, thinking_body
from util.gateway import GenerationError, OpenAICompatibleGateway

SYSTEM_PROMPT = PROJECT_ROOT / "prompts/writing/system.md"


@dataclass(frozen=True)
class WritingPreparation:
    phase: PhaseConfig
    body: dict
    system: str


def prepare_writing(config: BackendConfig, thinking_options=None) -> WritingPreparation:
    phase = config.phase("writing")
    return WritingPreparation(phase, thinking_body(load_thinking_options(thinking_options), phase),
                              SYSTEM_PROMPT.read_text(encoding="utf-8"))


def prepare_input(directory: Path, first: int) -> tuple[Plot, Novel, dict]:
    fingerprints = {}
    plot = load_plot(directory, fingerprints=fingerprints)
    if not 1 <= first <= len(plot.scenes):
        raise run.RunError(f"--from must be between 1 and {len(plot.scenes)}: {first}")
    novel = load_novel(directory, plot, until=first, fingerprints=fingerprints)
    return plot, novel, fingerprints


def assemble(directory: Path | str, plot: Plot, *, novel: Novel | None = None) -> Novel:
    """全シーンを空行で結合する。字数は空白・改行を除く。警告は本文に混ぜない。"""
    if novel is None:
        novel = complete_novel(directory, plot)
    run.atomic_write(Path(directory) / run.DRAFT, draft_text(novel))
    show_lengths(novel)
    return novel


def show_lengths(novel: Novel) -> None:
    total = 0
    for scene in novel.scenes:
        count = checks.character_count(scene.content)
        total += count
        print(f"scene_{scene.index:02d}: {count}字")
        if count < 600:
            print(f"警告: scene_{scene.index:02d} は600字未満です ({count}字)。", file=sys.stderr)
    print(f"合計: {total}字")


def run_writing(directory: Path | str, config: BackendConfig, *, first: int = 1,
                backend: str = "local", thinking_options=None, timeout: float = 600,
                gateway_factory=OpenAICompatibleGateway, prepared=None, inputs=None) -> Novel:
    directory = run.open_run(directory)
    plot, novel, _ = inputs if inputs is not None else prepare_input(directory, first)
    prepared = prepared or prepare_writing(config, thinking_options)
    phase, body, system = prepared.phase, prepared.body, prepared.system
    (directory / run.SCENES).mkdir(exist_ok=True)
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="writing", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        for number in range(first, len(plot.scenes) + 1):
            operation = CURRENT.get()
            if operation is not None:
                operation.step = f"writing_scene_{number:02d}"
            print(f"Writing: scene_{number:02d} ({number}/{len(plot.scenes)})", file=sys.stderr)
            # ログで最終シーンの usage を特定できるようにする。
            gateway.scene_index = number
            messages = writing_messages(directory, plot, number, system, novel=novel)
            text = gateway.text(messages)
            if not isinstance(text, str) or not text.strip():
                raise GenerationError(f"Scene {number} has no text content.")
            run.scene_path(directory, number).write_text(text, encoding="utf-8")
            record_output(run.scene_path(directory, number))
            novel.scenes.append(NovelScene(index=number, title=plot.scenes[number - 1].name, content=text))
    return assemble(directory, plot, novel=novel)
