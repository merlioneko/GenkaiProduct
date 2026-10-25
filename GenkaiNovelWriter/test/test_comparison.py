"""M5の計画固定、採取、失敗保持。モデル・lms・HTTPはスタブを使う。"""

import contextlib
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from novel import run
from test import compare_generation as comparison
from test.test_m1 import completion
from test.test_stage import CONCEPT_MARKDOWN, plot_data
from util.config import PROJECT_ROOT, load_backend
from util.gateway import OpenAICompatibleGateway


class ComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        self.config_path = self.root / "config.json"
        self.config_path.write_text((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.models = []
        self.calls = []
        self.fail = False

    def state(self, config):
        return {"status": "observed", "models": list(self.models)}

    def set_model(self, model, context=16384):
        self.models = [{"key": model, "type": "llm", "quantization": {"name": "test-Q4"},
                        "loaded_instances": [{"id": model, "config": {"context_length": context}}]}]

    def command(self, args, **kwargs):
        if args[1] == "--version":
            return SimpleNamespace(stdout="test-cli-version")
        if args[1] == "unload":
            self.models = []
        elif args[1] == "load":
            self.set_model(args[2], int(args[args.index("--context-length") + 1]))

    def prepare(self):
        return comparison.prepare(self.study, self.config_path, "ユーザ", snapshot=self.state, command=self.command)

    def gateway_class(self):
        owner = self

        class Gateway(OpenAICompatibleGateway):
            def __init__(self, **kwargs):
                phase, model = kwargs["phase"], kwargs["model"]

                def handler(request):
                    owner.calls.append(phase)
                    owner.set_model(model)
                    if owner.fail:
                        return httpx.Response(400, json={"error": {"message": "private-detail"}})
                    if phase == "concept":
                        text = CONCEPT_MARKDOWN
                    elif phase == "concept_verify":
                        text = '{"findings": []}'
                    elif phase == "structure":
                        text = json.dumps(plot_data(), ensure_ascii=False)
                    else:
                        text = "本文。" * 250
                    return httpx.Response(200, json=completion(text))

                client = OpenAI(base_url="http://fake.invalid/v1", api_key="test-secret", max_retries=0,
                                http_client=httpx.Client(transport=httpx.MockTransport(handler)))
                super().__init__(**kwargs, client=client)
        return Gateway

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return comparison.execute(self.study, self.config_path, snapshot=self.state,
                                      reset=lambda c: self.models.clear(), gateway_class=self.gateway_class())

    def test_fixed_plan_produces_eight_fresh_outputs_and_preserves_human_review(self):
        self.prepare()
        plan = comparison.read(self.study / "plan.json")
        self.assertEqual(len(plan["trials"]), 8)
        self.assertEqual(len({(t["input"], t["method"], t["repeat"]) for t in plan["trials"]}), 8)
        self.assertEqual(self.models, [])
        self.assertNotIn("api_key", (self.study / "plan.json").read_text(encoding="utf-8"))
        review = self.study / "human_review.md"
        review.write_text("人手の記入済み評価", encoding="utf-8")
        result = self.execute()
        self.assertEqual([t["status"] for t in result["trials"]], ["success"] * 8)
        self.assertEqual(len(self.calls), 24)
        for trial in result["trials"]:
            directory = self.study / trial["directory"]
            self.assertTrue((directory / ("baseline.md" if trial["method"] == "baseline" else run.EVAL)).is_file())
            self.assertGreater(trial["wall_seconds"], 0)
            self.assertGreater(trial["observation_seconds"], 0)
            self.assertTrue(trial["artifact_hashes"])
        self.assertEqual(review.read_text(encoding="utf-8"), "人手の記入済み評価")
        self.execute()
        self.assertEqual(len(self.calls), 24)

    def test_plan_and_artifact_changes_stop_before_new_generation(self):
        self.prepare()
        with patch.object(comparison, "fingerprint", return_value={"changed": "hash"}), self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(self.calls, [])
        result = self.execute()
        trial = result["trials"][0]
        (self.study / trial["directory"] / "baseline.md").write_text("手編集", encoding="utf-8")
        count = len(self.calls)
        with self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(len(self.calls), count)

    def test_failure_is_recorded_without_rewriting_or_scoring_partial_output(self):
        self.prepare()
        self.fail = True
        result = self.execute()
        self.assertEqual(len(result["trials"]), 1)
        trial = result["trials"][0]
        self.assertEqual(trial["status"], "error")
        self.assertEqual(trial["error_type"], "BadRequestError")
        self.assertNotIn("chars", trial)
        directory = self.study / trial["directory"]
        self.assertTrue((directory / run.INPUT).is_file())
        self.assertTrue((directory / run.CALLS).is_file())
        self.assertFalse((directory / "baseline.md").exists())
        raw = (self.study / "results.json").read_text(encoding="utf-8")
        self.assertNotIn("private-detail", raw)
        self.assertIn("評価状態: 未評価", (self.study / "human_review.md").read_text(encoding="utf-8"))

    def test_actual_context_mismatch_stops_before_plan_creation(self):
        def wrong_command(args, **kwargs):
            self.command(args, **kwargs)
            if args[1] == "load":
                self.set_model(args[2], 8192)

        with self.assertRaises(run.RunError):
            comparison.prepare(self.study, self.config_path, "ユーザ", snapshot=self.state, command=wrong_command)
        self.assertFalse((self.study / "plan.json").exists())
        self.assertEqual(comparison.read(self.study / "preflight.json")["status"], "error")


if __name__ == "__main__":
    unittest.main()
