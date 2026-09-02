from util.file import read_pipeline_prompt
from util.gateway import generate_text
from novel.plot import Plot, parse_plot
import json

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
    try_count = 0
    for _ in range(try_count):
        structured_idea = generate_text(gateway=client,
                                        system=read_pipeline_prompt("prompts/system_structuring.md"),
                                        user=improved_data)
        try:
            json_data = json.loads(structured_idea)
            return parse_plot(json_data)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Parse Error. LLM cannot create json data")

def writing(client, plot: Plot):
    novel = ""
    for scene in plot.scenes:
        novel += generate_text(client,
                               read_pipeline_prompt("prompts/system_writing.md"),
                               scene)
    return novel