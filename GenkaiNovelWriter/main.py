from datetime import datetime
from rich.console import Console

from util.gateway import connect_lm_studio, connect_openrouter
from util.file import read_prompt, output_creation
from util.env import ModelConfig
from novel.engine import improving, structuring, writing

console = Console()

# Generate improved idea ... ユーザプロンプトの入力があれば
try:
    user_idea = read_prompt("prompts/user_prompt.txt")
    if not user_idea or user_idea == "":
        raise RuntimeError("Illegal values input")
except:
    user_idea = input("Enter your idea: ")

directory_path = f"creations/output-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
output_creation(directory_path, "00_user_prompt.txt", user_idea)
try:
    model_config = ModelConfig()
    client = connect_openrouter(model_config.get_writer())
    output_creation(directory_path, "01_model_config.txt", str(model_config))
    console.print("[red]接続成功: OpenAI APIに接続しました。[/red]")
    #input("Enterを押すと処理を開始します。")

    improved_idea = improving(client, user_idea)
    output_creation(directory_path, "02_improved_idea.txt", improved_idea)
    console.print("[green]改善されたアイデア:[/green]", improved_idea)
    #input("Enterを押すと処理を開始します。")

    plot = structuring(client, improved_idea)
    output_creation(directory_path, "03_plot.txt", str(plot))
    console.print("[green]構造化されたアイデア:[/green]", plot)
    #input("Enterを押すと処理を開始します。")

    novel = writing(client, plot)
    output_creation(directory_path, "04_novel.txt", "\n\n".join([str(scene) for scene in novel]))

    console.print("[green]生成された小説:[/green]", novel)
except ConnectionError as ce:
    console.print("[red]接続エラー:[/red]", ce)
except Exception as e:
    print(e)
