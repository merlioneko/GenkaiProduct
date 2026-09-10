import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Literal, TypeVar
from uuid import uuid4
from collections.abc import Callable

from pydantic import Field
from rich.console import Console

from novel.engine import improving, structuring, writing, elaboration
from novel.novel import BorderCheckReport, DataModel, SceneWritingResult, WritingResult
from novel.plot import Plot
from util.file import get_root, read_file, output_creation, output_model, read_model
from util.gateway import connect_openrouter
from util.settings import ModelConfig


ResultT = TypeVar("ResultT")
PipelineStage = Literal["all", "writing", "borders"]
RunStatus = Literal["success", "partial", "failed"]
TextGenerator = Callable[..., str]


@dataclass
class PipelineContext:
    run_id: str
    directory: Path
    model: str | None = None
    # The engine also accepts injected clients when a custom generator is used.
    client: object | None = None


class RunEvent(DataModel):
    run_id: str
    timestamp: datetime
    stage: str
    status: RunStatus
    elapsed_seconds: float = Field(ge=0)
    model: str | None = None
    artifact: str | None = None
    error_type: str | None = None


def run_pipeline(
    *,
    stage: PipelineStage = "all",
    source: str | Path | None = None,
    directory: str | Path | None = "",
    client: object | None = None,
    config: ModelConfig | None = None,
    generate: TextGenerator | None = None,
    prompt: str | None = None,
) -> tuple[WritingResult, Path]:
    """Generate a novel, resume from Plot, or inspect saved WritingResult."""
    validate_pipeline_input(stage, source)
    context = create_pipeline_context(directory, client)

    if stage == "all":
        prepare_model_config(context, config)
        connect_pipeline_client(context)
        idea = load_user_idea(context)
        improved = execute_stage(
            context, "improving", partial(run_improving, context, idea),
            "02_improved_idea.txt",
        )
        plot = execute_stage(
            context, "structuring", partial(run_structuring, context, improved),
            "03_plot.json",
        )
        novel = execute_stage(
            context, "writing",
            partial(run_writing, context, plot, generate=generate, prompt=prompt),
            "04_novel.json", status=get_writing_status,
        )
    elif stage == "writing":
        prepare_model_config(context, config)
        # Validate the saved Plot before any API connection.
        plot = execute_stage(
            context, "load_plot", partial(read_model, source, Plot), str(source),
        )
        connect_pipeline_client(context)
        save_plot(context, plot)
        novel = execute_stage(
            context, "writing",
            partial(run_writing, context, plot, generate=generate, prompt=prompt),
            "04_novel.json", status=get_writing_status,
        )
    else:  # borders
        novel = execute_stage(
            context, "load_writing",
            partial(read_model, source, WritingResult), str(source),
        )

    execute_stage(
        context, "borders", partial(run_borders, context, novel), "05_borders.json",
    )
    return novel, context.directory


def validate_pipeline_input(
    stage: PipelineStage, source: str | Path | None,
) -> None:
    if stage not in {"all", "writing", "borders"}:
        raise ValueError(f"Unknown stage: {stage}")
    if stage != "all" and source is None:
        raise ValueError("source is required for an individual stage")


def create_pipeline_context(
    directory: str | Path | None, client: object | None,
) -> PipelineContext:
    run_id = uuid4().hex
    if directory:
        output_directory = Path(directory)
    else:
        output_directory = Path(
            f"creations/output-{datetime.now():%Y%m%d-%H%M%S}-{run_id[:8]}"
        )
    output_directory = get_root() / output_directory
    output_directory.mkdir(parents=True, exist_ok=True)
    return PipelineContext(run_id=run_id, directory=output_directory, client=client)


def prepare_model_config(
    context: PipelineContext, config: ModelConfig | None,
) -> None:
    config = config or ModelConfig()
    context.model = config.get_writer()
    output_model(str(context.directory), "01_model_config.json", config.data)


def connect_pipeline_client(context: PipelineContext) -> None:
    if context.client is None:
        if context.model is None:
            raise ValueError("Model configuration is required before connecting")
        context.client = execute_stage(
            context, "connect", partial(connect_openrouter, context.model), None,
        )


