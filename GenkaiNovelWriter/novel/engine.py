from typing import cast
import re

from util.file import read_pipeline_prompt
from util.gateway import generate_text, generate_formated
from novel.plot import Plot
from novel.novel import NovelScene
from novel.novel import (WritingResult, SceneWritingResult, GenerationError,
                         BorderCheckInput, BorderCheckResult, BorderCheckReport)

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

def writing(client, plot: Plot, *, generate=None, prompt: str | None = None,
            on_scene=None) -> WritingResult:
    generate = generate or generate_text
    if prompt is None:
        prompt = read_pipeline_prompt("prompts/system_writing.md")
    novel = []
    for index, scene in enumerate(plot.Scenes):
        try:
            content = generate(gateway=client,
                                   system=prompt,
                                   user=f"Plot: {plot}\nあなたはこのプロットにおける、シーン「{scene.name}」の小説を書きます。")
            result = SceneWritingResult(scene_index=index, title=scene.name,
                status="success", scene=NovelScene(title=scene.name, content=content))
        except Exception as e:
            result = SceneWritingResult(scene_index=index, title=scene.name,
                status="failed", error=GenerationError(type=type(e).__name__, message=str(e)))
        novel.append(result)
        # Persistence errors must propagate, rather than look like generation failures.
        if on_scene is not None:
            on_scene(result)
    return WritingResult(results=novel)

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
    result = inspect_border(BorderCheckInput(before_index=0, after_index=1,
        tail=extract_tail(scene_before.content, budget, window),
        head=extract_head(scene_after.content, budget, window), budget=budget, window=window))
    return result.status == "passed"

def inspect_border(data: BorderCheckInput) -> BorderCheckResult:
    """Record the existing punctuation heuristic, not a semantic review."""
    if not data.tail or not data.head:
        return BorderCheckResult(input=data, status="not_checked",
                                 reasons=["境界の抜粋が空です。"])
    reasons = []
    if data.tail[-1] not in "。！？":
        reasons.append("前のシーンの末尾が句点・感嘆符・疑問符ではありません。")
    if data.head[0] not in "「『":
        reasons.append("次のシーンの冒頭が会話の括弧ではありません。")
    return BorderCheckResult(input=data, status="failed" if reasons else "passed",
                             reasons=reasons)


def elaboration(novel_scenes: WritingResult, budget: int = 1000,
                window: float = 1.5) -> BorderCheckReport:
    """Inspect original adjacent scenes; regeneration remains a separate stage."""
    checks = []
    for before, after in zip(novel_scenes.results, novel_scenes.results[1:]):
        data = BorderCheckInput(before_index=before.scene_index,
            after_index=after.scene_index, budget=budget, window=window,
            tail=extract_tail(before.scene.content, budget, window) if before.scene else "",
            head=extract_head(after.scene.content, budget, window) if after.scene else "")
        if before.status == "failed" or after.status == "failed":
            checks.append(BorderCheckResult(input=data, status="not_checked",
                                           reasons=["隣接するシーンの生成に失敗しています。"]))
        else:
            checks.append(inspect_border(data))
    return BorderCheckReport(checks=checks)

