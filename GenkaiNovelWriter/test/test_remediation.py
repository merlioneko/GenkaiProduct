"""M6後修正: 事前検証・部分失敗・再結合・来歴を実SDKのメモリ応答で検証する。"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

import main as cli
from novel import checks, evaluation, history, run
from novel.phases import concept, structure, writing
from novel.phases.check import CheckFormatError, LLM_ITEMS
from novel.schema import Plot
from test.test_m1 import completion
from test.test_stage import CONCEPT_MARKDOWN, plot_data
from util.config import PROJECT_ROOT
from util.gateway import OpenAICompatibleGateway


class RemediationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "run"
        shutil.copytree(PROJECT_ROOT / "test/fixtures/check/synthetic-normal", self.directory)
        (self.directory / run.CONCEPT).write_text(CONCEPT_MARKDOWN, encoding="utf-8")
        (self.directory / run.CONFIG_SNAPSHOT).write_text("legacy config", encoding="utf-8")
        (self.directory / run.EVAL).write_text("評価済み", encoding="utf-8")
        self.idea = self.root / "idea.txt"
        self.idea.write_text("雪の町を舞台にした静かな短編", encoding="utf-8")
        self.config = self.root / "config.json"
        self.config.write_bytes((PROJECT_ROOT / "config/backends.example.json").read_bytes())
        self.requests = []
        self.answers = {}
        self.fail_phase = None
        self.creations = self.root / "creations"
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.stdout))
        self.stack.enter_context(contextlib.redirect_stderr(self.stderr))

    def factory(self, **kwargs):
        phase = kwargs["phase"]

        def handler(request):
            self.requests.append((phase, json.loads(request.content)))
            if phase == self.fail_phase:
                raise httpx.ConnectError("private-connection-detail", request=request)
            default = (CONCEPT_MARKDOWN if phase == "concept" else {"findings": []}
                       if phase == "concept_verify" else plot_data() if phase == "structure"
                       else {"item": phase.removeprefix("check_"), "issues": []}
                       if phase.startswith("check_") else "本文。" * 210)
            answer = self.answers.get(phase, default)
            if isinstance(answer, BaseException):
                raise answer
            if callable(answer):
                answer = answer()
            if isinstance(answer, httpx.Response):
                return answer
            content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
            return httpx.Response(200, json=completion(content))

        client = OpenAI(base_url="http://fake.invalid/v1", api_key="private-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        return OpenAICompatibleGateway(**kwargs, client=client)

    def stage(self, phase):
        return cli.stage(phase, run_dir=self.directory, config_path=self.config, gateway_factory=self.factory)

    def generate(self):
        return cli.run_pipeline(self.idea, config_path=self.config, output_root=self.creations,
                                gateway_factory=self.factory)

    def tree(self, directory=None):
        directory = directory or self.directory
        return {p.relative_to(directory).as_posix(): history.digest(p.read_bytes())
                for p in directory.rglob("*") if p.is_file()}

    def records(self, directory=None):
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(((directory or self.directory) / history.HISTORY).glob("*/start.json"))]

    def result(self, start, directory=None):
        path = (directory or self.directory) / history.HISTORY / start["operation_id"] / "result.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_missing_null_and_invalid_issues_fail_at_every_item_with_partial_results(self):
        for item in LLM_ITEMS:
            for malformed in ({"item": item}, {"item": item, "issues": None},
                              {"item": item, "issues": {}}, {"item": item, "issues": "none"}):
                with self.subTest(item=item, malformed=malformed):
                    self.answers = {f"check_{item}": malformed}
                    self.requests.clear()
                    before = {key: value for key, value in self.tree().items()
                              if key.startswith(("00", "01", "02", "03", "04", "05", "07"))}
                    with self.assertRaises(CheckFormatError):
                        self.stage("check")
                    folder = self.directory / run.CHECK
                    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                    for earlier in LLM_ITEMS[:LLM_ITEMS.index(item)]:
                        self.assertEqual(metadata["items"][earlier]["status"], "success")
                    state = metadata["items"][item]
                    self.assertEqual((state["status"], state["failure_step"], state["error_code"]),
                                     ("error", "schema_validation", "schema_invalid"))
                    for later in LLM_ITEMS[LLM_ITEMS.index(item) + 1:]:
                        self.assertEqual(metadata["items"][later]["status"], "pending")
                    self.assertEqual(json.loads((folder / f"{item}_raw.txt").read_text(encoding="utf-8")), malformed)
                    log = json.loads((self.directory / run.CALLS).read_text(encoding="utf-8").splitlines()[-1])
                    self.assertEqual(log["call_id"], state["call_id"])
                    self.assertEqual(log["error_code"], "schema_invalid")
                    self.assertEqual(len(self.requests), LLM_ITEMS.index(item) + 1)
                    self.assertEqual(before, {key: value for key, value in self.tree().items() if key in before})

    def test_cli_format_error_exits_nonzero(self):
        self.answers["check_elements"] = {"item": "elements"}
        dispatch = lambda name, **kwargs: stage_function(name, **kwargs, gateway_factory=self.factory)
        with patch("main.stage", side_effect=dispatch):
            self.assertEqual(cli.main(["stage", "check", "--run", str(self.directory), "--config", str(self.config)]), 1)

    def test_quote_failure_has_gateway_success_and_item_error_without_double_counting(self):
        self.answers["check_elements"] = {"item": "elements", "issues": [
            {"scene": 1, "quote": "原文に存在しない", "reason": "テスト"}]}
        with self.assertRaises(CheckFormatError):
            self.stage("check")
        logs = [json.loads(line) for line in (self.directory / run.CALLS).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(logs), 1)
        self.assertEqual((logs[0]["status"], logs[0]["finish_reason"], logs[0]["error_code"]), ("success", "stop", None))
        error = json.loads((self.directory / run.CHECK / "error.json").read_text(encoding="utf-8"))
        self.assertEqual(error["call_id"], logs[0]["call_id"])
        self.assertEqual(error["error_code"], "quote_mismatch")

    def test_gateway_classifies_truncation_empty_choices_and_connection_failure(self):
        choices = completion()
        choices["choices"] = []
        samples = [(completion("途中", finish="length"), "non_stop_finish", "length"),
                   (completion(" \n"), "empty_content", "stop"), (choices, "no_choices", None)]
        for response, code, finish in samples:
            self.answers["check_elements"] = httpx.Response(200, json=response)
            with self.assertRaises(Exception):
                self.stage("check")
            last = json.loads((self.directory / run.CALLS).read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual((last["error_code"], last["finish_reason"]), (code, finish))
        self.fail_phase = "check_elements"
        with self.assertRaises(Exception):
            self.stage("check")
        last = json.loads((self.directory / run.CALLS).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["error_code"], "request_failed")
        self.assertIsNone(last["finish_reason"])
        self.assertIsNone(last["input_tokens"])
        self.assertNotIn("private-connection-detail", json.dumps(last))

    def test_preflight_errors_preserve_all_artifacts_and_existing_archives(self):
        archive = self.directory / run.ARCHIVE / "old"
        archive.mkdir(parents=True)
        (archive / run.DRAFT).write_text("古い草稿", encoding="utf-8")
        for phase in ("concept", "structure", "writing"):
            for mode in ("missing_phase", "thinking", "prompt", "source"):
                saved_config = self.config.read_bytes()
                source = self.directory / (run.INPUT if phase == "concept" else run.CONCEPT if phase == "structure" else run.PLOT)
                saved_source = source.read_bytes()
                module = {"concept": concept, "structure": structure, "writing": writing}[phase]
                with self.subTest(phase=phase, mode=mode), contextlib.ExitStack() as stack:
                    try:
                        data = json.loads(self.config.read_text(encoding="utf-8"))
                        if mode == "missing_phase":
                            del data["local"]["phases"][phase]
                        elif mode == "thinking":
                            data["local"]["phases"][phase]["thinking"] = True
                        elif mode == "prompt":
                            stack.enter_context(patch.object(module, "SYSTEM_PROMPT", self.root / "missing-prompt"))
                        elif mode == "source":
                            source.write_text(" \n" if phase == "concept" else "invalid", encoding="utf-8")
                        self.config.write_text(json.dumps(data), encoding="utf-8")
                        before = self.tree()
                        with self.assertRaises(Exception):
                            self.stage(phase)
                        self.assertEqual(before, self.tree())
                        self.assertEqual(self.requests, [])
                    finally:
                        self.config.write_bytes(saved_config)
                        source.write_bytes(saved_source)

    def test_missing_concept_and_verify_prompt_stop_before_mutation(self):
        path = self.directory / run.CONCEPT
        path.unlink()
        before = self.tree()
        with self.assertRaises(concept.ConceptFormatError):
            self.stage("structure")
        self.assertEqual(before, self.tree())
        with patch.object(concept, "VERIFY_PROMPT", self.root / "missing"):
            with self.assertRaises(OSError):
                self.stage("concept")
        self.assertEqual(before, self.tree())

    def test_new_run_checks_every_prompt_before_creating_any_output(self):
        for module, attribute in ((concept, "SYSTEM_PROMPT"), (concept, "VERIFY_PROMPT"),
                                  (structure, "SYSTEM_PROMPT"), (writing, "SYSTEM_PROMPT")):
            with self.subTest(module=module.__name__, attribute=attribute), patch.object(module, attribute, self.root / "missing"):
                with self.assertRaises(OSError):
                    self.generate()
                self.assertFalse(self.creations.exists())
                self.assertEqual(self.requests, [])

    def test_prepared_input_and_prompts_are_reused_after_archiving(self):
        original_archive = run.archive_downstream
        expected = (self.directory / run.CONCEPT).read_text(encoding="utf-8")
        def archive(*args):
            result = original_archive(*args)
            (self.directory / run.CONCEPT).write_text("changed after preflight", encoding="utf-8")
            return result
        with patch("main.run.archive_downstream", side_effect=archive):
            self.stage("structure")
        self.assertEqual(self.requests[0][1]["messages"][1]["content"], expected)

    def test_empty_events_flow_through_structure_writing_check_without_inventing_specification(self):
        empty = "# 制約\n- 舞台は雪の町\n\n# 出来事\n\n# 構想\n静かな町で少女が過ごす。\n"
        self.answers["concept"] = empty
        directory = self.generate()
        data = json.loads((directory / run.PLOT).read_text(encoding="utf-8"))
        self.assertEqual(data["events"], [])
        self.assertTrue(all(scene["covers"] == [] for scene in data["scenes"]))
        self.assertFalse(any(f.check in ("uncovered", "covers", "order") for f in checks.check_plot(Plot(**data)).findings))
        self.assertIn("出来事リストは空", (directory / run.EVAL).read_text(encoding="utf-8"))
        cli.stage("check", run_dir=directory, config_path=self.config, gateway_factory=self.factory)
        self.assertTrue(run.check_path(directory, "physical").exists())
        data["scenes"][0]["covers"] = [1]
        self.assertTrue(any(f.check == "covers" for f in checks.check_plot(Plot(**data)).findings))

    def test_assemble_preserves_scenes_archives_old_outputs_and_check_uses_new_text(self):
        self.stage("check")
        path = run.scene_path(self.directory, 2)
        path.write_text(path.read_text(encoding="utf-8") + "\n手で直した結末。", encoding="utf-8")
        before = self.tree()
        count = len(self.requests)
        self.config.unlink()
        cli.assemble(self.directory)
        self.assertEqual(len(self.requests), count)
        for name, fingerprint in before.items():
            if name.startswith(("00", "01", "02", "03", "04")):
                self.assertEqual(history.digest((self.directory / name).read_bytes()), fingerprint)
        archive = next((self.directory / run.ARCHIVE).iterdir())
        for name in (run.DRAFT, run.CHECK_REPORT, run.EVAL):
            self.assertEqual(history.digest((archive / name).read_bytes()), before[name])
        self.assertIn("未評価", (self.directory / run.EVAL).read_text(encoding="utf-8"))
        self.assertFalse((self.directory / run.CHECK).exists())
        self.config.write_bytes((PROJECT_ROOT / "config/backends.example.json").read_bytes())
        self.stage("check")
        self.assertIn("手で直した結末", self.requests[count][1]["messages"][1]["content"])
        cli.assemble(self.directory)
        self.assertEqual(len(list((self.directory / run.ARCHIVE).iterdir())), 2)

    def test_assemble_rejects_invalid_inputs_before_history_or_archive(self):
        for mode in ("plot", "missing", "extra", "empty", "number", "input"):
            with self.subTest(mode=mode):
                target = self.directory / (run.PLOT if mode == "plot" else run.INPUT if mode == "input" else f"{run.SCENES}/scene_02.md")
                old = target.read_bytes()
                extra = None
                try:
                    if mode == "missing":
                        target.unlink()
                    elif mode in ("extra", "number"):
                        extra = self.directory / run.SCENES / ("scene_03.md" if mode == "extra" else "scene_bad.md")
                        extra.write_text("余分", encoding="utf-8")
                    else:
                        target.write_text("{}" if mode == "plot" else " \n", encoding="utf-8")
                    before = self.tree()
                    with self.assertRaises(Exception):
                        cli.assemble(self.directory)
                    self.assertEqual(before, self.tree())
                finally:
                    target.write_bytes(old)
                    if extra:
                        extra.unlink()

    def test_assemble_save_failure_reports_archive_and_preserves_finished_file(self):
        original = run.atomic_write
        def fail(path, text):
            if path.name == run.EVAL:
                raise OSError("private-filesystem-detail")
            original(path, text)
        with patch("main.run.atomic_write", side_effect=fail), self.assertRaises(run.RunError) as caught:
            cli.assemble(self.directory)
        self.assertIn(run.DRAFT, str(caught.exception))
        self.assertNotIn("private-filesystem-detail", str(caught.exception))
        start, = self.records()
        result = self.result(start)
        self.assertEqual(result["status"], "error")
        self.assertEqual(list(result["outputs"]), [run.DRAFT])
        self.assertTrue((self.directory / result["archive"] / run.EVAL).exists())

    def test_history_tracks_mixed_settings_resume_external_edit_and_legacy_snapshot(self):
        initial = (self.directory / run.CONFIG_SNAPSHOT).read_bytes()
        for phase, model in (("concept", "A"), ("structure", "B"), ("writing", "C")):
            config = json.loads(self.config.read_text(encoding="utf-8"))
            config["local"]["phases"][phase]["model"] = model
            self.config.write_text(json.dumps(config), encoding="utf-8")
            if phase == "writing":
                run.scene_path(self.directory, 1).parent.mkdir(exist_ok=True)
                run.scene_path(self.directory, 1).write_text("手編集した前シーン\r\n", encoding="utf-8")
                cli.write(self.directory, first=2, config_path=self.config, gateway_factory=self.factory)
            else:
                self.stage(phase)
        self.assertEqual(initial, (self.directory / run.CONFIG_SNAPSHOT).read_bytes())
        records = self.records()
        self.assertEqual(len({r["operation_id"] for r in records}), 3)
        by_name = {r["operation"]: r for r in records}
        self.assertEqual(by_name["stage concept"]["config"]["phases"]["concept"]["model"], "A")
        self.assertEqual(by_name["stage structure"]["config"]["phases"]["structure"]["model"], "B")
        write = by_name["write"]
        self.assertEqual(write["config"]["phases"]["writing"]["model"], "C")
        self.assertEqual(write["input_provenance"]["04_scenes/scene_01.md"]["status"], "external_or_unknown")
        self.assertEqual(write["input_provenance"][run.PLOT]["operation_id"], by_name["stage structure"]["operation_id"])
        result = self.result(write)
        self.assertIn("04_scenes/scene_02.md", result["outputs"])
        self.assertNotIn("04_scenes/scene_01.md", result["outputs"])
        migrations = list((self.directory / history.HISTORY).glob("*/migration.json"))
        self.assertEqual(len(migrations), 1)
        migration = json.loads(migrations[0].read_text(encoding="utf-8"))
        self.assertFalse(migration["initial_config_is_known"])
        self.assertEqual(migration["files"][run.CONFIG_SNAPSHOT], history.digest(initial))

    def test_partial_failure_and_normal_interrupt_have_results_and_generated_outputs(self):
        def interrupt():
            raise KeyboardInterrupt()
        for failure in ("network", "interrupt"):
            self.fail_phase = "writing" if failure == "network" else None
            self.answers = {"writing": interrupt} if failure == "interrupt" else {}
            with self.subTest(failure=failure), self.assertRaises(BaseException):
                self.generate()
        for directory in self.creations.iterdir():
            start, = self.records(directory)
            result = self.result(start, directory)
            self.assertIn(result["status"], ("error", "interrupted"))
            self.assertIn(run.PLOT, result["outputs"])
            self.assertNotIn(run.DRAFT, result["outputs"])

    def test_writing_failure_records_only_completed_scenes(self):
        calls = 0
        def response():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("private-generation-failure")
            return "保存できた前シーン。"
        self.answers["writing"] = response
        with self.assertRaises(RuntimeError):
            cli.write(self.directory, config_path=self.config, gateway_factory=self.factory)
        start, = self.records()
        result = self.result(start)
        self.assertEqual(result["failure_step"], "writing_scene_02")
        self.assertIn("04_scenes/scene_01.md", result["outputs"])
        self.assertNotIn("04_scenes/scene_02.md", result["outputs"])
        self.assertNotIn(run.DRAFT, result["outputs"])

    def test_missing_result_is_completion_unconfirmed_and_history_is_not_overwritten(self):
        self.stage("structure")
        first, = self.records()
        folder = self.directory / history.HISTORY / first["operation_id"]
        start_bytes = (folder / "start.json").read_bytes()
        (folder / "result.json").unlink()
        self.assertEqual(history.operation_statuses(self.directory)[0]["status"], "completion_unconfirmed")
        self.stage("structure")
        self.assertEqual((folder / "start.json").read_bytes(), start_bytes)
        self.assertEqual(len(self.records()), 2)

    def test_new_evaluation_uses_final_criteria_and_never_overwrites_a_saved_review(self):
        before = (self.directory / run.EVAL).read_bytes()
        with self.assertRaises(FileExistsError):
            evaluation.save_template(self.directory)
        self.assertEqual(before, (self.directory / run.EVAL).read_bytes())
        template = evaluation.render_template(Plot(**{**plot_data(), "constraints": [], "events": []}))
        self.assertIn("D51", template)
        self.assertIn("| 合否 |", template)
        self.assertNotIn("合否案", template)
        self.assertIn("制約リストは空", template)
        self.assertIn("操作履歴", template)

    def test_start_save_failure_never_archives_or_calls(self):
        before = self.tree()
        original = history.save_json
        def fail(path, data):
            if path.name == "start.json":
                raise OSError("cannot persist start")
            original(path, data)
        with patch("novel.history.save_json", side_effect=fail), self.assertRaises(OSError):
            self.stage("structure")
        after = self.tree()
        self.assertEqual(before, {key: after[key] for key in before})
        self.assertFalse((self.directory / run.ARCHIVE).exists())
        self.assertEqual(self.requests, [])

    def test_history_never_persists_keys_url_credentials_or_arbitrary_thinking_body(self):
        data = json.loads(self.config.read_text(encoding="utf-8"))
        data["local"]["base_url"] = "http://private-user:private-password@localhost:1234/v1?api_key=private-query#private-fragment"
        data["local"]["api_key"] = "private-config-key"
        data["local"]["phases"]["concept"]["thinking"] = True
        model = data["local"]["phases"]["concept"]["model"]
        self.config.write_text(json.dumps(data), encoding="utf-8")
        options = self.root / "thinking.json"
        options.write_text(json.dumps({model: {"on": {"private_field": "private-body"}}}), encoding="utf-8")
        cli.stage("concept", input_path=self.idea, output_root=self.creations, config_path=self.config,
                  thinking_options=options, gateway_factory=self.factory)
        output, = self.creations.iterdir()
        raw = "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))
        raw += (output / run.CALLS).read_text(encoding="utf-8")
        for secret in ("private-user", "private-password", "private-query", "private-fragment", "private-config-key", "private_field", "private-body", "private-key"):
            self.assertNotIn(secret, raw)

    def test_cli_assemble_requires_no_config_and_documents_evaluation_reset(self):
        with patch("main.load_backend", side_effect=AssertionError("assemble must not load backend config")):
            self.assertEqual(cli.main(["assemble", "--run", str(self.directory)]), 0)
        with self.assertRaises(SystemExit):
            cli.main(["assemble", "--help"])
        self.assertIn("未評価", self.stdout.getvalue())


# CLIのディスパッチだけ差し替えるテストで利用する。
stage_function = cli.stage
