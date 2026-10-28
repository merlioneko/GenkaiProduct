"""GenkaiNovelWriter CLI。

サブコマンドごとに1関数。中身は「設定を読む → 実行ディレクトリを作る → フェーズを呼ぶ → ファイルに書く」の直線。
run は生成部分と人手評価テンプレートの保存まで実行する(SPEC.md「CLI」D43)。
"""

import argparse
import sys
from pathlib import Path

from novel import checks, evaluation, run
from novel.history import Operation, digest, read_source, record_output
from novel.context import complete_novel, draft_text
from novel.phases import concept as concept_phase
from novel.phases import structure as structure_phase
from novel.phases import writing as writing_phase
from novel.phases import check as check_phase
from novel.run import CREATIONS, create_output_dir
from util.config import (
    DEFAULT_CONFIG, PROJECT_ROOT, ConfigError, load_backend,
    load_thinking_options, thinking_body,
)
from util.gateway import OpenAICompatibleGateway, create_messages
from util.models import ModelSwitchError

# 自分の例外だけは文面を出す。秘密の値を含まないため。
REPORTABLE = (ConfigError, run.RunError, concept_phase.ConceptFormatError,
              structure_phase.PlotFormatError, structure_phase.StructureError, ModelSwitchError,
              check_phase.CheckFormatError)


def baseline(input_path: Path, *, config_path=DEFAULT_CONFIG, backend="local",
             thinking_options=None, output_root=None, timeout=600,
             gateway_factory=OpenAICompatibleGateway) -> Path:
    """一発生成(U1 の比較用)。creations/baseline-*/ に 00_input.txt・baseline.md・calls.jsonl を書く。"""
    idea, _ = read_source(Path(input_path))
    if not idea.strip():
        raise ValueError("Input must not be empty.")
    config = load_backend(config_path, backend)
    phase = config.phase("baseline")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    prompt = (PROJECT_ROOT / "prompts/baseline/system.md").read_text(encoding="utf-8")

    directory = create_output_dir(Path(output_root or CREATIONS), "baseline-")
    (directory / run.INPUT).write_text(idea, encoding="utf-8")
    with Operation(directory, "baseline", config=config, backend=backend, new=True,
                   inputs={run.INPUT: digest((directory / run.INPUT).read_bytes())},
                   prompts={"prompts/baseline/system.md": prompt}, request_bodies={"baseline": body}) as operation:
        operation.step = "baseline"
        with gateway_factory(
            model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
            phase="baseline", backend=backend, thinking=phase.thinking, request_body=body,
            log_path=directory / "calls.jsonl", timeout=timeout,
        ) as gateway:
            text = gateway.text(create_messages(system=prompt, user=idea))
        (directory / "baseline.md").write_text(text, encoding="utf-8")
        record_output(directory / "baseline.md")
    return directory


def stage(name: str, *, run_dir=None, input_path=None, config_path=DEFAULT_CONFIG,
          backend="local", thinking_options=None, output_root=None, timeout=600,
          gateway_factory=OpenAICompatibleGateway, allowed_names=()) -> Path:
    """フェーズを1つだけ実行する。実行前に下流の成果物を退避する(D23)。"""
    if name == "writing":
        return write(run_dir, config_path=config_path, backend=backend,
                     thinking_options=thinking_options, timeout=timeout,
                     gateway_factory=gateway_factory)
    if name == "check":
        config = load_backend(config_path, backend)
        directory = run.open_run(run_dir)
        check_phase.run_check(directory, config, backend=backend, thinking_options=thinking_options,
                              timeout=timeout, allowed_names=allowed_names, gateway_factory=gateway_factory)
        return directory
    if name not in ("concept", "structure"):
        raise run.RunError(f"Unknown stage: {name}")
    config = load_backend(config_path, backend)
    new = name == "concept" and run_dir is None
    if name == "concept":
        if new:
            idea, _ = read_source(Path(input_path))
        else:
            directory = run.open_run(run_dir)
            idea, fingerprint = read_source(directory / run.INPUT)
        prepared = concept_phase.prepare_concept(idea, config, thinking_options)
        if new:
            directory = run.create_run(input_path, output_root=output_root, idea=idea)
            fingerprint = digest((directory / run.INPUT).read_bytes())
        inputs = None
        hashes = {run.INPUT: fingerprint}
        prompts = {"prompts/concept/system.md": prepared.system,
                   "prompts/concept/verify.md": prepared.verify_system}
    else:
        directory = run.open_run(run_dir)
        prepared = structure_phase.prepare_structure(config, thinking_options)
        inputs = structure_phase.prepare_input(directory)
        hashes = inputs[2]
        prompts = {"prompts/structure/system.md": prepared.system}
    options = {"backend": backend, "thinking_options": thinking_options,
               "timeout": timeout, "gateway_factory": gateway_factory, "prepared": prepared}

    with Operation(directory, f"stage {name}", config=config, backend=backend, new=new,
                   inputs=hashes, prompts=prompts, request_bodies={name: prepared.body}) as operation:
        operation.step = "archive"
        operation.archive = run.archive_downstream(directory, name)
        if new:
            run.save_config_snapshot(directory, backend, config)
        operation.step = name
        if name == "concept":
            concept_phase.run_concept(directory, config, **options)
            operation.step = "concept_verify"
            concept_phase.verify_concept(directory, config, **options)
        else:
            plot = structure_phase.run_structure(directory, config, inputs=inputs, **options)
            checks.save_plot_report(directory, checks.check_plot(plot))
    return directory


