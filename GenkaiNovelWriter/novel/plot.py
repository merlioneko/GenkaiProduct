from dataclasses import dataclass

"""
構造化されたアイデアのデータクラス
TODO: pydanticに置き換える
"""

@dataclass
class Plot:
    """
    構造化されたアイデア…もといプロット。
    Attributes:
        characters(list):Characterのリスト
        settings(list): Settingのリスト
        scenes(list): Scenesのリスト
    """
    characters: list
    settings: list
    scenes: list

@dataclass
class Character:
    name: str
    persona: str
    speech_examples: list[str]
    notes: str

@dataclass
class Setting:
    name: str
    kind: str
    notes: str

@dataclass
class Scene:
    name: str
    summary: str
    detail: str

    def is_written(self) -> bool:
        return self.detail != ""

def parse_plot(structured_data: dict) -> Plot:
    """
    Jsonからcharacters, setting, scenesを分解する
    基本的にcharacter/sceneの取り出しは明確に取れるようにする。
    settingはそれ以外のものを全て取得することにする。
    """

    characters = []
    settings = []
    scenes = []

    for key, value in structured_data:
        match key:
            case "Character": characters.extend(parse_chara(value))
            case "Scenes": scenes.extend(parse_scene(value))
            case "Settings": settings.extend(parse_setting(value))
            case _: continue

    return Plot(characters, settings, scenes)

def parse_chara(charas):
    return []

def parse_scene(scenes):
    return []

def parse_setting(setting):
    return []