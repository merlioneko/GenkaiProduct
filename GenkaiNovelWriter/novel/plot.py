from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")  # additionalProperties: false に相当
    name: str = Field(description="人物の名前を入れます。")
    persona: str = Field(description="人物の性格や価値観を簡潔に書きます。")
    speech_examples: list[str] = Field(min_length=1, description="その人物の口調や話し方の例を入れます。")
    notes: str = Field(description="人物に関する補足情報や背景を入れます。")

class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="場所や舞台の名前を入れます。")
    kind: Literal["place", "worldrule", "item"] = Field(description="場所の種類やカテゴリを入れます。")
    notes: str = Field(description="その場所の雰囲気や背景情報を入れます。")

class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="シーンの名前や見出しを入れます。")
    summary: str = Field(description="そのシーンで起きる出来事の要点を入れます。")

class Plot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Characters: list[Character] = Field(min_length=1, description="登場人物の一覧を入れる項目です。")
    Settings: list[Setting] = Field(min_length=1, description="舞台や背景設定の一覧を入れる項目です。")
    Scenes: list[Scene] = Field(min_length=1, description="物語の重要なシーン一覧を入れる項目です。")

def parse_plot(structured_data: dict) -> Plot:
    """
    Jsonからcharacters, setting, scenesを分解する
    基本的にcharacter/sceneの取り出しは明確に取れるようにする。
    settingはそれ以外のものを全て取得することにする。
    """

    characters = []
    settings = []
    scenes = []

    for key, value in structured_data.items():
        match key:
            case "Characters": characters.extend(parse_chara(value))
            case "Scenes": scenes.extend(parse_scene(value))
            case "Settings": settings.extend(parse_setting(value))
            case _: continue

    return Plot(Characters=characters, Settings=settings, Scenes=scenes)

def parse_chara(charas):
    return []

def parse_scene(scenes):
    return []

def parse_setting(setting):
    return []

def _test():
    import json
    schema = Plot.model_json_schema()
    print(json.dumps(schema, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _test()