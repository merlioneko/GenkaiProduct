"""パイプラインを流れるデータの pydantic モデル(SPEC.md D30〜D36)。

UserIdea(str) → Concept → Plot → Novel → Check の各段のデータだけを定義する。
gateway・prompts・ファイル入出力は import しない。変換はフェーズ関数(novel/phases/)が担う。
strict=True にして、型の暗黙変換("1000" → 1000 など)をしない。手で編集した成果物の誤りを黙って直さないため(D24)。
Field の description は JSON Schema 経由で LLM に渡るので、生成時の指示として書く。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- Concept(02_concept.md) ----

class Concept(BaseModel):
    """構想。指定要素(ユーザ入力由来・変更不可)と補完本文を分けて持つ(D9, D33)。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    constraints: list[str] = Field(description="順序なしの指定要素。ジャンル・トーン・登場人物の属性・世界設定。")
    events: list[str] = Field(description="順序ありの指定要素。ユーザ入力に出てきた順の出来事。")
    body: str = Field(description="構想本文(Markdown)。制約・出来事と矛盾しない範囲で空白を埋めた補完要素。")


# ---- Plot(03_plot.json) ----

class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    genre: str = Field(description="ジャンル。例: ドタバタラブコメ")
    tone: str = Field(description="トーン。例: 軽快、ツッコミ多め、終盤のみ熱い")
    style: str = Field(description="文体の指定。例: 地の文は三人称、会話多め")
    pov: str = Field(description="視点人物")


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(description="名前")
    persona: str = Field(description="性格・価値観")
    appearance: str = Field(description="外見")
    speech_examples: list[str] = Field(min_length=1, description="口調の例。1件以上")
    notes: str = Field(description="補足")


class Setting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(description="名前")
    kind: Literal["place", "worldrule", "item"] = Field(description="種別。place=場所, worldrule=世界の法則, item=物品")
    notes: str = Field(description="補足")


class SceneState(BaseModel):
    """シーン開始時点の状態(D16)。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    place: str = Field(description="場所。settings のうち kind=place の name と一致させる")
    time_of_day: str = Field(description="時間帯")
    weather: str = Field(description="天候")


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(description="シーン名")
    opening: SceneState = Field(description="開始時点の状態")
    beats: list[str] = Field(min_length=1, description="順序どおりに起こす出来事。本文ではなく指示。1件以上")
    covers: list[int] = Field(description="このシーンで満たす出来事(events)の番号。1始まり")
    target_chars: int = Field(default=1000, description="目安字数")


class Plot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    meta: Meta
    constraints: list[str] = Field(description="Concept.constraints をそのまま転記")
    events: list[str] = Field(description="Concept.events をそのまま転記")
    characters: list[Character] = Field(min_length=1, description="登場人物(作品レベル)。この話で使うものだけ")
    settings: list[Setting] = Field(min_length=1, description="設定(作品レベル)。この話で使うものだけ")
    scenes: list[Scene] = Field(min_length=1, description="シーン(話レベル)。時系列順")


# ---- Novel(04_scenes/scene_NN.md) ----

class NovelScene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=1, description="1始まり")
    title: str = Field(description="Plot.scenes[index-1].name")
    content: str = Field(description="scene_NN.md の内容(本文のみ)")


class Novel(BaseModel):
    """執筆済みシーンの列。ファイル(04_scenes/)が正で、実行時に Plot と各ファイルから組み立てる(D35)。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    scenes: list[NovelScene] = Field(default_factory=list)

    def context_until(self, k: int) -> str:
        """シーン 1〜k-1 の本文を空行区切りで結合して返す(B'方式の執筆文脈, D10)。"""
        return "\n\n".join(scene.content for scene in self.scenes if scene.index < k)

    def invalidate_from(self, k: int) -> None:
        """シーン k 以降を除去する。シーン k を書き直すと k+1 以降も無効になるため。ファイル側は退避(D23)で対応する。"""
        self.scenes = [scene for scene in self.scenes if scene.index < k]


# ---- Check(06_check/<項目>.json) ----

class CheckIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scene: int = Field(ge=1, description="問題のあるシーン番号")
    quote: str = Field(description="問題箇所の抜粋(30字以内)")
    reason: str = Field(description="問題の説明")


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item: str = Field(description="検査項目名。contamination / length / elements / consistency / physical")
    issues: list[CheckIssue] = Field(default_factory=list)


# ---- 照合・機械検査のレポート ----
# SPEC は 02_concept_report.json の内容を「欠落・順序変更・意味の弱化」としか定めていない。
# フィールドはここで決める。どちらのレポートも報告のみで、パイプラインは止めない(D18 と同じ扱い)。

class ConceptFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["missing", "reordered", "weakened"] = Field(
        description="missing=指定要素が構想に無い, reordered=出来事の順序が入力と違う, weakened=指定語の意味が弱められている")
    element: str = Field(description="対象の指定要素。ユーザ入力での表現をそのまま引く")
    detail: str = Field(description="何がどう違うかの説明。構想側の該当箇所を引用する")


class ConceptReport(BaseModel):
    """00_input.txt と 02_concept.md の照合結果(02_concept_report.json)。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    findings: list[ConceptFinding] = Field(description="問題が無ければ空リスト")


class PlotFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    check: Literal["undecided", "unused", "place", "uncovered", "covers", "order"] = Field(
        description="SPEC.md「Plot機械検査」の検査名。covers は存在しない出来事番号を指した場合")
    location: str = Field(description="03_plot.json 内の位置。例: scenes[2].beats[0]")
    detail: str = Field(description="何が見つかったかの説明")


class PlotReport(BaseModel):
    """Plot の機械検査の結果(03_plot_report.json)。LLM は使わない(D20)。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    findings: list[PlotFinding] = Field(description="問題が無ければ空リスト")
