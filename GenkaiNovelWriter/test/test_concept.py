"""Concept フェーズと 02_concept.md のパーサ。LLM はスタブに差し替えるので API 不要。"""

import json
import tempfile
import unittest
from pathlib import Path

from novel import run
from novel.phases import concept as phase
from novel.schema import Concept, ConceptFinding, ConceptReport
from util.config import PROJECT_ROOT, load_backend

SAMPLE = """# 制約
- ジャンル: ドタバタラブコメ
- 魔人は「最悪の魔人」である

# 出来事
1. 魔人がギャルの家に住み着いている
2. ギャルがカチコミに行く

# 構想
## 世界設定
現代日本。魔人の存在は公にはなっていない。
## 登場人物
## 展開
"""


class FakeGateway:
    """gateway_factory の差し替え。渡された messages を記録する。"""
    calls = []

    def __init__(self, text="", **kwargs):
        self.text_to_return = text
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, messages):
        FakeGateway.calls.append({"messages": messages, "kwargs": self.kwargs})
        return self.text_to_return

    def parse(self, messages, model_cls):
        FakeGateway.calls.append({"messages": messages, "kwargs": self.kwargs, "model_cls": model_cls})
        return self.parsed


def gateway_returning(text="", parsed=None):
    def factory(**kwargs):
        gateway = FakeGateway(text, **kwargs)
        gateway.parsed = parsed
        return gateway
    return factory


class ConceptFormatTest(unittest.TestCase):
    def test_parses_the_fixed_headings(self):
        result = phase.parse_concept(SAMPLE)
        self.assertEqual(result.constraints, ["ジャンル: ドタバタラブコメ", "魔人は「最悪の魔人」である"])
        self.assertEqual(result.events, ["魔人がギャルの家に住み着いている", "ギャルがカチコミに行く"])
        self.assertIn("現代日本", result.body)
        self.assertIn("## 展開", result.body)

    def test_render_and_parse_round_trip(self):
        original = Concept(constraints=["ジャンル: ラブコメ"], events=["出会う", "別れる"],
                           body="## 世界設定\n現代。")
        self.assertEqual(phase.parse_concept(phase.render_concept(original)), original)

    def test_missing_or_reordered_headings_are_rejected(self):
        for text in ("# 制約\n- a\n\n# 構想\n本文\n",
                     "# 出来事\n1. a\n\n# 制約\n- a\n\n# 構想\n本文\n",
                     SAMPLE.replace("# 制約", "# 制約事項")):
            with self.assertRaises(phase.ConceptFormatError):
                phase.parse_concept(text)

    def test_preamble_before_the_first_heading_is_rejected(self):
        with self.assertRaises(phase.ConceptFormatError):
            phase.parse_concept("承知しました。以下が構想です。\n\n" + SAMPLE)

    def test_event_numbers_must_start_at_one_without_gaps(self):
        with self.assertRaises(phase.ConceptFormatError):
            phase.parse_concept(SAMPLE.replace("2. ギャル", "3. ギャル"))
        with self.assertRaises(phase.ConceptFormatError):
            phase.parse_concept(SAMPLE.replace("1. 魔人", "- 魔人"))

    def test_empty_sections_are_rejected(self):
        with self.assertRaises(phase.ConceptFormatError):
            phase.parse_concept("# 制約\n\n# 出来事\n1. a\n\n# 構想\n本文\n")
        with self.assertRaises(phase.ConceptFormatError):
            phase.parse_concept("# 制約\n- a\n\n# 出来事\n1. a\n\n# 構想\n\n")


