import importlib
import runpy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from main import run_pipeline
from novel.engine import writing, elaboration, inspect_border
from novel.novel import (NovelScene, SceneWritingResult, WritingResult,
                         BorderCheckInput, BorderCheckReport)
from novel.plot import Plot
from util.file import output_model, read_model
from util.settings import ModelSettings


def sample_plot():
    return Plot.model_validate({
        "Characters": [{"name": "主人公", "persona": "勇敢", "speech_examples": ["行こう"], "notes": ""}],
        "Settings": [{"name": "町", "kind": "place", "notes": ""}],
        "Scenes": [{"name": "同名", "summary": str(i)} for i in range(3)],
    })


class PipelineTest(unittest.TestCase):
    def test_roundtrip_and_rendering(self):
        result = writing(None, sample_plot(), generate=Mock(return_value="本文。\n日本語"), prompt="test")
        with tempfile.TemporaryDirectory() as folder:
            output_model(folder, "novel.json", result)
            self.assertEqual(read_model(Path(folder) / "novel.json", WritingResult), result)
            output_model(folder, "plot.json", sample_plot())
            self.assertEqual(read_model(Path(folder) / "plot.json", Plot), sample_plot())
        self.assertTrue(result.complete)
        self.assertIn("Scene Title: 同名\nContent: 本文。", str(result.results[0].scene))

    def test_partial_failure_retains_order_and_original_adjacency(self):
        callback = Mock()
        result = writing(None, sample_plot(), prompt="test", on_scene=callback,
                         generate=Mock(side_effect=["文章。", RuntimeError("offline"), "「続き」"]))
        self.assertEqual([r.scene_index for r in result.results], [0, 1, 2])
        self.assertEqual([r.status for r in result.results], ["success", "failed", "success"])
        self.assertEqual(result.results[1].error.type, "RuntimeError")
        self.assertFalse(result.complete)
        self.assertEqual(callback.call_count, 3)
        report = elaboration(result)
        self.assertEqual([r.status for r in report.checks], ["not_checked", "not_checked"])
        self.assertEqual([(r.input.before_index, r.input.after_index) for r in report.checks], [(0, 1), (1, 2)])

    def test_empty_and_missing_responses_are_failures(self):
        result = writing(None, sample_plot(), prompt="test", generate=Mock(side_effect=[None, "", "  "]))
        self.assertTrue(all(r.status == "failed" for r in result.results))
        self.assertFalse(result.complete)

    def test_invalid_result_combinations(self):
        for data in [dict(status="success"), dict(status="failed"),
                     dict(status="failed", scene=NovelScene(title="a", content="b"))]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                SceneWritingResult(scene_index=0, title="a", **data)
        with self.assertRaises(ValidationError):
            WritingResult(results=[])
        item = SceneWritingResult(scene_index=1, title="a", status="success",
                                  scene=NovelScene(title="a", content="b"))
        with self.assertRaises(ValidationError):
            WritingResult(results=[item])

    def test_storage_failure_is_not_generation_failure(self):
        generate = Mock(return_value="本文")
        with self.assertRaises(OSError):
            writing(None, sample_plot(), prompt="test", generate=generate,
                    on_scene=Mock(side_effect=OSError("disk")))
        self.assertEqual(generate.call_count, 1)

    def test_border_reasons_and_empty_input(self):
        for tail, head, status, count in [("本文。", "「続き", "passed", 0),
                ("本文", "続き", "failed", 2), ("", "続き", "not_checked", 1)]:
            with self.subTest(status=status):
                result = inspect_border(BorderCheckInput(before_index=0, after_index=1,
                    tail=tail, head=head, budget=1000, window=1.5))
                self.assertEqual(result.status, status)
                self.assertEqual(len(result.reasons), count)

    def test_saved_stage_execution_and_logs_without_api(self):
        with tempfile.TemporaryDirectory() as folder, patch("main.connect_openrouter") as connect:
            root = Path(folder)
            output_model(root, "plot.json", sample_plot())
            result, output = run_pipeline(stage="writing", source=root / "plot.json",
                directory=root / "writing", client=object(), prompt="test",
                generate=Mock(side_effect=["文章。", RuntimeError("offline"), "続き。 "]))
            self.assertEqual(len(list((output / "scenes").glob("*.json"))), 3)
            self.assertIn("未生成", (output / "04_novel.txt").read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(next(e for e in events if e["stage"] == "writing")["status"], "partial")
            restored, checked = run_pipeline(stage="borders", source=output / "04_novel.json",
                                             directory=root / "borders")
            self.assertEqual(restored, result)
            self.assertEqual(len(read_model(checked / "05_borders.json", BorderCheckReport).checks), 2)
            connect.assert_not_called()

    def test_imports_do_not_run_pipeline(self):
        with patch("util.gateway.connect_openrouter", side_effect=AssertionError("network")), \
             patch("builtins.input", side_effect=AssertionError("input")):
            importlib.reload(importlib.import_module("main"))
            for name in ["test.py", "test_extract.py"]:
                runpy.run_path(str(Path(__file__).parent / name), run_name="import_check")

    def test_settings_validation(self):
        with self.assertRaises(ValidationError):
            ModelSettings(writer=" ", editor="model")
        with self.assertRaises(ValidationError):
            ModelSettings(writer="model")

    def test_full_pipeline_with_fake_gateway(self):
        gateway = Mock()
        gateway.chat_response.return_value.choices = [Mock(message=Mock(content="具体化された構想"))]
        gateway.chat_formated.return_value = sample_plot()
        with tempfile.TemporaryDirectory() as folder, patch("main.read_file", return_value="アイデア"), \
             patch("main.connect_openrouter", side_effect=AssertionError("network")):
            result, output = run_pipeline(directory=folder, client=gateway,
                                          generate=Mock(return_value="本文。"), prompt="test")
            self.assertTrue(result.complete)
            self.assertEqual(read_model(output / "03_plot.json", Plot), sample_plot())
            self.assertEqual(read_model(output / "04_novel.json", WritingResult), result)
            self.assertTrue((output / "01_model_config.json").exists())

    def test_all_failed_and_load_error_are_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output_model(root, "plot.json", sample_plot())
            result, output = run_pipeline(stage="writing", source=root / "plot.json",
                directory=root / "failed", client=object(), prompt="test",
                generate=Mock(side_effect=RuntimeError("offline")))
            self.assertFalse(result.complete)
            events = [json.loads(line) for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(next(e for e in events if e["stage"] == "writing")["status"], "failed")
            with self.assertRaises(FileNotFoundError):
                run_pipeline(stage="borders", source=root / "missing.json", directory=root / "load-error")
            event = json.loads((root / "load-error" / "events.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(event["error_type"], "FileNotFoundError")
            self.assertEqual(event["status"], "failed")


if __name__ == "__main__":
    unittest.main()
