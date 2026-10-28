"""physical比較の44回採取・調整/確認分割・固定条件・失敗保存。"""

import json
import unittest

from novel import run
from test import compare_physical
from test import test_remediation as fixtures


class PhysicalComparisonTest(unittest.TestCase):
    setUp = fixtures.RemediationTest.setUp
    factory = fixtures.RemediationTest.factory

    def snapshot(self, config):
        return {"status": "observed", "models": [{"key": config.phase("writing").model, "type": "llm",
                 "quantization": {"name": "stub"}, "loaded_instances": [
                     {"id": "gemma", "config": {"context_length": config.context_length}}]}]}

    def prepare(self):
        self.study = self.root / "physical-study"
        compare_physical.prepare(self.study, self.config, evaluator="ユーザ", snapshot=self.snapshot)

    def execute(self):
        return compare_physical.execute(self.study, self.config, gateway_factory=self.factory, snapshot=self.snapshot)

    def test_forty_four_trials_separate_tuning_and_holdout_without_overwriting_human_review(self):
        self.prepare()
        plan = json.loads((self.study / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(len(plan["trials"]), 44)
        self.assertTrue(all(t["split"] == "tuning" for t in plan["trials"][:32]))
        self.assertTrue(all(t["split"] == "holdout" for t in plan["trials"][32:]))
        self.execute()
        self.assertEqual(len(self.requests), 44)
        results = json.loads((self.study / "results.json").read_text(encoding="utf-8"))
        self.assertTrue(all(t["status"] == "success" for t in results["trials"]))
        self.assertTrue(all(t["call_id"] for t in results["trials"]))
        path = self.study / "human_review.md"
        path.write_text("人手照合を書き込んだ", encoding="utf-8")
        self.execute()
        self.assertEqual(len(self.requests), 44)
        self.assertEqual(path.read_text(encoding="utf-8"), "人手照合を書き込んだ")

    def test_changed_candidate_or_fixed_artifact_stops_before_any_calls(self):
        self.prepare()
        prompt = self.study / "prompts/candidate.md"
        previous = prompt.read_bytes()
        prompt.write_text("changed", encoding="utf-8")
        with self.assertRaises(run.RunError):
            self.execute()
        prompt.write_bytes(previous)
        artifact = next((self.study / "fixtures").glob("*/03_plot.json"))
        artifact.write_text("{}", encoding="utf-8")
        with self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(self.requests, [])

    def test_quote_failures_keep_gateway_success_and_trial_failure_without_resampling(self):
        self.prepare()
        self.answers["check_physical"] = {"item": "physical", "issues": [
            {"scene": 1, "quote": "どの原文にも存在しない引用", "reason": "テスト"}]}
        self.execute()
        self.execute()
        results = json.loads((self.study / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.requests), 44)
        self.assertTrue(all(t["status"] == "error" for t in results["trials"]))
        self.assertTrue(all(t["error_code"] == "quote_mismatch" for t in results["trials"]))
        first = self.study / results["trials"][0]["id"]
        log = json.loads((first / run.CALLS).read_text(encoding="utf-8"))
        self.assertEqual(log["status"], "success")
        self.assertTrue((first / "physical_raw.txt").exists())
        self.assertFalse((first / "physical.json").exists())
