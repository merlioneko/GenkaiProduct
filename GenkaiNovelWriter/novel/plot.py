from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
import textwrap

class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")  # additionalProperties: false に相当
    name: str = Field(description="人物の名前を入れます。")
    persona: str = Field(description="人物の性格や価値観を簡潔に書きます。")
    speech_examples: list[str] = Field(min_length=1, description="その人物の口調や話し方の例を入れます。")
    notes: str = Field(description="人物に関する補足情報や背景を入れます。")

    def __str__(self):
        speech_examples = "\n".join(f"  - {example}" for example in self.speech_examples)
        return (
            f"### {self.name}\n"
            f"- Persona: {self.persona}\n"
            f"- Speech Examples:\n{speech_examples}\n"
            f"- Notes: {self.notes}"
        )

class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="場所や舞台の名前を入れます。")
    kind: Literal["place", "worldrule", "item"] = Field(description="場所の種類やカテゴリを入れます。")
    notes: str = Field(description="その場所の雰囲気や背景情報を入れます。")

    def __str__(self):
        return f"### {self.name}\n- Kind: {self.kind}\n- Notes: {self.notes}"

class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="シーンの名前や見出しを入れます。")
    summary: str = Field(description="そのシーンで起きる出来事の要点を入れます。")

    def __str__(self):
        return f"### {self.name}\n- Summary: {self.summary}"

class Plot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Characters: list[Character] = Field(min_length=1, description="登場人物の一覧を入れる項目です。")
    Settings: list[Setting] = Field(min_length=1, description="舞台や背景設定の一覧を入れる項目です。")
    Scenes: list[Scene] = Field(min_length=1, description="物語の重要なシーン一覧を入れる項目です。")

    def __str__(self):
        characters = "\n\n".join(str(character) for character in self.Characters)
        settings = "\n\n".join(str(setting) for setting in self.Settings)
        scenes = "\n\n".join(str(scene) for scene in self.Scenes)
        return f"# Plot\n\n## Characters\n\n{characters}\n\n## Settings\n\n{settings}\n\n## Scenes\n\n{scenes}"

def _test():
    import json
    schema = Plot.model_json_schema()
    print(json.dumps(schema, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _test()