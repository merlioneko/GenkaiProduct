from util.file import read_pipeline_prompt
from util.gateway import generate_text
import json

"""
具体的なパイプライン処理を担うモジュール

TODO: fileにあるパイプライン処理関係のも可能ならこっちに移す(mainを完全にこっちに移行できれば…)
"""

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

