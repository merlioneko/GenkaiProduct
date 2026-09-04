from typing import cast
import re

from util.file import read_pipeline_prompt
from util.gateway import generate_text, generate_formated
from novel.plot import Plot
from novel.novel import NovelScene

"""
具体的なパイプライン処理を担うモジュール

TODO: fileにあるパイプライン処理関係のも可能ならこっちに移す(mainを完全にこっちに移行できれば…)
TODO: 【要相談】設定において、パースに失敗したらどうするか？本当は聞き返すのがいいんだろうが…
TODO: engineという名前が大げさすぎた説がある
"""

def improving(client, user_idea):
    """
    アイデアを膨らませて構想を作成する。ここはまだ平文
    """
    improved_idea = generate_text(gateway=client,
                                system=read_pipeline_prompt("prompts/system_improving.md"),
                                user=user_idea)
    return improved_idea

def structuring(client, improved_data):
    structured_idea = generate_formated(gateway=client,
                                    system=read_pipeline_prompt("prompts/system_structuring.md"),
                                    user=improved_data,
                                    base_model=Plot)
    return cast(Plot, structured_idea)

def writing(client, plot: Plot):
    novel = []
    for scene in plot.Scenes:
        try:
            content = generate_text(gateway=client,
                                   system=read_pipeline_prompt("prompts/system_writing.md"),
                                   user=f"Plot: {plot}\nあなたはこのプロットにおける、シーン「{scene.name}」の小説を書きます。")
            novel.append(NovelScene(title=scene.name, content=content))
        except Exception as e:
            print(f"Error occurred while generating content for scene '{scene.name}': {e}")
    return novel

def extract_tail(text: str, budget: int = 1000, window: float = 1.5) -> str:
    w = int(budget * window)
    chunk = text[-w:] if len(text) > w else text
    # 段落境界を優先して探す（窓の先頭寄りの最初の空行）
    para_match = re.search(r"\n\s*\n", chunk)
    if para_match:
        return chunk[para_match.end():]
    # 文境界にフォールバック
    sent_matches = list(re.finditer(r"[。！？」]", chunk[:budget] if len(chunk) > budget else chunk))
    if sent_matches:
        return chunk[sent_matches[0].end():]
    # 強制カット
    return chunk[-budget:]

def extract_head(text: str, budget: int = 1000, window: float = 1.5) -> str:
    w = int(budget * window)
    chunk = text[:w] if len(text) > w else text
    # 段落境界を優先して探す（窓の末尾寄りの最後の空行）
    para_matches = list(re.finditer(r"\n\s*\n", chunk))
    if para_matches:
        return chunk[:para_matches[-1].start()]
    # 文境界にフォールバック
    sent_matches = list(re.finditer(r"[。！？」]", chunk[:budget] if len(chunk) > budget else chunk))
    if sent_matches:
        return chunk[:sent_matches[-1].end()]
    # 強制カット
    return chunk[:budget]

def check_border(scene_before: NovelScene, scene_after: NovelScene, budget: int = 1000, window: float = 1.5) -> bool:
    """
    2つのシーンの境界をチェックする。境界が不自然な場合はFalseを返す。
    """
    tail_before = extract_tail(scene_before.content, budget=budget, window=window)
    head_after = extract_head(scene_after.content, budget=budget, window=window)
    # 境界が不自然な場合はFalseを返す
    if tail_before and head_after:
        if tail_before[-1] not in "。！？":
            return False
        if head_after[0] not in "「『":
            return False
    return True

def elaboration(novel_scenes: list[NovelScene]):
    """
    小説の各シーンを精緻化する。境界が不自然な場合は、前後のシーンを再生成する。
    """
    for i in range(len(novel_scenes) - 1):
        scene_before = novel_scenes[i]
        scene_after = novel_scenes[i + 1]
        if not check_border(scene_before, scene_after):
            # 境界が不自然な場合は、前後のシーンを再生成する
            print(f"境界が不自然なため、シーン {scene_before.title} と {scene_after.title} を再生成します。")
            # 再生成の処理をここに追加する
            # 例: scene_before.content = generate_text(...) など

