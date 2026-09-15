from pydantic import BaseModel, ConfigDict, Field

class NovelScene:
    """
    plot.Sceneを実行した後、小説の形になったシーンのクラス
    """
    def __init__(self, title: str, content: str, notes: str = ""):
        self.title = title
        self.content = content
        self.notes = notes

    def __str__(self):
        return f"Scene Title: {self.title}\nContent: {self.content}\nNotes: {self.notes}"

class Novel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(description="小説のタイトルを入れる。")
    scenes: list[NovelScene] = Field(description="小説のシーンを入れる。")