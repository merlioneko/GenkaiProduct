"""Writing の入力を SPEC の順序で組み立てる。本文は毎回ファイルから読む。"""

import json
from pathlib import Path

from novel import run
from novel.schema import Novel, NovelScene, Plot
from novel.history import read_source
from util.gateway import create_messages


def load_novel(directory: Path | str, plot: Plot, *, until: int | None = None,
               fingerprints=None) -> Novel:
    """1〜until-1 (未指定なら全シーン)を読む。欠落・空本文は修復しない。"""
    stop = len(plot.scenes) + 1 if until is None else until
    if not 1 <= stop <= len(plot.scenes) + 1:
        raise run.RunError(f"Scene boundary out of range: {stop}")
    scenes = []
    for number in range(1, stop):
        path = run.scene_path(directory, number)
        if not path.is_file():
            raise run.RunError(f"Missing prior scene: {path.name}")
        content, fingerprint = read_source(path)
        if not content.strip():
            raise run.RunError(f"Empty scene: {path.name}")
        scenes.append(NovelScene(index=number, title=plot.scenes[number - 1].name, content=content))
        if fingerprints is not None:
            fingerprints[f"{run.SCENES}/{path.name}"] = fingerprint
    return Novel(scenes=scenes)


def complete_novel(directory: Path | str, plot: Plot, *, fingerprints=None) -> Novel:
    expected = [run.scene_path(directory, i) for i in range(1, len(plot.scenes) + 1)]
    if run.scene_paths(directory) != expected:
        raise run.RunError("Requires exactly the completed scenes listed in Plot.")
    return load_novel(directory, plot, fingerprints=fingerprints)


def draft_text(novel: Novel) -> str:
    return "\n\n".join(scene.content for scene in novel.scenes) + "\n"


def writing_messages(directory: Path | str, plot: Plot, number: int, system: str,
                     *, novel: Novel | None = None) -> list:
    if not 1 <= number <= len(plot.scenes):
        raise run.RunError(f"Scene number must be between 1 and {len(plot.scenes)}: {number}")
    if novel is None:
        novel = load_novel(directory, plot, until=number)
    scene = plot.scenes[number - 1]

    def dump(value):
        return json.dumps(value, ensure_ascii=False, indent=2)

    elements = {"constraints": plot.constraints,
                "events": [{"number": i, "event": event} for i, event in enumerate(plot.events, 1)]}
    outline = [{"number": i, "name": item.name, "beats": item.beats, "担当": i == number}
               for i, item in enumerate(plot.scenes, 1)]
    user = "\n\n".join([
        "# meta\n" + dump(plot.meta.model_dump()),
        "# 指定要素\n" + dump(elements),
        "# 登場人物・設定\n" + dump({
            "characters": [item.model_dump() for item in plot.characters],
            "settings": [item.model_dump() for item in plot.settings],
        }),
        f"# 全シーンの一覧 (担当: {number})\n" + dump(outline),
        "# 既存シーンの本文 (1〜担当直前、全文)\n" + novel.context_until(number),
        f"# 担当シーン {number}\n" + dump({
            "opening": scene.opening.model_dump(), "beats": scene.beats,
            "target_chars": scene.target_chars,
        }),
    ])
    return create_messages(system=system, user=user)
