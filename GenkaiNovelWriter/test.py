from util.gateway import connect_lm_studio, generate_text, connect_openrouter
from util.file import read_prompt, read_pipeline_prompt, read_model

# user_idea = input("Enter your idea: ")

# Generate improved idea
user_idea = "かっこいい女の子が冒険する話"

try:
    #client = connect_lm_studio(read_model("model.md"))
    client = connect_openrouter("inclusionai/ling-3.0-flash-fin:free")
    print("接続成功: OpenAI APIに接続しました。")
except Exception as e:
    print(f"駄目みたいですね（諦観）\n{e}")