from util.gateway import connect_lm_studio, connect_openrouter
from util.file import read_file, output_creation, read_json
from util.env import ModelConfig
from novel.engine import improving, structuring, writing, extract_tail, extract_head
from novel.novel import NovelScene

# Writingが終わりました～～という体
contents = []
for n in range(6):
    try:
        content = read_json(f"creations/output-20260904-124615/scene-0{n+1}.json")
        scene = NovelScene(
                        title=content["Scene Title"],
                        content="\n\n".join(content["Content"]),
                        notes=content["Notes"]
                    )
        print(scene)
        contents.append(scene)
    except Exception as e:
        print(f"{n}: なんか駄目でした。\n{e}")

pairs = [
    (
        extract_tail(contents[i - 1].content),
        extract_head(contents[i].content),
    )
    for i in range(1, len(contents))
]
for pair in pairs:
    print(f"tail: {pair[0]}")
    print(f"head: {pair[1]}")

input("oksk?")

config = ModelConfig()
try:
    gateway = connect_openrouter(model=config.get_model(role="writer"))
except Exception as e:
    print(e)
    exit()


