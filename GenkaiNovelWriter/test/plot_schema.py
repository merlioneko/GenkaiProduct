"""SPEC Plot schema for the M1 U3 probe only; the M2 pipeline is not implemented."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Meta(StrictModel):
    genre: str
    tone: str
    style: str
    pov: str


class SpecifiedElement(StrictModel):
    id: str = Field(pattern=r"^S[1-9][0-9]*$")
    text: str


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
    covers: list[str]
    target_chars: int = 1000


class Plot(StrictModel):
    meta: Meta
    specified_elements: list[SpecifiedElement]
    characters: list[Character] = Field(min_length=1)
    settings: list[Setting] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
