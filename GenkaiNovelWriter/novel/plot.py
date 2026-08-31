from dataclasses import dataclass

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
    notes: str

@dataclass
class Scene:
    name: str
    summary: str
    detail: str

    def is_written(self) -> bool:
        return self.detail != ""