class PhaseFixture(unittest.TestCase):
    """実行ディレクトリと設定を用意するだけの土台。テストは持たない。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        idea = self.root / "idea.txt"
        idea.write_text("不良少女と魔人が報復をする話", encoding="utf-8")
        self.directory = run.create_run(idea, output_root=self.root / "creations")
        config_path = self.root / "backends.json"
        config_path.write_text((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"),
                               encoding="utf-8")
        self.config = load_backend(config_path)
        FakeGateway.calls = []


class ConceptPhaseTest(PhaseFixture):
    def test_writes_the_concept_file_and_returns_the_parsed_model(self):
        result = phase.run_concept(self.directory, self.config,
                                   gateway_factory=gateway_returning(SAMPLE))
        self.assertEqual(result.events, ["魔人がギャルの家に住み着いている", "ギャルがカチコミに行く"])
        written = (self.directory / run.CONCEPT).read_text(encoding="utf-8")
        self.assertEqual(phase.parse_concept(written), result)

    def test_sends_the_system_prompt_and_the_run_input(self):
        phase.run_concept(self.directory, self.config, gateway_factory=gateway_returning(SAMPLE))
        messages = FakeGateway.calls[0]["messages"]
        self.assertEqual(messages[0]["content"],
                         phase.SYSTEM_PROMPT.read_text(encoding="utf-8"))
        self.assertEqual(messages[1]["content"], "不良少女と魔人が報復をする話")
        self.assertEqual(FakeGateway.calls[0]["kwargs"]["phase"], "concept")
        self.assertEqual(FakeGateway.calls[0]["kwargs"]["model"], "qwen3.6-35b-a3b")
        self.assertEqual(FakeGateway.calls[0]["kwargs"]["log_path"], self.directory / run.CALLS)

    def test_broken_output_stops_but_leaves_the_file_for_hand_editing(self):
        with self.assertRaises(phase.ConceptFormatError):
            phase.run_concept(self.directory, self.config,
                              gateway_factory=gateway_returning("承知しました。\n# 制約\n- a\n"))
        self.assertIn("承知しました", (self.directory / run.CONCEPT).read_text(encoding="utf-8"))

    def test_load_concept_reads_hand_edits(self):
        phase.run_concept(self.directory, self.config, gateway_factory=gateway_returning(SAMPLE))
        path = self.directory / run.CONCEPT
        path.write_text(path.read_text(encoding="utf-8").replace("ドタバタラブコメ", "シリアス"),
                        encoding="utf-8")
        self.assertIn("ジャンル: シリアス", phase.load_concept(self.directory).constraints)

    def test_missing_concept_file_is_an_error(self):
        with self.assertRaises(phase.ConceptFormatError):
            phase.load_concept(self.directory)


if __name__ == "__main__":
    unittest.main()


class ConceptVerifyTest(PhaseFixture):
    def setUp(self):
        super().setUp()
        phase.run_concept(self.directory, self.config, gateway_factory=gateway_returning(SAMPLE))
        FakeGateway.calls = []

    def test_writes_the_report_and_does_not_stop_on_findings(self):
        finding = {"kind": "weakened", "element": "最悪の魔人",
                   "detail": "構想では「気のいい同居人」になっている"}
        report = ConceptReport(findings=[ConceptFinding(**finding)])
        result = phase.verify_concept(self.directory, self.config,
                                      gateway_factory=gateway_returning(parsed=report))
        self.assertEqual(result, report)
        saved = json.loads((self.directory / run.CONCEPT_REPORT).read_text(encoding="utf-8"))
        self.assertEqual(saved, {"findings": [finding]})

    def test_compares_the_input_against_the_concept_file(self):
        phase.verify_concept(self.directory, self.config,
                             gateway_factory=gateway_returning(parsed=ConceptReport(findings=[])))
        call = FakeGateway.calls[0]
        self.assertEqual(call["messages"][0]["content"], phase.VERIFY_PROMPT.read_text(encoding="utf-8"))
        self.assertIn("不良少女と魔人が報復をする話", call["messages"][1]["content"])
        self.assertIn("魔人は「最悪の魔人」である", call["messages"][1]["content"])
        self.assertIs(call["model_cls"], ConceptReport)
        # 照合は Concept と同じモデルだが、ログ上は別フェーズとして数える。
        self.assertEqual(call["kwargs"]["phase"], "concept_verify")
        self.assertEqual(call["kwargs"]["model"], self.config.phase("concept").model)

    def test_an_empty_report_is_still_written(self):
        phase.verify_concept(self.directory, self.config,
                             gateway_factory=gateway_returning(parsed=ConceptReport(findings=[])))
        saved = json.loads((self.directory / run.CONCEPT_REPORT).read_text(encoding="utf-8"))
        self.assertEqual(saved["findings"], [])
