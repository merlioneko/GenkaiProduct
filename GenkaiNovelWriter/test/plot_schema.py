"""M1 の U3 検証だけで使う Plot スキーマ。novel/schema.py が入ったらそちらに統一する。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Meta(StrictModel):
    genre: str
    tone: str
    style: str
    pov: str


class Character(StrictModel):
    name: str
    persona: str
    appearance: str
    speech_examples: list[str] = Field(min_length=1)
    notes: str


class Setting(StrictModel):
    name: str
    kind: Literal["place", "worldrule", "item"]
    notes: str


class SceneState(StrictModel):
    place: str
    time_of_day: str
    weather: str


class Scene(StrictModel):
    name: str
    opening: SceneState
    beats: list[str] = Field(min_length=1)
    covers: list[int]
    target_chars: int = 1000


class Plot(StrictModel):
    meta: Meta
    constraints: list[str]
    events: list[str]
    characters: list[Character] = Field(min_length=1)
    settings: list[Setting] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
