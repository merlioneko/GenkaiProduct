"""M1 CLI. Importing this module does not run generation."""

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
    parser = argparse.ArgumentParser(description="GenkaiNovelWriter (M1)")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("baseline", help="Generate a standalone short story")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--backend", choices=("local", "remote"), default="local")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command.add_argument("--thinking-options", type=Path,
                         help="Per-model on/off request bodies under U2 verification")
    command.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        directory = baseline(args.input, config_path=args.config, backend=args.backend,
                             thinking_options=args.thinking_options, timeout=args.timeout)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except Exception as error:
        # SDK errors may contain credentials or private request data.
        print(f"{type(error).__name__}: baseline failed; check input/config and calls.jsonl", file=sys.stderr)
        return 1
    print(directory)
    if args.backend == "remote":
        print("OpenRouter: 動作確認専用。品質評価には使用しない。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
