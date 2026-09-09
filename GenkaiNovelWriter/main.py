import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from pydantic import Field
from rich.console import Console

from novel.engine import improving, structuring, writing, elaboration
from novel.novel import DataModel, WritingResult
from novel.plot import Plot
from util.file import get_root, read_file, output_creation, output_model, read_model
from util.gateway import connect_openrouter
from util.settings import ModelConfig


class RunEvent(DataModel):
    run_id: str
    timestamp: datetime
    stage: str
    status: Literal["success", "partial", "failed"]
    elapsed_seconds: float = Field(ge=0)
    model: str | None = None
    artifact: str | None = None
    error_type: str | None = None


def run_pipeline(*, stage="all", source=None, directory=None, client=None,
                 config=None, generate=None, prompt=None):
    """Run all stages, write from saved Plot, or inspect saved WritingResult."""
    if stage not in {"all", "writing", "borders"}:
        raise ValueError(f"Unknown stage: {stage}")
    if stage != "all" and source is None:
        raise ValueError("source is required for an individual stage")
    run_id = uuid4().hex
    directory = Path(directory) if directory else Path(
        f"creations/output-{datetime.now():%Y%m%d-%H%M%S}-{run_id[:8]}")
    directory = get_root() / directory
    directory.mkdir(parents=True, exist_ok=True)
    model = None

    def execute(name, action, artifact, status=None):
        started = perf_counter()
        try:
            result = action()
        except Exception as error:
            event = RunEvent(run_id=run_id, timestamp=datetime.now(timezone.utc),
                stage=name, status="failed", elapsed_seconds=perf_counter() - started,
                model=model, error_type=type(error).__name__)
            with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
            raise
        event = RunEvent(run_id=run_id, timestamp=datetime.now(timezone.utc),
            stage=name, status=status(result) if status else "success",
            elapsed_seconds=perf_counter() - started, model=model, artifact=artifact)
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
        return result

    if stage == "borders":
        novel = execute("load_writing", lambda: read_model(source, WritingResult), str(source))
    else:
        config = config or ModelConfig()
        model = config.get_writer()
        output_model(directory, "01_model_config.json", config.data)
        output_creation(directory, "01_model_config.txt", str(config))
        if stage == "writing":
            plot = execute("load_plot", lambda: read_model(source, Plot), str(source))
        if client is None:
            client = execute("connect", lambda: connect_openrouter(model), None)
        if stage == "all":
            idea = read_file("prompts/user_prompt.txt")
            if not idea.strip():
                raise ValueError("User prompt must not be blank")
            output_creation(directory, "00_user_prompt.txt", idea)

            def improve():
                result = improving(client, idea)
                output_creation(directory, "02_improved_idea.txt", result)
                return result

            improved = execute("improving", improve, "02_improved_idea.txt")

            def structure():
                result = structuring(client, improved)
                output_model(directory, "03_plot.json", result)
                output_creation(directory, "03_plot.txt", str(result))
                return result

            plot = execute("structuring", structure, "03_plot.json")
        else:
            output_model(directory, "03_plot.json", plot)
            output_creation(directory, "03_plot.txt", str(plot))

        def write():
            result = writing(client, plot, generate=generate, prompt=prompt,
                on_scene=lambda item: output_model(directory,
                    f"scenes/scene-{item.scene_index:04d}.json", item))
            output_model(directory, "04_novel.json", result)
            text = "\n\n".join(str(item.scene) if item.scene is not None else
                f"[未生成: scene {item.scene_index}: {item.title}]" for item in result.results)
            output_creation(directory, "04_novel.txt", text)
            return result

        novel = execute("writing", write, "04_novel.json", status=lambda result:
            "success" if result.complete else
            "partial" if any(item.status == "success" for item in result.results) else "failed")

    def borders():
        report = elaboration(novel)
        output_model(directory, "05_borders.json", report)
        return report

    execute("borders", borders, "05_borders.json")
    return novel, directory


def main(argv=None):
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
