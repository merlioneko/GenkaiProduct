from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NovelScene(DataModel):
    """
    plot.Sceneを実行した後、小説の形になったシーンのクラス
    """
    title: str
    content: str = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def nonblank_content(self):
        if not self.content.strip():
            raise ValueError("Scene content must not be blank")
        return self

    def __str__(self):
        return f"Scene Title: {self.title}\nContent: {self.content}\nNotes: {self.notes}"


class GenerationError(DataModel):
    type: str
    message: str


class SceneWritingResult(DataModel):
    scene_index: int = Field(ge=0)
    title: str
    status: Literal["success", "failed"]
    scene: NovelScene | None = None
    error: GenerationError | None = None

    @model_validator(mode="after")
    def valid_outcome(self):
        if self.status == "success":
            if self.scene is None or self.error is not None:
                raise ValueError("Success requires a scene and no error")
        elif self.scene is not None or self.error is None:
            raise ValueError("Failure requires an error and no scene")
        return self


class WritingResult(DataModel):
    schema_version: Literal[1] = 1
    results: list[SceneWritingResult] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_scenes(self):
        if [item.scene_index for item in self.results] != list(range(len(self.results))):
            raise ValueError("Results must retain every scene in original order")
        return self

    @property
    def complete(self) -> bool:
        return all(item.status == "success" for item in self.results)


class BorderCheckInput(DataModel):
    before_index: int = Field(ge=0)
    after_index: int = Field(ge=0)
    tail: str
    head: str
    budget: int = Field(gt=0)
    window: float = Field(ge=1)


class BorderCheckResult(DataModel):
    input: BorderCheckInput
    status: Literal["passed", "failed", "not_checked"]
    reasons: list[str]
    method: Literal["punctuation_v1"] = "punctuation_v1"


class BorderCheckReport(DataModel):
    schema_version: Literal[1] = 1
    checks: list[BorderCheckResult] = Field(default_factory=list)
