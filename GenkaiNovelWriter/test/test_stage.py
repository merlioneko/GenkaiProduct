"""stage concept / stage structure。LLM はスタブに差し替えるので API 不要。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from main import main, stage
from novel import run
from novel.schema import ConceptReport, Plot
from util.config import PROJECT_ROOT

CONCEPT_MARKDOWN = """# 制約
- ジャンル: ドタバタラブコメ

# 出来事
1. 魔人が住み着く
2. ギャルがカチコミに行く

# 構想
## 世界設定
現代日本。
"""


def plot_data():
    return {
        "meta": {"genre": "ドタバタラブコメ", "tone": "軽快", "style": "三人称", "pov": "ギャル"},
        "constraints": ["置き換えられる"],
        "events": ["置き換えられる"],
        "characters": [{"name": "ギャル", "persona": "強気", "appearance": "金髪",
                        "speech_examples": ["行くよ"], "notes": ""}],
        "settings": [{"name": "ギャルの家", "kind": "place", "notes": ""}],
        "scenes": [{"name": "同居", "opening": {"place": "ギャルの家", "time_of_day": "朝", "weather": "晴れ"},
                    "beats": ["魔人がギャルの家に居座る"], "covers": [1], "target_chars": 1000},
                   {"name": "出発", "opening": {"place": "ギャルの家", "time_of_day": "昼", "weather": "晴れ"},
                    "beats": ["ギャルがギャルの家を出てカチコミに行く"], "covers": [2], "target_chars": 1000}],
    }


class FakeGateway:
    """concept は text、concept_verify と structure は parse を呼ぶ。"""

    def __init__(self, **kwargs):
        self.phase = kwargs["phase"]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, messages):
        return CONCEPT_MARKDOWN

    def parse(self, messages, model_cls):
        if model_cls is ConceptReport:
            return ConceptReport(findings=[])
        return Plot(**plot_data())


class StageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.idea = self.root / "idea.txt"
        self.idea.write_text("最悪の魔人と不良ギャルの話", encoding="utf-8")
        self.config_path = self.root / "backends.json"
        self.config_path.write_text(
            (PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.creations = self.root / "creations"

    def stage(self, name, **kwargs):
        return stage(name, config_path=self.config_path, output_root=self.creations,
                     gateway_factory=FakeGateway, **kwargs)

    def test_concept_creates_a_run_directory_with_its_artifacts(self):
        directory = self.stage("concept", input_path=self.idea)
        self.assertEqual(directory.parent, self.creations)
        for name in (run.INPUT, run.CONFIG_SNAPSHOT, run.CONCEPT, run.CONCEPT_REPORT):
            self.assertTrue((directory / name).is_file(), name)
        snapshot = json.loads((directory / run.CONFIG_SNAPSHOT).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["backend"], "local")
        self.assertNotIn("api_key", snapshot)

    def test_structure_follows_concept_in_the_same_directory(self):
        directory = self.stage("concept", input_path=self.idea)
        self.assertEqual(self.stage("structure", run_dir=directory), directory)
        plot = json.loads((directory / run.PLOT).read_text(encoding="utf-8"))
        # 指定要素は 02_concept.md から転記される。
        self.assertEqual(plot["events"], ["魔人が住み着く", "ギャルがカチコミに行く"])
        report = json.loads((directory / run.PLOT_REPORT).read_text(encoding="utf-8"))
        self.assertEqual(report["findings"], [])

    def test_rerunning_structure_archives_the_previous_plot(self):
        directory = self.stage("concept", input_path=self.idea)
        self.stage("structure", run_dir=directory)
        (directory / run.PLOT).write_text('{"手で壊した": true}', encoding="utf-8")
        self.stage("structure", run_dir=directory)
        archives = list((directory / run.ARCHIVE).iterdir())
        self.assertEqual(len(archives), 1)
        self.assertIn("手で壊した", (archives[0] / run.PLOT).read_text(encoding="utf-8"))
        self.assertNotIn("手で壊した", (directory / run.PLOT).read_text(encoding="utf-8"))

    def test_rerunning_concept_archives_the_plot_too(self):
        directory = self.stage("concept", input_path=self.idea)
        self.stage("structure", run_dir=directory)
        self.stage("concept", run_dir=directory)
        self.assertFalse((directory / run.PLOT).exists())
        self.assertTrue((directory / run.CONCEPT).exists())

    def test_hand_edited_concept_reaches_the_plot(self):
        directory = self.stage("concept", input_path=self.idea)
        path = directory / run.CONCEPT
        path.write_text(path.read_text(encoding="utf-8").replace("魔人が住み着く", "魔人が現れる"),
                        encoding="utf-8")
        self.stage("structure", run_dir=directory)
        plot = json.loads((directory / run.PLOT).read_text(encoding="utf-8"))
        self.assertEqual(plot["events"][0], "魔人が現れる")

    def test_structure_on_a_directory_without_a_concept_stops(self):
        directory = run.create_run(self.idea, output_root=self.creations)
        with self.assertRaises(Exception) as caught:
            self.stage("structure", run_dir=directory)
        self.assertIn(run.CONCEPT, str(caught.exception))


class StageArgumentTest(unittest.TestCase):
    def run_cli(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(argv)
        return caught.exception.code, stderr.getvalue()

    def test_concept_needs_exactly_one_of_run_or_input(self):
        code, message = self.run_cli(["stage", "concept"])
        self.assertEqual(code, 2)
        self.assertIn("exactly one", message)
        code, message = self.run_cli(["stage", "concept", "--run", "a", "--input", "b"])
        self.assertIn("exactly one", message)

    def test_structure_needs_a_run_directory(self):
        code, message = self.run_cli(["stage", "structure", "--input", "a"])
        self.assertEqual(code, 2)
        self.assertIn("--run", message)

    def test_unimplemented_stages_are_rejected(self):
        code, message = self.run_cli(["stage", "check", "--run", "a"])
        self.assertEqual(code, 2)
        self.assertIn("check", message)

    def test_a_missing_run_directory_is_reported_without_a_traceback(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["stage", "structure", "--run", "does-not-exist"])
        self.assertEqual(code, 1)
        self.assertIn("does-not-exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
