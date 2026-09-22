"""GenkaiNovelWriter CLI。

サブコマンドごとに1関数。中身は「設定を読む → 実行ディレクトリを作る → フェーズを呼ぶ → ファイルに書く」の直線。
現在は baseline と stage concept / stage structure。run / write は M3 以降で追加する(SPEC.md「CLI」)。
"""

import argparse
import sys
from pathlib import Path

from novel import checks, run
from novel.phases import concept as concept_phase
from novel.phases import structure as structure_phase
from novel.run import CREATIONS, create_output_dir
from util.config import (
    DEFAULT_CONFIG, PROJECT_ROOT, ConfigError, load_backend,
    load_thinking_options, thinking_body,
)
from util.gateway import OpenAICompatibleGateway, create_message

# 自分の例外だけは文面を出す。秘密の値を含まないため。
REPORTABLE = (ConfigError, run.RunError, concept_phase.ConceptFormatError,
              structure_phase.PlotFormatError, structure_phase.StructureError)


def baseline(input_path: Path, *, config_path=DEFAULT_CONFIG, backend="local",
             thinking_options=None, output_root=None, timeout=600,
             gateway_factory=OpenAICompatibleGateway) -> Path:
    """一発生成(U1 の比較用)。creations/baseline-*/ に 00_input.txt・baseline.md・calls.jsonl を書く。"""
    idea = Path(input_path).read_text(encoding="utf-8")
    if not idea.strip():
        raise ValueError("Input must not be empty.")
    config = load_backend(config_path, backend)
    phase = config.phase("baseline")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    prompt = (PROJECT_ROOT / "prompts/baseline/system.md").read_text(encoding="utf-8")

    directory = create_output_dir(Path(output_root or CREATIONS), "baseline-")
    (directory / "00_input.txt").write_text(idea, encoding="utf-8")
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="baseline", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / "calls.jsonl", timeout=timeout,
    ) as gateway:
        text = gateway.text(create_message(system=prompt, user=idea))
    (directory / "baseline.md").write_text(text, encoding="utf-8")
    return directory


def stage(name: str, *, run_dir=None, input_path=None, config_path=DEFAULT_CONFIG,
          backend="local", thinking_options=None, output_root=None, timeout=600,
          gateway_factory=OpenAICompatibleGateway) -> Path:
    """フェーズを1つだけ実行する。実行前に下流の成果物を退避する(D23)。"""
    config = load_backend(config_path, backend)
    if name == "concept" and run_dir is None:
        directory = run.create_run(input_path, output_root=output_root)
    else:
        directory = run.open_run(run_dir)
    run.archive_downstream(directory, name)
    run.save_config_snapshot(directory, backend, config)
    options = {"backend": backend, "thinking_options": thinking_options,
               "timeout": timeout, "gateway_factory": gateway_factory}

    if name == "concept":
        concept_phase.run_concept(directory, config, **options)
        concept_phase.verify_concept(directory, config, **options)
    else:
        plot = structure_phase.run_structure(directory, config, **options)
        checks.save_plot_report(directory, checks.check_plot(plot))
    return directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GenkaiNovelWriter")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("baseline", help="一発生成でベースラインを出力する")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path,
                         help="thinking を true/false にしたモデル用の on/off リクエスト本文(U2 検証用)")
    command.add_argument("--timeout", type=float, default=600)

    command = commands.add_parser("stage", help="フェーズを1つだけ実行する")
    command.add_argument("phase", choices=("concept", "structure"))
    command.add_argument("--run", type=Path, dest="run_dir", help="既存の実行ディレクトリ")
    command.add_argument("--input", type=Path,
                         help="stage concept のみ。新しい実行ディレクトリを作って始める")
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path)
    command.add_argument("--timeout", type=float, default=600)

    args = parser.parse_args(argv)
    if args.command == "stage":
        if args.phase == "concept" and bool(args.run_dir) == bool(args.input):
            parser.error("stage concept needs exactly one of --run or --input.")
        if args.phase != "concept" and args.run_dir is None:
            parser.error(f"stage {args.phase} needs --run.")

    try:
        if args.command == "baseline":
            directory = baseline(args.input, config_path=args.config, backend=args.backend,
                                 thinking_options=args.thinking_options, timeout=args.timeout)
        else:
            directory = stage(args.phase, run_dir=args.run_dir, input_path=args.input,
                              config_path=args.config, backend=args.backend,
                              thinking_options=args.thinking_options, timeout=args.timeout)
    except REPORTABLE as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        # SDK の例外には鍵やリクエスト本文が含まれうるので種別だけ出す。詳細は calls.jsonl。
        print(f"{type(error).__name__}: {args.command} failed; check input/config and calls.jsonl",
              file=sys.stderr)
        return 1
    print(directory)
    if args.backend == "remote":
        print("OpenRouter: 動作確認専用。品質評価には使用しない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
