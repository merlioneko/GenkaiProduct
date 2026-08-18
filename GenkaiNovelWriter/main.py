from util.gateway import connect_lm_studio, generate_text
from util.file import read_prompt, read_pipeline_prompt, read_model

# user_idea = input("Enter your idea: ")

# Generate improved idea
user_idea = read_prompt("prompts/user_prompt.txt")

client = connect_lm_studio(read_model("model.md"))
print("接続成功: OpenAI APIに接続しました。")

improved_idea = generate_text(client, read_pipeline_prompt("prompts/system_improving.md"), user_idea)
print("改善されたアイデア:", improved_idea)

structured_idea = generate_text(client, read_pipeline_prompt("prompts/system_structuring.md"), improved_idea)
print("構造化されたアイデア:", structured_idea)

writtens = ""
for i in ["起","承","転","結"]:
    add_prompt = f"""
# Writing Request
あなたは「{i}」のシーンを執筆してください。
"""
    writtens += generate_text(client, read_pipeline_prompt("prompts/system_writing.md"), structured_idea+add_prompt)

print(writtens)