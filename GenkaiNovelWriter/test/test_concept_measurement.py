"""U13採取計画の固定・16回採取・失敗保存をAPIなしで検証する。"""

import json
import unittest
from unittest.mock import patch

from novel import run
from test import measure_concept
from test import test_remediation as fixtures


class ConceptMeasurementTest(unittest.TestCase):
    setUp = fixtures.RemediationTest.setUp
    factory = fixtures.RemediationTest.factory

    def snapshot(self, config):
        return {"status": "observed", "models": [{"key": config.phase("concept").model, "type": "llm",
                 "quantization": {"name": "stub"}, "loaded_instances": [
                     {"id": "qwen", "config": {"context_length": config.context_length}}]}]}

    def prepare(self):
        self.study = self.root / "study"
        return measure_concept.prepare(self.study, self.config, evaluator="ユーザ", snapshot=self.snapshot)

    def execute(self):
        return measure_concept.execute(self.study, self.config, gateway_factory=self.factory, snapshot=self.snapshot)

    def test_sixteen_fixed_trials_have_logs_outputs_and_unscored_review_without_resampling(self):
        self.prepare()
        self.execute()
        self.assertEqual(len(self.requests), 16)
        results = json.loads((self.study / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(results["trials"]), 16)
        self.assertTrue(all(t["status"] == "success" for t in results["trials"]))
        self.assertTrue(all(t["call_id"] for t in results["trials"]))
        review = (self.study / "human_review.md").read_bytes()
        self.execute()
        self.assertEqual(len(self.requests), 16)
        self.assertEqual((self.study / "human_review.md").read_bytes(), review)

    def test_plan_input_or_code_mutation_stops_before_sampling(self):
        self.prepare()
        with patch("test.measure_concept.code_hashes", return_value={}):
            with self.assertRaises(run.RunError):
                self.execute()
        plan = json.loads((self.study / "plan.json").read_text(encoding="utf-8"))
        path = self.study / plan["trials"][0]["id"] / run.INPUT
        original = path.read_bytes()
        path.write_text("changed", encoding="utf-8")
        with self.assertRaises(run.RunError):
            self.execute()
        path.write_bytes(original)
        plan["evaluator"] = "changed"
        (self.study / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(self.requests, [])

    def test_failed_trials_are_retained_and_not_retried_or_scored_as_clean(self):
        self.prepare()
        self.fail_phase = "concept_verify"
        self.execute()
        self.execute()
        results = json.loads((self.study / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.requests), 16)
        self.assertTrue(all(t["status"] == "error" for t in results["trials"]))
        self.assertIn("未測定", (self.study / "human_review.md").read_text(encoding="utf-8"))
        self.assertNotIn("private-connection-detail", (self.study / "results.json").read_text(encoding="utf-8"))

    def test_changed_observed_context_is_rejected_before_plan_creation(self):
        def bad(config):
            result = self.snapshot(config)
            result["models"][0]["loaded_instances"][0]["config"]["context_length"] = 8192
            return result
        with self.assertRaises(run.RunError):
            measure_concept.prepare(self.root / "bad-study", self.config, evaluator="ユーザ", snapshot=bad)
        self.assertFalse((self.root / "bad-study").exists())