def run_pipeline(input_path: Path, *, config_path=DEFAULT_CONFIG, backend="local",
                 thinking_options=None, output_root=None, timeout=600,
                 gateway_factory=OpenAICompatibleGateway) -> Path:
    """新しい実行ディレクトリで生成部分を一括実行する。失敗時は後続を呼ばない。"""
    config = load_backend(config_path, backend)
    idea, _ = read_source(Path(input_path))
    concept = concept_phase.prepare_concept(idea, config, thinking_options)
    structure = structure_phase.prepare_structure(config, thinking_options)
    writing = writing_phase.prepare_writing(config, thinking_options)
    directory = run.create_run(input_path, output_root=output_root, idea=idea)
    print(f"Run: {directory}", file=sys.stderr, flush=True)
    arguments = {"backend": backend, "thinking_options": thinking_options,
                 "timeout": timeout, "gateway_factory": gateway_factory}
    with Operation(directory, "run", config=config, backend=backend, new=True,
                   inputs={run.INPUT: digest((directory / run.INPUT).read_bytes())},
                   prompts={"prompts/concept/system.md": concept.system,
                            "prompts/concept/verify.md": concept.verify_system,
                            "prompts/structure/system.md": structure.system,
                            "prompts/writing/system.md": writing.system},
                   request_bodies={"concept": concept.body, "structure": structure.body,
                                   "writing": writing.body}) as operation:
        run.save_config_snapshot(directory, backend, config)
        operation.step = "concept"
        concept_phase.run_concept(directory, config, prepared=concept, **arguments)
        operation.step = "concept_verify"
        concept_phase.verify_concept(directory, config, prepared=concept, **arguments)
        operation.step = "structure"
        plot = structure_phase.run_structure(directory, config, prepared=structure, **arguments)
        checks.save_plot_report(directory, checks.check_plot(plot))
        operation.step = "writing"
        writing_phase.run_writing(directory, config, prepared=writing, **arguments)
        operation.step = "evaluation"
        evaluation.save_template(directory)
    return directory


def write(run_dir: Path | str, *, first: int = 1, config_path=DEFAULT_CONFIG,
          backend="local", thinking_options=None, timeout=600,
          gateway_factory=OpenAICompatibleGateway) -> Path:
    """シーン k 以降を退避・再生成し、Assemble まで実行する。"""
    config = load_backend(config_path, backend)
    directory = run.open_run(run_dir)
    prepared = writing_phase.prepare_writing(config, thinking_options)
    inputs = writing_phase.prepare_input(directory, first)
    # --from 1 は stage writing と同じ範囲(04 全体)を退避する。
    with Operation(directory, "write", config=config, backend=backend, first=first,
                   inputs=inputs[2], prompts={"prompts/writing/system.md": prepared.system},
                   request_bodies={"writing": prepared.body}) as operation:
        operation.step = "archive"
        operation.archive = (run.archive_downstream(directory, "writing") if first == 1
                             else run.archive_from_scene(directory, first))
        operation.step = "writing"
        writing_phase.run_writing(directory, config, first=first, backend=backend,
                                  thinking_options=thinking_options, timeout=timeout,
                                  gateway_factory=gateway_factory, prepared=prepared, inputs=inputs)
    return directory


