from util.gateway import connect, generate_text
from util.file import read_prompt, read_pipeline_prompt, read_model

# user_idea = input("Enter your idea: ")

# Generate improved idea
user_idea = "かっこいい女の子が冒険する話"

client = connect(read_model("model.md"))
print("接続成功: OpenAI APIに接続しました。")