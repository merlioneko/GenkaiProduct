"""Writing・再開・Assemble。SDK にはメモリ上の HTTP 応答のみ渡す。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import BadRequestError, OpenAI

from main import main, stage, write
from novel import run
from novel.context import writing_messages
from novel.phases.structure import PlotFormatError, load_plot
from novel.phases.writing import assemble
from test.test_m1 import completion
from test.test_stage import plot_data
from util.config import PROJECT_ROOT
from util.gateway import GenerationError, OpenAICompatibleGateway


class WritingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        idea = self.root / "idea.txt"
        idea.write_text("ギャルと魔人の話", encoding="utf-8")
        self.directory = run.create_run(idea, output_root=self.root / "creations")
        self.config_path = self.root / "backends.json"
        self.config_path.write_text(
            (PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"), encoding="utf-8")
        data = plot_data()
        data["constraints"] = ["ジャンル: ドタバタラブコメ"]
        data["events"] = ["魔人が住み着く", "ギャルが出発", "ギャルが帰宅"]
        data["scenes"].append({**data["scenes"][1], "name": "帰宅", "beats": ["ギャルが帰宅"], "covers": [3]})
        (self.directory / run.PLOT).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.requests = []
        self.gateway_options = []
        self.responder = lambda number: httpx.Response(200, json=completion(f"本文{number}。" * 160))

    def factory(self, **kwargs):
        self.gateway_options.append(kwargs)

        def handler(request):
            self.requests.append(json.loads(request.content))
            return self.responder(len(self.requests))

        client = OpenAI(base_url="http://fake.invalid/v1", api_key="test-secret", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return OpenAICompatibleGateway(**kwargs, client=client)

    def write(self, first=1):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return write(self.directory, first=first, config_path=self.config_path,
                         gateway_factory=self.factory, timeout=1800)

    def save_scene(self, number, text):
        path = run.scene_path(self.directory, number)
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_stage_writing_saves_all_scenes_and_assembled_draft(self):
        with contextlib.redirect_stdout(io.StringIO()):
            stage("writing", run_dir=self.directory, config_path=self.config_path,
                  gateway_factory=self.factory, timeout=1800)
        contents = [path.read_text(encoding="utf-8") for path in run.scene_paths(self.directory)]
        self.assertEqual(len(contents), 3)
        self.assertEqual((self.directory / run.DRAFT).read_text(encoding="utf-8"), "\n\n".join(contents) + "\n")
        self.assertEqual(self.gateway_options[0]["phase"], "writing")
        self.assertIsNone(self.gateway_options[0]["thinking"])
        self.assertEqual(self.gateway_options[0]["timeout"], 1800)
        self.assertNotIn("extra_body", self.requests[0])
        logs = [json.loads(line) for line in (self.directory / run.CALLS).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["scene"] for row in logs], [1, 2, 3])
        self.assertEqual(logs[-1]["input_tokens"] + logs[-1]["output_tokens"], 168)
        self.assertIn(contents[0], self.requests[2]["messages"][1]["content"])
        self.assertIn(contents[1], self.requests[2]["messages"][1]["content"])

    def test_context_has_spec_order_numbered_events_and_full_prior_text(self):
        prior = " 手編集された本文\n" + "省略しない。" * 2000
        self.save_scene(1, prior)
        messages = writing_messages(self.directory, load_plot(self.directory), 2, "SYSTEM")
        self.assertEqual(messages[0], {"role": "system", "content": "SYSTEM"})
        user = messages[1]["content"]
        headings = ["# meta", "# 指定要素", "# 登場人物・設定", "# 全シーンの一覧",
                    "# 既存シーンの本文", "# 担当シーン 2"]
        self.assertEqual([user.index(h) for h in headings], sorted(user.index(h) for h in headings))
        self.assertIn(prior, user)
        self.assertIn('"number": 3', user)
        self.assertIn('"event": "ギャルが帰宅"', user)
        self.assertIn('"担当": true', user)
        self.assertIn('"opening"', user)
        self.assertIn('"target_chars": 1000', user)

    def test_resume_preserves_edited_bytes_and_archives_only_later_artifacts(self):
        first = self.save_scene(1, "一番目\r\nの本文。")
        second = self.save_scene(2, "二番目を手で編集。\n" + "全文" * 500)
        before = [first.read_bytes(), second.read_bytes()]
        self.save_scene(3, "旧三番目")
        for name in (run.DRAFT, run.CHECK_REPORT, f"{run.CHECK}/elements.json"):
            path = self.directory / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("旧成果物", encoding="utf-8")
        self.write(3)
        self.assertEqual([first.read_bytes(), second.read_bytes()], before)
        self.assertEqual(len(self.requests), 1)
        self.assertIn(second.read_text(encoding="utf-8"), self.requests[0]["messages"][1]["content"])
        archive = next((self.directory / run.ARCHIVE).iterdir())
        self.assertEqual(run.scene_path(archive, 3).read_text(encoding="utf-8"), "旧三番目")
        self.assertFalse(run.scene_path(archive, 1).exists())
        for name in (run.DRAFT, run.CHECK_REPORT, f"{run.CHECK}/elements.json"):
            self.assertEqual((archive / name).read_text(encoding="utf-8"), "旧成果物")
        self.assertFalse((self.directory / run.CHECK).exists())

    def test_from_one_archives_entire_scenes_directory(self):
        self.save_scene(1, "旧本文")
        (self.directory / run.SCENES / "memo.txt").write_text("メモ", encoding="utf-8")
        self.write(1)
        archive = next((self.directory / run.ARCHIVE).iterdir())
        self.assertEqual((archive / run.SCENES / "memo.txt").read_text(encoding="utf-8"), "メモ")
        self.assertFalse((self.directory / run.SCENES / "memo.txt").exists())

    def test_invalid_start_and_missing_or_empty_prior_scene_do_not_archive_or_call(self):
        self.save_scene(3, "旧三番目")
        for first in (0, -1, 4, 3):
            with self.assertRaises(run.RunError):
                self.write(first)
        self.save_scene(1, " \n")
        with self.assertRaises(run.RunError):
            self.write(2)
        self.assertEqual(self.requests, [])
        self.assertFalse((self.directory / run.ARCHIVE).exists())
        self.assertEqual(run.scene_path(self.directory, 3).read_text(encoding="utf-8"), "旧三番目")

    def test_broken_plot_stops_before_archiving_or_calling(self):
        self.save_scene(1, "既存本文")
        (self.directory / run.PLOT).write_text('{"壊れた":true}', encoding="utf-8")
        with self.assertRaises(PlotFormatError):
            self.write()
        self.assertEqual(self.requests, [])
        self.assertFalse((self.directory / run.ARCHIVE).exists())

    def test_context_error_stops_without_truncation_and_records_scene_usage(self):
        def responder(number):
            if number == 2:
                return httpx.Response(400, json={"error": {"message": "private-server-detail"},
                                                "usage": {"prompt_tokens": 17000, "completion_tokens": 0}})
            return httpx.Response(200, json=completion("長い前シーン。" * 1000))
        self.responder = responder
        with self.assertRaises(BadRequestError):
            self.write()
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(run.scene_path(self.directory, 1).exists())
        self.assertFalse(run.scene_path(self.directory, 2).exists())
        self.assertFalse((self.directory / run.DRAFT).exists())
        self.assertIn("長い前シーン。" * 1000, self.requests[1]["messages"][1]["content"])
        raw = (self.directory / run.CALLS).read_text(encoding="utf-8")
        last = json.loads(raw.splitlines()[-1])
        self.assertEqual((last["scene"], last["status"], last["input_tokens"]), (2, "error", 17000))
        self.assertNotIn("private-server-detail", raw)

    def test_truncated_or_empty_generation_never_becomes_a_scene_or_draft(self):
        for response in (completion("部分本文", finish="length"), completion(" \n")):
            self.responder = lambda number: httpx.Response(200, json=response)
            with self.assertRaises(GenerationError):
                self.write()
            self.assertFalse(run.scene_path(self.directory, 1).exists())
            self.assertFalse((self.directory / run.DRAFT).exists())

    def test_assemble_counts_whitespace_free_characters_and_warns_below_600_only(self):
        self.save_scene(1, "あ" * 599 + " \t\n\u3000")
        self.save_scene(2, "い" * 600)
        self.save_scene(3, "う" * 601)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            novel = assemble(self.directory, load_plot(self.directory))
        self.assertEqual(len(novel.scenes), 3)
        self.assertIn("合計: 1800字", stdout.getvalue())
        self.assertIn("scene_01", stderr.getvalue())
        self.assertNotIn("scene_02", stderr.getvalue())
        self.assertNotIn("警告", (self.directory / run.DRAFT).read_text(encoding="utf-8"))

    def test_assemble_missing_scene_does_not_write_partial_draft(self):
        self.save_scene(1, "本文")
        with self.assertRaises(run.RunError):
            assemble(self.directory, load_plot(self.directory))
        self.assertFalse((self.directory / run.DRAFT).exists())

    def test_cli_dispatches_write_and_stage_writing(self):
        with patch("main.write", return_value=self.directory) as mocked, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["write", "--run", str(self.directory), "--from", "3", "--timeout", "1800"]), 0)
            self.assertEqual(mocked.call_args.kwargs["first"], 3)
            self.assertEqual(mocked.call_args.kwargs["timeout"], 1800)
        with patch("main.stage", return_value=self.directory) as mocked, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["stage", "writing", "--run", str(self.directory)]), 0)
            self.assertEqual(mocked.call_args.args[0], "writing")

    def test_cli_rejects_input_for_writing_and_missing_from(self):
        for argv in (["stage", "writing", "--run", "x", "--input", "y"], ["write", "--run", "x"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(argv)
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
