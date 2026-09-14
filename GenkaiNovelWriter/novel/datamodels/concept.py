from pydantic import BaseModel, ConfigDict, Field


class Concept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specifies: list[str] = Field(description="必須事項を入れます。")
    body: str = Field(description="構想案を入れます。")

