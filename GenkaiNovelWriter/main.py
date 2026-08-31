from util.gateway import connect_lm_studio, generate_text
from util.file import read_prompt, read_pipeline_prompt, read_model
from novel.engine import improving, structuring, writing

# Generate improved idea ... ユーザプロンプトの入力があれば
try:
    user_idea = read_prompt("prompts/user_prompt.txt")
    if not user_idea or user_idea == "":
        raise RuntimeError("Illegal values input")
except:
    user_idea = input("Enter your idea: ")

try:
    client = connect_lm_studio(read_model("model.md"))
    print("接続成功: OpenAI APIに接続しました。")

    improved_idea = improving(client, user_idea)
    print("改善されたアイデア:", improved_idea)

    plot = structuring(client, improved_idea)
    print("構造化されたアイデア:", plot)

    novel = writing(client, plot)

    print(novel)
except ConnectionError as ce:
    print(ce)
except Exception as e:
    print(e)
