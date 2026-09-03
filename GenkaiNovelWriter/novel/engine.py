from typing import cast

from util.file import read_pipeline_prompt
from util.gateway import generate_text, generate_formated
from novel.plot import Plot

"""
具体的なパイプライン処理を担うモジュール

TODO: fileにあるパイプライン処理関係のも可能ならこっちに移す(mainを完全にこっちに移行できれば…)
TODO: 【要相談】gateway操作とデータ操作は分けた方がいいだろうか？
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
    novel = ""
    for scene in plot.Scenes:
        novel += generate_text(gateway=client,
                               system=read_pipeline_prompt("prompts/system_writing.md"),
                               user=f"Scene: {scene.name}\nSummary: {scene.summary}")
    return novel