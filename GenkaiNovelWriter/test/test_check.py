"""M6: 機械検査と実SDKによる項目別検査、失敗・退避・本文保護。"""

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import httpx
from openai import BadRequestError, OpenAI
from pydantic import ValidationError

from main import stage
from novel import checks, run
from novel.phases.check import CheckFormatError, ITEMS, load_inputs
from novel.schema import CheckIssue, CheckResult, Novel, NovelScene
from test.test_m1 import completion
from util.config import PROJECT_ROOT
from util.gateway import OpenAICompatibleGateway

FIXTURE = PROJECT_ROOT / "test/fixtures/check/synthetic-normal"


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "run"
        shutil.copytree(FIXTURE, self.directory)
        self.config = self.root / "config.json"
        self.config.write_text((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        (self.directory / run.EVAL).write_text("人手評価を保存", encoding="utf-8")
        (self.directory / run.CONFIG_SNAPSHOT).write_text("生成時の設定", encoding="utf-8")
        self.requests = []
        self.responses = {}
        self.fail_item = None

    def factory(self, **kwargs):
        item = kwargs["phase"].removeprefix("check_")

        def handler(request):
            self.requests.append((item, json.loads(request.content)))
            if self.fail_item == item:
                return httpx.Response(400, json={"error": {"message": "private-detail"}})
            data = self.responses.get(item, {"item": item, "issues": []})
            return httpx.Response(200, json=completion(json.dumps(data, ensure_ascii=False)))

        client = OpenAI(base_url="http://fake.invalid/v1", api_key="test-secret", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return OpenAICompatibleGateway(**kwargs, client=client)

    def check(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return stage("check", run_dir=self.directory, config_path=self.config,
                         allowed_names=["NASA"], gateway_factory=self.factory)

    def protected(self):
        return {p.relative_to(self.directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.directory.rglob("*") if p.is_file() and (
                    p.name in (run.INPUT, run.PLOT, run.DRAFT, run.EVAL, run.CONFIG_SNAPSHOT)
                    or p.parent.name == run.SCENES)}

    def test_all_items_separate_requests_and_preserve_inputs_and_human_review(self):
        before = self.protected()
        self.assertEqual(self.check(), self.directory)
        self.assertEqual(before, self.protected())
        self.assertEqual([i for i, _ in self.requests], ["elements", "consistency", "physical"])
        for item in ITEMS:
            self.assertTrue(run.check_path(self.directory, item).exists())
        self.assertEqual(json.loads(run.check_path(self.directory,"contamination").read_text(encoding="utf-8"))["issues"], [])
        _, novel = load_inputs(self.directory)
        for item, request in self.requests:
            data = json.loads(request["messages"][1]["content"])
            self.assertEqual([s["content"] for s in data["scenes"]], [s.content for s in novel.scenes])
            self.assertEqual([s["scene"] for s in data["scenes"]], [1, 2])
            self.assertIn(item, request["messages"][0]["content"])
        log = [json.loads(s) for s in (self.directory/run.CALLS).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(log), 3)
        self.assertTrue(all(s["input_tokens"] is not None and s["duration_seconds"] >= 0 for s in log))
        metadata = json.loads((self.directory/run.CHECK/"metadata.json").read_text(encoding="utf-8"))
        self.assertNotIn("api_key", json.dumps(metadata))

    def test_repeated_check_archives_results_but_not_review_or_generation_config(self):
        self.check()
        before = self.protected()
        old = run.check_path(self.directory,"physical").read_bytes()
        self.check()
        archives = list((self.directory/run.ARCHIVE).iterdir())
        self.assertEqual(len(archives), 1)
        self.assertEqual((archives[0]/run.CHECK/"physical.json").read_bytes(), old)
        self.assertTrue((archives[0]/run.CHECK_REPORT).is_file())
        self.assertEqual(before, self.protected())

    def test_incomplete_empty_extra_or_stale_draft_stops_before_archive_or_requests(self):
        self.check()
        for mode in ("missing", "empty", "extra", "draft"):
            with self.subTest(mode=mode):
                target = self.directory / (run.DRAFT if mode == "draft" else f"{run.SCENES}/scene_02.md")
                old = target.read_bytes()
                if mode == "missing":
                    target.unlink()
                elif mode == "extra":
                    run.scene_path(self.directory, 3).write_text("余分", encoding="utf-8")
                else:
                    target.write_text("別の草稿" if mode == "draft" else " \n", encoding="utf-8")
                try:
                    count = len(self.requests)
                    with self.assertRaises(run.RunError):
                        self.check()
                    self.assertEqual(len(self.requests), count)
                    self.assertFalse((self.directory/run.ARCHIVE).exists())
                    self.assertTrue(run.check_path(self.directory,"physical").exists())
                finally:
                    target.write_bytes(old)
                    if mode == "extra":
                        run.scene_path(self.directory,3).unlink()

    def test_wrong_item_scene_quote_and_overlong_quote_are_saved_as_format_failures(self):
        samples = [dict(item="physical",scene=1,quote="廊下"),
                   dict(item="elements",scene=3,quote="廊下"),
                   dict(item="elements",scene=2,quote="廊下で管理人"),
                   dict(item="elements",scene=1,quote="存在しない原文"),
                   dict(item="elements",scene=1,quote="長"*31),
                   dict(item="elements",scene=1,quote="")]
        for sample in samples:
            self.requests.clear()
            self.responses["elements"] = {"item":sample["item"], "issues":[
                {"scene":sample["scene"],"quote":sample["quote"],"reason":"根拠"}]}
            with self.subTest(sample=sample), self.assertRaises(CheckFormatError):
                self.check()
            self.assertEqual(len(self.requests), 1)
            self.assertTrue((self.directory/run.CHECK/"elements_raw.txt").is_file())
            self.assertFalse(run.check_path(self.directory,"elements").exists())
            self.assertIn("未実行",(self.directory/run.CHECK_REPORT).read_text(encoding="utf-8"))

    def test_api_errors_preserve_finished_items_without_repair_or_retry(self):
        for item, count in (("elements",1),("consistency",2),("physical",3)):
            self.fail_item=item
            self.requests.clear()
            before = self.protected()
            with self.subTest(item=item), self.assertRaises(BadRequestError):
                self.check()
            self.assertEqual(len(self.requests),count)
            self.assertTrue(run.check_path(self.directory,"length").is_file())
            self.assertFalse(run.check_path(self.directory,item).is_file())
            self.assertEqual(self.protected(), before)
            report=(self.directory/run.CHECK_REPORT).read_text(encoding="utf-8")
            self.assertIn("失敗",report)
            self.assertNotIn("private-detail",report)

    def test_reported_issues_do_not_trigger_generation_or_stop_later_items(self):
        self.responses["elements"]={"item":"elements","issues":[{"scene":1,"quote":"廊下","reason":"テスト指摘"}]}
        self.check()
        self.assertEqual(len(self.requests),3)
        self.assertIn("テスト指摘",(self.directory/run.CHECK_REPORT).read_text(encoding="utf-8"))


class MechanicalCheckTest(unittest.TestCase):
    def novel(self, text):
        return Novel(scenes=[NovelScene(index=1,title="検査",content=text)])

    def test_contamination_regressions_allowlist_and_normal_words(self):
        text="黒ish。Episode 1 はここで幕を閉じた。第1話。<think>思考</think>。NASA。NASAX。"
        result=checks.check_contamination(self.novel(text),("NASA",))
        quotes=[i.quote for i in result.issues]
        for quote in ("ish","Episode 1","幕を閉じた","第1話","<think>","</think>","NASAX"):
            self.assertIn(quote,quotes)
        self.assertNotIn("NASA",quotes)
        self.assertFalse(checks.check_contamination(self.novel("思考を巡らせる。青い瞳の葵。NASA"),("NASA",)).issues)

    def test_length_excludes_unicode_whitespace_and_warns_only_below_600(self):
        for count in (599,600):
            novel=self.novel("あ"*count+" \n\t\u3000")
            result=checks.check_length(novel)
            self.assertEqual(result.total,count)
            self.assertEqual(result.counts[0].characters,count)
            self.assertEqual(bool(result.issues),count<600)

    def test_quote_length_is_a_schema_constraint(self):
        for quote in ("", "あ"*31):
            with self.assertRaises(ValidationError):
                CheckIssue(scene=1,quote=quote,reason="理由")
        self.assertEqual(len(CheckIssue(scene=1,quote="あ"*30,reason="理由").quote),30)
        with self.assertRaises(ValidationError):
            CheckResult(item="wrong",issues=[])


if __name__ == "__main__":
    unittest.main()
