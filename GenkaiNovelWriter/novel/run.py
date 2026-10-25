"""実行ディレクトリの作成・成果物パスの解決・退避(SPEC.md「実行ディレクトリ」「退避」D23)。

ファイル名の正は SPEC.md の表であり、その名前をこのモジュールの定数に写している。
フェーズ関数はここからパスを受け取って読み書きする。gateway・prompts・schema は import しない。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from util.config import PROJECT_ROOT

CREATIONS = PROJECT_ROOT / "creations"

# SPEC.md「実行ディレクトリ」の表。実行ディレクトリ直下の相対パス。
INPUT = "00_input.txt"
CONFIG_SNAPSHOT = "01_config.json"
CONCEPT = "02_concept.md"
CONCEPT_REPORT = "02_concept_report.json"
PLOT = "03_plot.json"
PLOT_REPORT = "03_plot_report.json"
# スキーマに適合しなかったときの生出力(SPEC.md「Structure」)。成功時は作られない。
PLOT_RAW = "03_plot_raw.txt"
SCENES = "04_scenes"
DRAFT = "05_draft.md"
CHECK = "06_check"
CHECK_REPORT = "06_check_report.md"
EVAL = "07_eval.md"
CALLS = "calls.jsonl"
ARCHIVE = "_archive"

# SPEC.md「退避」の表。キーは実行したステージ、値はそのステージが退避する下流の成果物。
DOWNSTREAM = {
    "concept": [CONCEPT, CONCEPT_REPORT, PLOT, PLOT_REPORT, PLOT_RAW, SCENES, DRAFT, CHECK, CHECK_REPORT, EVAL],
    "structure": [PLOT, PLOT_REPORT, PLOT_RAW, SCENES, DRAFT, CHECK, CHECK_REPORT, EVAL],
    "writing": [SCENES, DRAFT, CHECK, CHECK_REPORT, EVAL],
    "check": [CHECK, CHECK_REPORT],
}


class RunError(ValueError):
    pass


def create_output_dir(root: Path, prefix: str) -> Path:
    """<root>/<prefix><時刻>/ を作る。同じ秒に作られた場合は連番を付ける。"""
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


def create_run(input_path: Path | str, *, output_root: Path | str | None = None) -> Path:
    """新しい実行ディレクトリを作り、00_input.txt を書く。"""
    idea = Path(input_path).read_text(encoding="utf-8")
    if not idea.strip():
        raise ValueError("Input must not be empty.")
    directory = create_output_dir(Path(output_root or CREATIONS), "")
    (directory / INPUT).write_text(idea, encoding="utf-8")
    return directory


def open_run(directory: Path | str) -> Path:
    """既存の実行ディレクトリを開く(stage / write 用)。無ければ停止する。"""
    directory = Path(directory)
    if not directory.is_dir():
        raise RunError(f"Run directory not found: {directory}")
    if not (directory / INPUT).is_file():
        raise RunError(f"Not a run directory (no {INPUT}): {directory}")
    return directory


def read_input(directory: Path | str) -> str:
    return (Path(directory) / INPUT).read_text(encoding="utf-8")


def save_config_snapshot(directory: Path | str, backend: str, config) -> Path:
    """01_config.json。どのモデルで作った成果物かを後から特定するため。api_key は書かない。"""
    snapshot = {
        "backend": backend,
        "base_url": config.base_url,
        "context_length": config.context_length,
        "phases": {name: {"model": phase.model, "thinking": phase.thinking}
                   for name, phase in config.phases.items()},
    }
    path = Path(directory) / CONFIG_SNAPSHOT
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def scene_path(directory: Path | str, number: int) -> Path:
    if number < 1:
        raise RunError(f"Scene number must be 1 or greater: {number}")
    return Path(directory) / SCENES / f"scene_{number:02d}.md"


def scene_number(path: Path) -> int:
    """scene_03.md → 3。想定外の名前は、黙って飛ばさずエラーにする(D24 と同じ理由)。"""
    stem = path.stem
    if not stem.startswith("scene_") or not stem[len("scene_"):].isdigit():
        raise RunError(f"Unexpected file in {SCENES}: {path.name}")
    return int(stem[len("scene_"):])


def scene_paths(directory: Path | str) -> list[Path]:
    """存在する scene_NN.md を番号順に返す。"""
    folder = Path(directory) / SCENES
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.md"), key=scene_number)


def check_path(directory: Path | str, item: str) -> Path:
    return Path(directory) / CHECK / f"{item}.json"


def archive(directory: Path | str, targets: list[str]) -> Path | None:
    """targets のうち存在するものを _archive/<時刻>/ に、元の相対パスを保って移動する。

    削除はしない(D23)。退避するものが無ければ何も作らず None を返す。
    """
    directory = Path(directory)
    present = [name for name in targets if (directory / name).exists()]
    if not present:
        return None
    destination = create_output_dir(directory / ARCHIVE, "")
    for name in present:
        moved = destination / name
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory / name), str(moved))
    return destination


def archive_downstream(directory: Path | str, stage: str) -> Path | None:
    """stage <名前> を実行する前に、その下流の成果物を退避する。"""
    if stage not in DOWNSTREAM:
        raise RunError(f"Unknown stage: {stage}")
    return archive(directory, DOWNSTREAM[stage])


def archive_from_scene(directory: Path | str, first: int) -> Path | None:
    """write --from k を実行する前に、シーン k 以降と 05・06・07 を退避する。"""
    if first < 1:
        raise RunError(f"Scene number must be 1 or greater: {first}")
    scenes = [f"{SCENES}/{path.name}" for path in scene_paths(directory)
              if scene_number(path) >= first]
    return archive(directory, scenes + [DRAFT, CHECK, CHECK_REPORT, EVAL])