def assemble(run_dir: Path | str) -> Path:
    """04を正として再結合する。毎回古い評価を退避して未評価へ戻す(D55)。"""
    directory = run.open_run(run_dir)
    idea, fingerprint = read_source(directory / run.INPUT)
    if not idea.strip():
        raise run.RunError("Input must not be empty.")
    hashes = {run.INPUT: fingerprint}
    plot = structure_phase.load_plot(directory, fingerprints=hashes)
    novel = complete_novel(directory, plot, fingerprints=hashes)
    draft, template = draft_text(novel), evaluation.render_template(plot)
    with Operation(directory, "assemble", inputs=hashes) as operation:
        saved = []
        try:
            operation.step = "archive"
            operation.archive = run.archive_downstream(directory, "assemble")
            operation.step = "save_draft"
            run.atomic_write(directory / run.DRAFT, draft)
            saved.append(run.DRAFT)
            operation.step = "save_evaluation"
            run.atomic_write(directory / run.EVAL, template)
            saved.append(run.EVAL)
        except OSError:
            raise run.RunError(f"Assemble save failed; archive: {operation.archive}; saved: {saved}.") from None
        writing_phase.show_lengths(novel)
    return directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GenkaiNovelWriter")
    commands = parser.add_subparsers(dest="command", required=True)

    assemble_help = "保存済み04を再結合する。毎回旧05/06/07を退避し、評価を未評価へ戻す"
    command = commands.add_parser("assemble", help=assemble_help, description=assemble_help)
    command.add_argument("--run", type=Path, dest="run_dir", required=True)

    command = commands.add_parser("run", help="生成部分を一括実行し、人手評価テンプレートを保存する")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path)
    command.add_argument("--timeout", type=float, default=600)

    command = commands.add_parser("baseline", help="一発生成でベースラインを出力する")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path,
                         help="thinking を true/false にしたモデル用の on/off リクエスト本文(U2 検証用)")
    command.add_argument("--timeout", type=float, default=600)

    command = commands.add_parser("stage", help="フェーズを1つだけ実行する")
    command.add_argument("phase", choices=("concept", "structure", "writing", "check"))
    command.add_argument("--allow-name", action="append", default=[], dest="allowed_names",
                         help="stage check の英字固有名の明示許可(繰り返し指定可)")
    command.add_argument("--run", type=Path, dest="run_dir", help="既存の実行ディレクトリ")
    command.add_argument("--input", type=Path,
                         help="stage concept のみ。新しい実行ディレクトリを作って始める")
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path)
    command.add_argument("--timeout", type=float, default=600)

    command = commands.add_parser("write", help="シーンk以降を再生成して結合する")
    command.add_argument("--run", type=Path, dest="run_dir", required=True)
    command.add_argument("--from", type=int, dest="first", required=True)
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path)
    command.add_argument("--timeout", type=float, default=600)

    args = parser.parse_args(argv)
    if args.command == "stage":
        if args.allowed_names and args.phase != "check":
            parser.error("--allow-name is only available for stage check.")
        if args.phase == "concept" and bool(args.run_dir) == bool(args.input):
            parser.error("stage concept needs exactly one of --run or --input.")
        if args.phase != "concept" and args.run_dir is None:
            parser.error(f"stage {args.phase} needs --run.")
        if args.phase != "concept" and args.input is not None:
            parser.error(f"stage {args.phase} does not accept --input.")

    try:
        if args.command == "assemble":
            directory = assemble(args.run_dir)
        elif args.command == "run":
            directory = run_pipeline(args.input, config_path=args.config, backend=args.backend,
                                     thinking_options=args.thinking_options, timeout=args.timeout)
        elif args.command == "baseline":
            directory = baseline(args.input, config_path=args.config, backend=args.backend,
                                 thinking_options=args.thinking_options, timeout=args.timeout)
        elif args.command == "write":
            directory = write(args.run_dir, first=args.first, config_path=args.config,
                              backend=args.backend, thinking_options=args.thinking_options,
                              timeout=args.timeout)
        else:
            directory = stage(args.phase, run_dir=args.run_dir, input_path=args.input,
                              config_path=args.config, backend=args.backend,
                              thinking_options=args.thinking_options, timeout=args.timeout,
                              allowed_names=args.allowed_names)
    except REPORTABLE as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        # SDK の例外には鍵やリクエスト本文が含まれうるので種別だけ出す。詳細は calls.jsonl。
        print(f"{type(error).__name__}: {args.command} failed; check input/config and calls.jsonl",
              file=sys.stderr)
        return 1
    print(directory)
    if getattr(args, "backend", None) == "remote":
        print("OpenRouter: 動作確認専用。品質評価には使用しない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
