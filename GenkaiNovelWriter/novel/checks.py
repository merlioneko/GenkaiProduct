"""LLMを使わない機械検査(D20)。M2 では Plot の検査(SPEC.md「Plot機械検査」)。

報告のみで、パイプラインは止めない。検査は5種類とも SPEC の表に対応する。
"""

import json
from pathlib import Path

from novel import run
from novel.schema import Plot, PlotFinding, PlotReport

# 未決定表現(D13)。SPEC の「または」「(例)」「例:」に、全角の書き方を足したもの。
UNDECIDED_MARKERS = ("または", "もしくは", "(例", "（例", "例:", "例：")


def check_plot(plot: Plot) -> PlotReport:
    return PlotReport(findings=_undecided(plot) + _unused(plot) + _places(plot) + _covers(plot))


def save_plot_report(directory: Path | str, report: PlotReport) -> Path:
    path = Path(directory) / run.PLOT_REPORT
    path.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _undecided(plot: Plot) -> list[PlotFinding]:
    """未決定表現。Plot 確定時点で選択肢を残さない(D13)。"""
    findings = []
    for location, text in _texts(plot):
        for marker in UNDECIDED_MARKERS:
            if marker in text:
                findings.append(PlotFinding(
                    check="undecided", location=location,
                    detail=f"未決定の表現「{marker}」が残っている: {text[:40]}"))
                break
    return findings


def _unused(plot: Plot) -> list[PlotFinding]:
    """どのシーンの beats にも名前が現れない登場人物・設定(D14)。"""
    beats = "\n".join(beat for scene in plot.scenes for beat in scene.beats)
    findings = []
    for index, character in enumerate(plot.characters):
        if character.name not in beats:
            findings.append(PlotFinding(
                check="unused", location=f"characters[{index}].name",
                detail=f"「{character.name}」がどのシーンの beats にも現れない"))
    for index, setting in enumerate(plot.settings):
        if setting.name not in beats:
            findings.append(PlotFinding(
                check="unused", location=f"settings[{index}].name",
                detail=f"「{setting.name}」がどのシーンの beats にも現れない"))
    return findings


def _places(plot: Plot) -> list[PlotFinding]:
    """opening.place が settings の kind=place に無い(旧実装の「自宅が未定義」問題)。"""
    places = {setting.name for setting in plot.settings if setting.kind == "place"}
    return [PlotFinding(check="place", location=f"scenes[{index}].opening.place",
                        detail=f"「{scene.opening.place}」が settings の kind=place に無い")
            for index, scene in enumerate(plot.scenes)
            if scene.opening.place not in places]


def _covers(plot: Plot) -> list[PlotFinding]:
    """指定要素の未割当と、出来事の順序違反(D34)。"""
    findings = []
    total = len(plot.events)
    sequence = [(index, number) for index, scene in enumerate(plot.scenes) for number in scene.covers]

    covered = {number for _, number in sequence}
    for number in range(1, total + 1):
        if number not in covered:
            findings.append(PlotFinding(
                check="uncovered", location=f"events[{number - 1}]",
                detail=f"出来事 {number}「{plot.events[number - 1]}」がどのシーンの covers にも無い"))
    for index, number in sequence:
        if not 1 <= number <= total:
            findings.append(PlotFinding(
                check="covers", location=f"scenes[{index}].covers",
                detail=f"出来事 {number} は存在しない(出来事は {total} 件)"))

    previous_index, previous = None, None
    for index, number in sequence:
        if previous is not None and number < previous:
            findings.append(PlotFinding(
                check="order", location=f"scenes[{index}].covers",
                detail=f"出来事 {number} が、前のシーン({previous_index + 1}番目)の {previous} より後ろに来ている"))
        previous_index, previous = index, number
    return findings


def _texts(plot: Plot):
    """検査対象の文字列を (位置, 文字列) で返す。位置は 03_plot.json のキーで書く。"""
    yield "meta.genre", plot.meta.genre
    yield "meta.tone", plot.meta.tone
    yield "meta.style", plot.meta.style
    yield "meta.pov", plot.meta.pov
    for index, item in enumerate(plot.constraints):
        yield f"constraints[{index}]", item
    for index, item in enumerate(plot.events):
        yield f"events[{index}]", item
    for index, character in enumerate(plot.characters):
        base = f"characters[{index}]"
        yield f"{base}.name", character.name
        yield f"{base}.persona", character.persona
        yield f"{base}.appearance", character.appearance
        for position, line in enumerate(character.speech_examples):
            yield f"{base}.speech_examples[{position}]", line
        yield f"{base}.notes", character.notes
    for index, setting in enumerate(plot.settings):
        base = f"settings[{index}]"
        yield f"{base}.name", setting.name
        yield f"{base}.notes", setting.notes
    for index, scene in enumerate(plot.scenes):
        base = f"scenes[{index}]"
        yield f"{base}.name", scene.name
        yield f"{base}.opening.place", scene.opening.place
        yield f"{base}.opening.time_of_day", scene.opening.time_of_day
        yield f"{base}.opening.weather", scene.opening.weather
        for position, beat in enumerate(scene.beats):
            yield f"{base}.beats[{position}]", beat
