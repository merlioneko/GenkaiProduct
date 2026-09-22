"""Structure フェーズ。LLM はスタブに差し替えるので API 不要。"""

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from novel import run
from novel.phases import structure as phase
from novel.phases.concept import render_concept
from novel.schema import Concept, Plot
from util.config import PROJECT_ROOT, load_backend

CONCEPT = Concept(
    constraints=["ジャンル: ドタバタラブコメ", "魔人は「最悪の魔人」である"],
    events=["魔人がギャルの家に住み着く", "ギャルがカチコミに行く", "魔人が助けに来る"],
    body="## 世界設定\n現代日本。",
)


def plot_data():
    return {
        "meta": {"genre": "ドタバタラブコメ", "tone": "軽快", "style": "三人称", "pov": "ギャル"},
        "constraints": ["LLM が勝手に書き直した制約"],
        "events": ["LLM が勝手に並べ替えた出来事"],
        "characters": [{"name": "ギャル", "persona": "強気", "appearance": "金髪",
                        "speech_examples": ["行くよ"], "notes": ""}],
        "settings": [{"name": "ギャルの家", "kind": "place", "notes": "散らかっている"}],
        "scenes": [{"name": "同居", "opening": {"place": "ギャルの家", "time_of_day": "朝", "weather": "晴れ"},
                    "beats": ["魔人がギャルの家に居座る"], "covers": [1], "target_chars": 1000}],
    }


class FakeGateway:
    """parse を呼ばれた回数だけ results から順に返す。例外なら送出する。"""
    calls = []

    def __init__(self, results, **kwargs):
        self.results = list(results)
        self.kwargs = kwargs
        self.last_response = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def parse(self, messages, model_cls):
        FakeGateway.calls.append({"messages": messages, "kwargs": self.kwargs, "model_cls": model_cls})
        result = self.results.pop(0) if self.results else self.results
        if isinstance(result, BaseException):
            self.last_response = _response_with("スキーマに合わない生の出力")
            raise result
        return result


def _response_with(content):
    message = type("Message", (), {"content": content})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


def schema_violation():
    try:
        Plot.model_validate({})
    except ValidationError as error:
        return error


def gateway_returning(*results):
    def factory(**kwargs):
        return FakeGateway(results, **kwargs)
    return factory


class StructureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        idea = self.root / "idea.txt"
        idea.write_text("最悪の魔人と不良ギャルの話", encoding="utf-8")
        self.directory = run.create_run(idea, output_root=self.root / "creations")
        (self.directory / run.CONCEPT).write_text(render_concept(CONCEPT), encoding="utf-8")
        config_path = self.root / "backends.json"
        config_path.write_text((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"),
                               encoding="utf-8")
        self.config = load_backend(config_path)
        FakeGateway.calls = []

    def test_designated_elements_are_copied_from_the_concept_not_the_model(self):
        plot = phase.run_structure(self.directory, self.config,
                                   gateway_factory=gateway_returning(Plot(**plot_data())))
        self.assertEqual(plot.constraints, CONCEPT.constraints)
        self.assertEqual(plot.events, CONCEPT.events)
        saved = json.loads((self.directory / run.PLOT).read_text(encoding="utf-8"))
        self.assertEqual(saved["events"], CONCEPT.events)
        # 上書きされるのは指定要素だけで、生成された中身はそのまま残る。
        self.assertEqual(saved["meta"]["genre"], "ドタバタラブコメ")
        self.assertEqual(saved["scenes"][0]["covers"], [1])

    def test_the_concept_file_is_what_gets_sent(self):
        phase.run_structure(self.directory, self.config,
                            gateway_factory=gateway_returning(Plot(**plot_data())))
        call = FakeGateway.calls[0]
        self.assertEqual(call["messages"][0]["content"], phase.SYSTEM_PROMPT.read_text(encoding="utf-8"))
        self.assertIn("3. 魔人が助けに来る", call["messages"][1]["content"])
        self.assertIs(call["model_cls"], Plot)
        self.assertEqual(call["kwargs"]["phase"], "structure")

    def test_hand_edited_concept_reaches_the_plot(self):
        path = self.directory / run.CONCEPT
        path.write_text(path.read_text(encoding="utf-8").replace("ドタバタラブコメ", "シリアス"),
                        encoding="utf-8")
        plot = phase.run_structure(self.directory, self.config,
                                   gateway_factory=gateway_returning(Plot(**plot_data())))
        self.assertIn("ジャンル: シリアス", plot.constraints)

    def test_a_schema_violation_is_retried_twice(self):
        plot = phase.run_structure(
            self.directory, self.config,
            gateway_factory=gateway_returning(schema_violation(), schema_violation(), Plot(**plot_data())))
        self.assertEqual(len(FakeGateway.calls), 3)
        self.assertEqual(plot.events, CONCEPT.events)
        self.assertFalse((self.directory / run.PLOT_RAW).exists())

    def test_three_failures_save_the_raw_output_and_stop(self):
        with self.assertRaises(phase.StructureError):
            phase.run_structure(self.directory, self.config, gateway_factory=gateway_returning(
                schema_violation(), schema_violation(), schema_violation()))
        self.assertEqual(len(FakeGateway.calls), 3)
        self.assertFalse((self.directory / run.PLOT).exists())
        self.assertEqual((self.directory / run.PLOT_RAW).read_text(encoding="utf-8"),
                         "スキーマに合わない生の出力")

    def test_a_broken_plot_file_stops_the_next_stage(self):
        phase.run_structure(self.directory, self.config,
                            gateway_factory=gateway_returning(Plot(**plot_data())))
        path = self.directory / run.PLOT
        self.assertEqual(phase.load_plot(self.directory).events, CONCEPT.events)
        path.write_text(path.read_text(encoding="utf-8").replace('"scenes"', '"場面"'), encoding="utf-8")
        with self.assertRaises(phase.PlotFormatError):
            phase.load_plot(self.directory)
        path.write_text("{ 壊れた JSON", encoding="utf-8")
        with self.assertRaises(phase.PlotFormatError):
            phase.load_plot(self.directory)

    def test_missing_plot_file_is_an_error(self):
        with self.assertRaises(phase.PlotFormatError):
            phase.load_plot(self.directory)

    def test_stale_raw_output_is_archived_by_the_next_structure_run(self):
        (self.directory / run.PLOT_RAW).write_text("前回の失敗", encoding="utf-8")
        destination = run.archive_downstream(self.directory, "structure")
        self.assertFalse((self.directory / run.PLOT_RAW).exists())
        self.assertEqual((destination / run.PLOT_RAW).read_text(encoding="utf-8"), "前回の失敗")


if __name__ == "__main__":
    unittest.main()
