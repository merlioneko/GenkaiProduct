"""比較の固定条件、失敗と未評価の保持、人手対応付けによる集計。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from novel import run
from test import measure_check as measure
from test.test_m1 import completion
from util.config import PROJECT_ROOT
from util.gateway import OpenAICompatibleGateway


class MeasureCheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        self.config = self.root / "config.json"
        self.config.write_text((PROJECT_ROOT/"config/backends.example.json").read_text(encoding="utf-8"),encoding="utf-8")
        self.loaded_model = "gemma-4-26b-a4b"
        self.bad = None
        self.calls = 0

    def snapshot(self, config):
        return {"status":"observed","models":[{"key":self.loaded_model,"type":"llm","quantization":"test-only",
            "loaded_instances":[{"id":self.loaded_model,"config":{"context_length":16384}}]}]}

    def command(self, args, **kwargs):
        self.loaded_model=args[2]

    def factory(self, **kwargs):
        folder = Path(kwargs["log_path"]).parent
        item=kwargs["phase"].removeprefix("check_")
        case_id=folder.name.split("-",1)[1]
        cases=measure.read(self.study/"fixtures/manifest.json")["cases"]
        known=next(c for c in cases if c["id"]==case_id)["known_issues"]
        def handler(request):
            self.calls+=1
            self.loaded_model=kwargs["model"]
            issues=[{"scene":k["scene"],"quote":k["quote"],"reason":k["rationale"]} for k in known if k["item"]==item]
            if self.bad==(folder.name,item):
                issues=[{"scene":999,"quote":"架空","reason":"不正"}]
            return httpx.Response(200,json=completion(json.dumps({"item":item,"issues":issues},ensure_ascii=False)))
        client=OpenAI(base_url="http://fake.invalid/v1",api_key="test-secret",max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return OpenAICompatibleGateway(**kwargs,client=client)

    def prepare(self):
        measure.prepare(self.study,self.config,"テスト評価者")

    def execute(self):
        with patch.object(measure,"prepare_local_model"),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            return measure.execute(self.study,self.config,gateway_factory=self.factory,
                                   snapshot=self.snapshot,command=self.command)

    def complete_review(self):
        review=measure.read(self.study/"human_review.json")
        for row in review["rows"]:
            row["confirmed"]=True
            for truth in row["ground_truth"]:
                truth.update(decision="include",reason="テスト専用の照合")
            for finding,truth in zip(row["findings"],row["ground_truth"]):
                finding.update(verdict="tp",known_ids=[truth["id"]],reason="テスト専用の対応付け")
        measure.save(self.study/"human_review.json",review)
        return review

    def test_fixture_manifest_source_hashes_and_known_quotes_are_valid(self):
        manifest=measure.validate_fixtures(measure.FIXTURES)
        self.assertEqual(len(manifest["cases"]),5)
        self.assertEqual(len(manifest["excluded_observations"]),2)

    def test_same_fixtures_two_models_switching_retention_and_no_overwrite(self):
        self.prepare()
        self.execute()
        result=measure.read(self.study/"results.json")
        self.assertEqual(len(result["trials"]),10)
        self.assertTrue(all(r["status"]=="success" for r in result["trials"]))
        self.assertEqual(self.calls,30)
        first=result["trials"][0]["observations"][0]
        self.assertIn("gemma",first["before"]["models"][0]["key"])
        self.assertIn("qwen",first["after"]["models"][0]["key"])
        gemma=result["trials"][5]["observations"][0]
        self.assertEqual(gemma["before"],gemma["after"])
        path=self.study/"human_review.md"
        path.write_text("手書き評価を保持",encoding="utf-8")
        self.execute()
        self.assertEqual(self.calls,30)
        self.assertEqual(path.read_text(encoding="utf-8"),"手書き評価を保持")
        report=measure.summarize(self.study)
        self.assertTrue(all(r["tp"] is None and r["status"]=="pending_human" for r in report["rows"]))

    def test_human_matches_drive_metrics_and_unmatched_known_issues_are_false_negatives(self):
        self.prepare()
        self.execute()
        review=self.complete_review()
        row=next(r for r in review["rows"] if r["trial"]=="qwen-synthetic-errors" and r["item"]=="elements")
        row["findings"][0].update(verdict="fp",known_ids=[],reason="テストの誤検出")
        measure.save(self.study/"human_review.json",review)
        report=measure.summarize(self.study)
        row=next(r for r in report["rows"] if r["trial"]=="qwen-synthetic-errors" and r["item"]=="elements")
        self.assertEqual((row["tp"],row["fp"],row["fn"],row["recall"]),(1,1,1,0.5))
        self.assertTrue(all(r["status"]=="reviewed" for r in report["totals"]))
        review["rows"][0]["ground_truth"].append({"id":"架空","decision":"include","reason":"不正"})
        measure.save(self.study/"human_review.json",review)
        with self.assertRaises(run.RunError):
            measure.summarize(self.study)

    def test_format_failure_is_not_scored_zero_and_study_does_not_retry_it(self):
        self.prepare()
        self.bad=("qwen-synthetic-errors","consistency")
        self.execute()
        result=measure.read(self.study/"results.json")
        trial=next(t for t in result["trials"] if t["id"]==self.bad[0])
        self.assertEqual(trial["status"],"error")
        self.assertEqual(trial["items"]["consistency"],"error")
        self.assertEqual(trial["items"]["physical"],"not_run")
        count=self.calls
        self.execute()
        self.assertEqual(self.calls,count)
        report=measure.summarize(self.study)
        row=next(r for r in report["rows"] if r["trial"]==trial["id"] and r["item"]=="consistency")
        self.assertIsNone(row["recall"])
        self.assertIsNone(row["fn"])

    def test_changed_conditions_inputs_or_saved_outputs_stop_before_calls(self):
        self.prepare()
        path=self.study/"fixtures/synthetic-normal/04_scenes/scene_01.md"
        original=path.read_bytes()
        path.write_text("変更",encoding="utf-8")
        with self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(self.calls,0)
        path.write_bytes(original)
        self.execute()
        path=self.study/"qwen-synthetic-normal/06_check/elements.json"
        path.write_text('{}',encoding="utf-8")
        calls=self.calls
        with self.assertRaises(run.RunError):
            self.execute()
        self.assertEqual(self.calls,calls)


if __name__ == "__main__":
    unittest.main()
