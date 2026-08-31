from util.file import read_pipeline_prompt
from util.gateway import generate_text
from novel.plot import Plot
from novel.parse import *
import json

"""
具体的なパイプライン処理を担うモジュール

TODO: fileにあるパイプライン処理関係のも可能ならこっちに移す(mainを完全にこっちに移行できれば…)
TODO: 【要相談】gateway操作とデータ操作は分けた方がいいだろうか？
TODO: 【要相談】設定において、パースに失敗したらどうするか？本当は聞き返すのがいいんだろうが…
"""

def parse_plot(structured_data: dict) -> Plot:
    """
    Jsonからcharacters, setting, scenesを分解する
    基本的にcharacter/sceneの取り出しは明確に取れるようにする。
    settingはそれ以外のものを全て取得することにする。
    """

    characters = []
    settings = []
    scenes = []

    for key, value in structured_data:
        match key:
            case "Character": characters.extend(parse_chara(value))
            case "Scenes": scenes.extend(parse_scene(value))
            case _: settings.extend(parse_setting(value))

    return Plot(characters, settings, scenes)

def improving(client, user_idea):
    """
    アイデアを膨らませて構想を作成する。Jsonで返す
    TODO: historyを持たせたい（gatewayの設計変更必須）
    """
    try_count = 5
    for _ in range(try_count):
        improved_idea = generate_text(client,
                                    read_pipeline_prompt("prompts/system_improving.md"),
                                    user_idea)
        try:
            return json.loads(improved_idea)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Parse Error. LLM cannot create json data")

def structuring(client, improved_data):
    try_count = 0
    for _ in range(try_count):
        structured_idea = generate_text(client, read_pipeline_prompt("prompts/system_structuring.md"),improved_data)
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