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