def load_user_idea(context: PipelineContext) -> str:
    idea = read_file("prompts/user_prompt.txt")
    if not idea.strip():
        raise ValueError("User prompt must not be blank")
    output_creation(str(context.directory), "00_user_prompt.txt", idea)
    return idea


def run_improving(context: PipelineContext, idea: str) -> str:
    result = improving(context.client, idea)
    output_creation(str(context.directory), "02_improved_idea.txt", result)
    return result


def run_structuring(context: PipelineContext, improved: str) -> Plot:
    result = structuring(context.client, improved)
    save_plot(context, result)
    return result


def save_plot(context: PipelineContext, plot: Plot) -> None:
    output_model(str(context.directory), "03_plot.json", plot)
    output_creation(str(context.directory), "03_plot.txt", str(plot))


def run_writing(
    context: PipelineContext,
    plot: Plot,
    *,
    generate: TextGenerator | None = None,
    prompt: str | None = None,
) -> WritingResult:
    result = writing(
        context.client, plot, generate=generate, prompt=prompt,
        on_scene=partial(save_scene, context),
    )
    output_model(str(context.directory), "04_novel.json", result)
    output_creation(str(context.directory), "04_novel.txt", render_novel(result))
    return result


def save_scene(context: PipelineContext, item: SceneWritingResult) -> None:
    """Save each outcome immediately so a later failure preserves progress."""
    output_model(
        str(context.directory), f"scenes/scene-{item.scene_index:04d}.json", item,
    )


def render_novel(result: WritingResult) -> str:
    scenes: list[str] = []
    for item in result.results:
        if item.scene is not None:
            scenes.append(str(item.scene))
        else:
            scenes.append(f"[未生成: scene {item.scene_index}: {item.title}]")
    return "\n\n".join(scenes)


def get_writing_status(result: WritingResult) -> RunStatus:
    """Partial means at least one scene succeeded, but some remain ungenerated."""
    if result.complete:
        return "success"
    if any(item.status == "success" for item in result.results):
        return "partial"
    return "failed"


def run_borders(
    context: PipelineContext, novel: WritingResult,
) -> BorderCheckReport:
    report = elaboration(novel)
    output_model(str(context.directory), "05_borders.json", report)
    return report


def execute_stage(
    context: PipelineContext,
    name: str,
    action: Callable[[], ResultT],
    artifact: str | None,
    status: Callable[[ResultT], RunStatus] | None = None,
) -> ResultT:
    """Time an action including artifact saves; log failures before re-raising."""
    started = perf_counter()
    try:
        result = action()
    except Exception as error:
        record_event(context, RunEvent(
            run_id=context.run_id, timestamp=datetime.now(timezone.utc),
            stage=name, status="failed", elapsed_seconds=perf_counter() - started,
            model=context.model, error_type=type(error).__name__,
        ))
        raise

    result_status: RunStatus = "success"
    if status is not None:
        result_status = status(result)
    record_event(context, RunEvent(
        run_id=context.run_id, timestamp=datetime.now(timezone.utc),
        stage=name, status=result_status, elapsed_seconds=perf_counter() - started,
        model=context.model, artifact=artifact,
    ))
    return result


def record_event(context: PipelineContext, event: RunEvent) -> None:
    with (context.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(event.model_dump_json() + "\n")



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="小説生成と保存データからの工程実行")
    parser.add_argument("--stage", choices=["all", "writing", "borders"], default="all")
    parser.add_argument("--input", type=Path, help="保存したPlotまたはWritingResultのJSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.stage != "all" and args.input is None:
        parser.error("writing/borders stages require --input")
    console = Console()
    try:
        result, directory = run_pipeline(stage=args.stage, source=args.input, directory=args.output)
    except Exception as error:
        console.print(f"[red]実行失敗: {error}[/red]")
        return 1
    console.print(f"{'執筆完了' if result.complete else '未生成のシーンあり'}: {directory}")
    return 0 if result.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
