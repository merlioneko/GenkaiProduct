"""M4: 実フェーズ・SDK・メモリ上のHTTP応答による一括実行と失敗時の保存点。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import BadRequestError, OpenAI

from main import main, run_pipeline, stage, write
from novel import evaluation, run
from novel.phases.concept import ConceptFormatError
from novel.phases.structure import PlotFormatError, StructureError
from test.test_m1 import completion
from test.test_stage import CONCEPT_MARKDOWN, plot_data
from util.config import ConfigError, PROJECT_ROOT
from util.gateway import OpenAICompatibleGateway


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.creations = self.root / "creations"
        self.config = self.root / "config.json"
        # Check・baselineの設定は生成部分の必須条件ではない。
        config = json.loads((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"))
        for backend in config.values():
            backend["phases"].pop("check")
            backend["phases"].pop("baseline")
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.requests = []
        self.options = []
        self.fail_at = None
        self.invalid_concept = False
        self.invalid_plot = False
        self.findings = False

    def factory(self, **kwargs):
        self.options.append(kwargs)
        phase = kwargs["phase"]

        def handler(request):
            self.requests.append((phase, json.loads(request.content)))
            if len(self.requests) == self.fail_at:
                return httpx.Response(400, json={"error": {"message": "private-api-detail"}})
            if phase == "concept":
                text = "壊れた構想" if self.invalid_concept else CONCEPT_MARKDOWN
            elif phase == "concept_verify":
                findings = [{"kind": "missing", "element": "追加指定", "detail": "未記載"}] if self.findings else []
                text = json.dumps({"findings": findings}, ensure_ascii=False)
            elif phase == "structure":
                data = plot_data()
                if self.findings:
                    data["characters"].append({**data["characters"][0], "name": "未使用人物"})
                text = "{}" if self.invalid_plot else json.dumps(data, ensure_ascii=False)
            elif phase == "writing":
                text = f"シーン本文{len(self.requests)}。" * 100
            else:
                self.fail(f"Unexpected phase: {phase}")
            return httpx.Response(200, json=completion(text))

        client = OpenAI(base_url="http://fake.invalid/v1", api_key="test-secret", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return OpenAICompatibleGateway(**kwargs, client=client)

    def generate(self, input_name="concrete_01.txt", **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_pipeline(PROJECT_ROOT / "prompts/tests" / input_name, config_path=self.config,
                                output_root=self.creations, gateway_factory=self.factory,
                                timeout=1800, **kwargs)

    def test_both_inputs_complete_without_check_and_use_saved_prior_scenes(self):
        directories = []
        for input_name in ("concrete_01.txt", "vague_01.txt"):
            self.requests.clear()
            directory = self.generate(input_name)
            directories.append(directory)
            for name in (run.INPUT, run.CONFIG_SNAPSHOT, run.CONCEPT, run.CONCEPT_REPORT,
                         run.PLOT, run.PLOT_REPORT, run.DRAFT, run.EVAL, run.CALLS):
                self.assertTrue((directory / name).is_file(), name)
            self.assertEqual(run.read_input(directory),
                             (PROJECT_ROOT / "prompts/tests" / input_name).read_text(encoding="utf-8"))
            self.assertEqual([name for name, _ in self.requests],
                             ["concept", "concept_verify", "structure", "writing", "writing"])
            scenes = [path.read_text(encoding="utf-8") for path in run.scene_paths(directory)]
            self.assertEqual((directory / run.DRAFT).read_text(encoding="utf-8"), "\n\n".join(scenes) + "\n")
            self.assertIn(scenes[0], self.requests[-1][1]["messages"][1]["content"])
            self.assertFalse((directory / run.CHECK).exists())
            self.assertFalse((directory / run.CHECK_REPORT).exists())
            logs = [json.loads(line) for line in (directory / run.CALLS).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["status"] for row in logs], ["success"] * 5)
            self.assertTrue(all(row["duration_seconds"] >= 0 for row in logs))
            self.assertTrue(all(row["input_tokens"] is not None for row in logs))
        self.assertNotEqual(*directories)
        self.assertTrue(all(options["timeout"] == 1800 for options in self.options))
        raw = (directories[-1] / run.CONFIG_SNAPSHOT).read_text(encoding="utf-8")
        self.assertNotIn("api_key", raw)

    def test_reports_with_findings_do_not_stop_the_pipeline(self):
        self.findings = True
        directory = self.generate()
        for name in (run.CONCEPT_REPORT, run.PLOT_REPORT):
            self.assertTrue(json.loads((directory / name).read_text(encoding="utf-8"))["findings"])
        self.assertTrue((directory / run.EVAL).exists())

    def test_api_error_at_each_call_stops_and_keeps_completed_artifacts(self):
        for number in range(1, 6):
            with self.subTest(call=number):
                self.requests.clear()
                self.fail_at = number
                before = set(self.creations.iterdir()) if self.creations.exists() else set()
                with self.assertRaises(BadRequestError):
                    self.generate()
                directory, = set(self.creations.iterdir()) - before
                self.assertEqual(len(self.requests), number)
                for name in (run.INPUT, run.CONFIG_SNAPSHOT, run.CALLS):
                    self.assertTrue((directory / name).exists())
                for completed_after, name in ((1, run.CONCEPT), (2, run.CONCEPT_REPORT),
                                              (3, run.PLOT), (3, run.PLOT_REPORT),
                                              (4, f"{run.SCENES}/scene_01.md")):
                    self.assertEqual((directory / name).exists(), number > completed_after, name)
                self.assertFalse((directory / run.DRAFT).exists())
                self.assertFalse((directory / run.EVAL).exists())
                raw = (directory / run.CALLS).read_text(encoding="utf-8")
                self.assertEqual(json.loads(raw.splitlines()[-1])["status"], "error")
                self.assertNotIn("private-api-detail", raw)

    def test_invalid_concept_stops_before_verification_and_is_preserved(self):
        self.invalid_concept = True
        with self.assertRaises(ConceptFormatError):
            self.generate()
        directory = next(self.creations.iterdir())
        self.assertEqual((directory / run.CONCEPT).read_text(encoding="utf-8").strip(), "壊れた構想")
        self.assertEqual([name for name, _ in self.requests], ["concept"])
        self.assertFalse((directory / run.EVAL).exists())

    def test_invalid_plot_stops_after_existing_structure_retry_limit_and_preserves_raw(self):
        self.invalid_plot = True
        with self.assertRaises(StructureError):
            self.generate()
        directory = next(self.creations.iterdir())
        self.assertEqual([name for name, _ in self.requests],
                         ["concept", "concept_verify", "structure", "structure", "structure"])
        self.assertEqual((directory / run.PLOT_RAW).read_text(encoding="utf-8"), "{}")
        self.assertTrue((directory / run.CONCEPT_REPORT).exists())
        self.assertFalse((directory / run.SCENES).exists())

    def test_invalid_saved_plot_is_not_repaired_by_writing(self):
        from novel.phases.structure import run_structure

        def corrupt(*args, **kwargs):
            plot = run_structure(*args, **kwargs)
            (Path(args[0]) / run.PLOT).write_text("{}", encoding="utf-8")
            return plot

        with patch("main.structure_phase.run_structure", side_effect=corrupt), self.assertRaises(PlotFormatError):
            self.generate()
        self.assertEqual([name for name, _ in self.requests], ["concept", "concept_verify", "structure"])

    def test_missing_phase_config_stops_before_creating_a_run(self):
        data = json.loads(self.config.read_text(encoding="utf-8"))
        del data["local"]["phases"]["writing"]
        self.config.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ConfigError):
            self.generate()
        self.assertFalse(self.creations.exists())
        self.assertEqual(self.requests, [])

    def test_evaluation_includes_original_input_order_and_unfilled_judgments(self):
        directory = self.generate()
        text = (directory / run.EVAL).read_text(encoding="utf-8")
        for marker in ("[原入力](00_input.txt)", "原入力との照合", "評価者:", "総合判定:",
                       "本文のシーン・引用", "未評価", "ジャンル・トーン", "設定一貫性",
                       "物理的妥当性", "600字未満", "伏線放置", "非陳腐性"):
            self.assertIn(marker, text)
        self.assertIn("| 1 | ジャンル: ドタバタラブコメ |  |  |", text)
        self.assertLess(text.index("| 1 | 魔人が住み着く"), text.index("| 2 | ギャルがカチコミに行く"))
        self.assertNotIn("合格", text)
        (directory / run.EVAL).write_text("記入済み評価", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            evaluation.save_template(directory)
        self.assertEqual((directory / run.EVAL).read_text(encoding="utf-8"), "記入済み評価")

    def test_evaluation_requires_a_draft_and_escapes_table_content(self):
        directory = self.generate()
        (directory / run.EVAL).unlink()
        data = json.loads((directory / run.PLOT).read_text(encoding="utf-8"))
        data["constraints"] = ["A|B\n<script>"]
        (directory / run.PLOT).write_text(json.dumps(data), encoding="utf-8")
        evaluation.save_template(directory)
        self.assertIn("A&#124;B<br>&lt;script&gt;", (directory / run.EVAL).read_text(encoding="utf-8"))
        (directory / run.DRAFT).unlink()
        with self.assertRaises(run.RunError):
            evaluation.save_template(directory)

    def test_generation_reruns_archive_completed_evaluation_even_on_api_failure(self):
        for operation in ("concept", "structure", "writing", "resume"):
            with self.subTest(operation=operation):
                self.fail_at = None
                directory = self.generate()
                path = directory / run.EVAL
                path.write_bytes("評価者: 人間\r\n判定済み".encode("utf-8"))
                before = path.read_bytes()
                first_scene = run.scene_path(directory, 1).read_bytes()
                self.fail_at = len(self.requests) + 1
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(BadRequestError):
                    if operation == "resume":
                        write(directory, first=2, config_path=self.config, gateway_factory=self.factory)
                    else:
                        stage(operation, run_dir=directory, config_path=self.config, gateway_factory=self.factory)
                self.assertFalse(path.exists())
                archive, = (directory / run.ARCHIVE).iterdir()
                self.assertEqual((archive / run.EVAL).read_bytes(), before)
                if operation == "resume":
                    self.assertEqual(run.scene_path(directory, 1).read_bytes(), first_scene)

    def test_cli_dispatches_run_options_and_reports_errors_without_secret_details(self):
        with patch("main.run_pipeline", return_value=self.root) as mocked, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(["run", "--input", "idea.txt", "--backend", "remote", "--config", "c.json",
                                   "--thinking-options", "t.json", "--timeout", "1800"]), 0)
        self.assertEqual(mocked.call_args.args, (Path("idea.txt"),))
        self.assertEqual(mocked.call_args.kwargs, {"backend": "remote", "config_path": Path("c.json"),
                                                  "thinking_options": Path("t.json"), "timeout": 1800})
        self.assertIn("品質評価には使用しない", stdout.getvalue())
        with patch("main.run_pipeline", side_effect=RuntimeError("private-secret")), \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(main(["run", "--input", "idea.txt"]), 1)
        self.assertNotIn("private-secret", stderr.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["run"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
