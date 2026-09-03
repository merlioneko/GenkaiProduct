from util.gateway import connect_lm_studio, connect_openrouter
from util.file import read_prompt
from util.env import ModelConfig
from novel.engine import improving, structuring, writing

# Generate improved idea ... ユーザプロンプトの入力があれば
try:
    user_idea = read_prompt("prompts/user_prompt.txt")
    if not user_idea or user_idea == "":
        raise RuntimeError("Illegal values input")
except:
    user_idea = input("Enter your idea: ")

try:
    model_config = ModelConfig()
    client = connect_openrouter(model_config.get_writer())
    print("接続成功: OpenAI APIに接続しました。")
    input("Enterを押すと処理を開始します。")

    improved_idea = improving(client, user_idea)
    print("改善されたアイデア:", improved_idea)
    input("Enterを押すと処理を開始します。")

    plot = structuring(client, improved_idea)
    print("構造化されたアイデア:", plot)
    input("Enterを押すと処理を開始します。")

    novel = writing(client, plot)

    print(novel)
except ConnectionError as ce:
    print(ce)
except Exception as e:
    print(e)
