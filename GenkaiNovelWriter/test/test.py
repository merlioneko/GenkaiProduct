from util.gateway import connect_lm_studio, generate_text, generate_with_search, connect_openrouter
from util.file import read_prompt, read_pipeline_prompt
from util.tools import Tavily
from util.env import ModelConfig

# user_idea = input("Enter your idea: ")

# Generate improved idea
user_idea = "かっこいい女の子が冒険する話"

user_question = f"最近強いLLMについて教えてください。"

model_config = ModelConfig()
client = connect_openrouter(model_config.get_writer())
print("接続成功: OpenAI APIに接続しました。")

try:
    #client = connect_lm_studio(read_model("model.md"))
    client = connect_openrouter("inclusionai/ling-3.0-flash-fin:free")
    print("接続成功: OpenAI APIに接続しました。")
except Exception as e:
    print(f"駄目みたいですね（諦観）\n{e}")
