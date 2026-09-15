"""GenkaiNovelWriter CLI。

サブコマンドごとに1関数。中身は「設定を読む → 実行ディレクトリを作る → フェーズを呼ぶ → ファイルに書く」の直線。
現在は M1 の baseline のみ。run / stage / write は M2 以降で追加する(SPEC.md「CLI」)。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from util.config import (
    DEFAULT_CONFIG, PROJECT_ROOT, ConfigError, load_backend,
    load_thinking_options, thinking_body,
)
from util.gateway import OpenAICompatibleGateway, create_message


def create_output_dir(root: Path, prefix: str) -> Path:
    """creations/<prefix><時刻>/ を作る。同じ秒に作られた場合は連番を付ける。"""
    root.mkdir(parents=True, exist_ok=True)
    stem = prefix + datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in range(10000):
        path = root / (stem if suffix == 0 else f"{stem}-{suffix:02d}")
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise FileExistsError("Cannot allocate a new output directory.")


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

    directory = create_output_dir(Path(output_root or PROJECT_ROOT / "creations"), "baseline-")
    (directory / "00_input.txt").write_text(idea, encoding="utf-8")
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="baseline", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / "calls.jsonl", timeout=timeout,
    ) as gateway:
        text = gateway.text(create_message(system=prompt, user=idea))
    (directory / "baseline.md").write_text(text, encoding="utf-8")
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

    args = parser.parse_args(argv)
    try:
        directory = baseline(args.input, config_path=args.config, backend=args.backend,
                             thinking_options=args.thinking_options, timeout=args.timeout)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        # SDK の例外には鍵やリクエスト本文が含まれうるので種別だけ出す。詳細は calls.jsonl。
        print(f"{type(error).__name__}: baseline failed; check input/config and calls.jsonl", file=sys.stderr)
        return 1
    print(directory)
    if args.backend == "remote":
        print("OpenRouter: 動作確認専用。品質評価には使用しない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
