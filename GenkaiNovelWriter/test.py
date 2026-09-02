from util.gateway import connect_lm_studio, generate_text, generate_with_search
from util.file import read_prompt, read_pipeline_prompt, read_model
from util.tools import Tavily

# user_idea = input("Enter your idea: ")

# Generate improved idea
user_idea = "かっこいい女の子が冒険する話"

user_question = f"最近強いLLMについて教えてください。"

client = connect_lm_studio(read_model("model.md"))
print("接続成功: OpenAI APIに接続しました。")

tool = Tavily()
answer = generate_with_search(client, "ユーザの質問を分析し、適切な回答を提供する。", user_question, tool)
print(f"ユーザの質問: {user_question}")
print(f"AIの回答: {answer}")