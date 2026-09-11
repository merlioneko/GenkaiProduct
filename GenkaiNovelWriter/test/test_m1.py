"""Offline tests: real OpenAI SDK with an in-memory HTTP transport, no API keys."""

import builtins
import contextlib
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openai import OpenAI
import httpx as sdk_http
from pydantic import ValidationError

from main import baseline, main
from test import verify_backend
from test.plot_schema import Plot
from test.verify_backend import run_probes
from util.config import ConfigError, PROJECT_ROOT, load_backend, load_thinking_options, thinking_body
from util.gateway import GenerationError, OpenAICompatibleGateway, create_message


def plot_data():
    return {
        "meta": {"genre": "ラブコメ", "tone": "軽快", "style": "三人称", "pov": "少女"},
        "specified_elements": [{"id": "S1", "text": "少女と魔人"}],
        "characters": [{"name": "少女", "persona": "強気", "appearance": "制服",
                        "speech_examples": ["行くよ"], "notes": ""}],
        "settings": [{"name": "家", "kind": "place", "notes": "少女の家"}],
        "scenes": [{"name": "出会い", "opening": {"place": "家", "time_of_day": "朝", "weather": "晴れ"},
                    "beats": ["少女が家で魔人に出会う"], "covers": ["S1"], "target_chars": 1000}],
    }


def completion(content="小説本文。", *, finish="stop", usage=True, reasoning=None):
    result = {"id": "fake-id", "object": "chat.completion", "created": 1, "model": "test-model",
              "choices": [{"index": 0, "finish_reason": finish,
                           "message": {"role": "assistant", "content": content}}]}
    if usage:
        result["usage"] = {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}
    if reasoning:
        result["choices"][0]["message"]["reasoning_content"] = reasoning
    return result


class M1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_path = self.root / "backends.json"
        self.config_data = json.loads((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"))
        self.save_config()
        self.config = load_backend(self.config_path)
        self.options = {phase.model: {"on": {"test_thinking": True}, "off": {"test_thinking": False}}
                        for phase in self.config.phases.values()}
        self.options_path = self.root / "thinking.json"
        self.options_path.write_text(json.dumps(self.options), encoding="utf-8")
        self.input = self.root / "idea.txt"
        self.input.write_text("少女と魔人の話。", encoding="utf-8")
        self.requests = []

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config_data), encoding="utf-8")

    def factory(self, responder):
        def handler(request):
            self.requests.append(json.loads(request.content))
            return responder(request)
        def factory(**kwargs):
            client = OpenAI(base_url="http://fake.invalid/v1", api_key="test-only-secret", max_retries=0,
                            http_client=sdk_http.Client(transport=sdk_http.MockTransport(handler)))
            return OpenAICompatibleGateway(**kwargs, client=client)
        return factory

    def gateway(self, responder):
        return self.factory(responder)(model="test-model", base_url="http://fake.invalid/v1", api_key="test-only-secret",
                                       phase="writing", log_path=self.root / "calls.jsonl")

    def logs(self, path=None):
        return [json.loads(line) for line in (path or self.root / "calls.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_local_config_does_not_require_remote_key(self):
        self.assertEqual(self.config.phase("baseline"), self.config.phase("writing"))
        self.assertNotIn("lm-studio", repr(self.config))
        with self.assertRaises(ConfigError):
            load_backend(self.config_path, "remote")

    def test_config_parse_errors_do_not_leak_private_values(self):
        self.config_data["local"]["context_length"] = "private-secret"
        self.save_config()
        with self.assertRaises(ConfigError) as result:
            load_backend(self.config_path)
        self.assertNotIn("private-secret", str(result.exception))
        self.config_path.write_text('{"api_key":"private-secret",', encoding="utf-8")
        with self.assertRaises(ConfigError) as result:
            load_backend(self.config_path)
        self.assertNotIn("private-secret", str(result.exception))

    def test_phase_thinking_is_strict_and_baseline_must_match_writing(self):
        self.config_data["local"]["phases"]["writing"]["thinking"] = "false"
        self.save_config()
        with self.assertRaises(ConfigError):
            load_backend(self.config_path)
        self.config_data["local"]["phases"]["writing"]["thinking"] = True
        self.save_config()
        with self.assertRaises(ConfigError):
            load_backend(self.config_path).phase("baseline")

    def test_thinking_requires_explicit_body_and_rejects_output_overrides(self):
        phase = self.config.phase("baseline")
        for options in ({}, {phase.model: {"off": {}}}, {phase.model: {"off": {"model": "other"}}}):
            with self.assertRaises(ConfigError):
                thinking_body(options, phase)
        self.assertEqual(thinking_body(load_thinking_options(self.options_path), phase), {"test_thinking": False})

    def test_baseline_writes_utf8_input_and_body_four_distinct_times(self):
        factory = self.factory(lambda request: sdk_http.Response(200, json=completion()))
        outputs = [baseline(self.input, config_path=self.config_path, thinking_options=self.options_path,
                            output_root=self.root / "outputs", gateway_factory=factory) for _ in range(4)]
        self.assertEqual(len(set(outputs)), 4)
        for output in outputs:
            self.assertEqual((output / "00_input.txt").read_text(encoding="utf-8"), "少女と魔人の話。")
            self.assertEqual((output / "baseline.md").read_text(encoding="utf-8"), "小説本文。")
            log = self.logs(output / "calls.jsonl")[0]
            self.assertEqual((log["phase"], log["thinking"], log["input_tokens"], log["output_tokens"]),
                             ("baseline", False, 123, 45))
            self.assertGreater(log["duration_seconds"], 0)
            self.assertNotIn("test-only-secret", (output / "calls.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(len(self.requests), 4)  # No implicit connection-test calls.
        self.assertFalse(self.requests[0]["test_thinking"])
        self.assertEqual(self.requests[0]["model"], self.config.phase("writing").model)

    def test_baseline_stops_before_api_when_input_or_thinking_invalid(self):
        with self.assertRaises(ConfigError):
            baseline(self.input, config_path=self.config_path, output_root=self.root / "outputs")
        self.input.write_text("  \n", encoding="utf-8")
        with self.assertRaises(ValueError):
            baseline(self.input, config_path=self.config_path, output_root=self.root / "outputs")
        self.assertFalse((self.root / "outputs").exists())

    def test_failed_baseline_preserves_input_without_publishing_partial_draft(self):
        factory = self.factory(lambda request: sdk_http.Response(200, json=completion("途中", finish="length")))
        with self.assertRaises(GenerationError):
            baseline(self.input, config_path=self.config_path, thinking_options=self.options_path,
                     output_root=self.root / "outputs", gateway_factory=factory)
        output = next((self.root / "outputs").iterdir())
        self.assertTrue((output / "00_input.txt").is_file())
        self.assertFalse((output / "baseline.md").exists())
        self.assertEqual(self.logs(output / "calls.jsonl")[0]["status"], "error")

    def test_empty_and_truncated_responses_are_logged_as_errors(self):
        for content, finish in (("", "stop"), (None, "stop"), ("途中", "length")):
            with self.gateway(lambda request: sdk_http.Response(200, json=completion(content, finish=finish))) as gateway:
                with self.assertRaises(GenerationError):
                    gateway.text(create_message(user="入力"))
        self.assertEqual(len(self.logs()), 3)
        self.assertTrue(all(log["error_type"] == "GenerationError" for log in self.logs()))

    def test_connection_failure_logs_unknown_usage_without_retries(self):
        def responder(request):
            raise sdk_http.ConnectError("private-secret", request=request)
        with self.gateway(responder) as gateway:
            with self.assertRaises(Exception):
                gateway.text(create_message(user="入力"))
        self.assertEqual(len(self.requests), 1)
        log = self.logs()[0]
        self.assertIsNone(log["input_tokens"])
        self.assertEqual(log["status"], "error")
        self.assertNotIn("private-secret", json.dumps(log))

    def test_api_error_usage_is_preserved_without_logging_error_text(self):
        body = {"error": {"message": "private-secret", "type": "exceed_context_size_error"},
                "usage": {"prompt_tokens": 17000, "completion_tokens": 0, "total_tokens": 17000}}
        with self.gateway(lambda request: sdk_http.Response(400, json=body)) as gateway:
            with self.assertRaises(Exception):
                gateway.text(create_message(user="入力"))
        log = self.logs()[0]
        self.assertEqual(log["input_tokens"], 17000)
        self.assertNotIn("private-secret", json.dumps(log))

    def test_missing_usage_is_null_not_zero(self):
        with self.gateway(lambda request: sdk_http.Response(200, json=completion(usage=False))) as gateway:
            gateway.text(create_message())
        self.assertIsNone(self.logs()[0]["output_tokens"])
        self.assertIsNone(self.logs()[0]["output_tokens_per_second_end_to_end"])

    def test_structured_response_uses_actual_spec_schema_and_validates(self):
        with self.gateway(lambda request: sdk_http.Response(200, json=completion(json.dumps(plot_data())))) as gateway:
            plot = gateway.chat_formated(create_message(), Plot)
        self.assertEqual(plot.scenes[0].opening.place, "家")
        self.assertFalse(self.requests[0]["response_format"]["json_schema"]["schema"]["additionalProperties"])
        with self.gateway(lambda request: sdk_http.Response(200, json=completion('{"Scenes": []}'))) as gateway:
            with self.assertRaises(ValidationError):
                gateway.chat_formated(create_message(), Plot)
        self.assertEqual(self.logs()[-1]["status"], "error")

    def test_spec_schema_rejects_extra_fields_and_empty_required_lists(self):
        for key in ("characters", "settings", "scenes"):
            data = plot_data()
            data[key] = []
            with self.assertRaises(ValidationError):
                Plot.model_validate(data)
        for key in ("beats",):
            data = plot_data()
            data["scenes"][0][key] = []
            with self.assertRaises(ValidationError):
                Plot.model_validate(data)
        data = plot_data()
        data["meta"]["unexpected"] = "value"
        with self.assertRaises(ValidationError):
            Plot.model_validate(data)
        data = plot_data()
        data["scenes"][0]["target_chars"] = "1000"
        with self.assertRaises(ValidationError):
            Plot.model_validate_json(json.dumps(data))

    def test_probe_suite_records_observations_and_ten_schema_attempts(self):
        schema_count = 0
        def responder(request):
            nonlocal schema_count
            body = json.loads(request.content)
            if "response_format" in body:
                schema_count += 1
                if schema_count == 1:
                    return sdk_http.Response(503, json={"error": {"message": "not available"}})
                content = '{"Scenes": []}' if schema_count == 2 else json.dumps(plot_data())
            else:
                content = "結果は2/5です。"
            return sdk_http.Response(200, json=completion(content, reasoning="模擬思考" if body.get("test_thinking") else None))
        output = self.root / "verify"
        report = run_probes(self.config, self.options, output, "入力", ["thinking", "schema", "switching", "speed"],
                            gateway_factory=self.factory(responder),
                            snapshot=lambda config: {"status": "observed", "models": []},
                            memory=lambda: {"status": "unavailable"})
        self.assertEqual(report["U3"], {"status": "measured", "attempts": 10, "valid": 8, "schema_violations": 1, "api_errors": 1})
        self.assertEqual(report["U2"]["status"], "needs_review")
        self.assertTrue(report["U2"]["observations"][0]["has_separate_reasoning"])
        self.assertFalse(report["U2"]["observations"][1]["has_separate_reasoning"])
        self.assertEqual([item["model"] for item in report["U4"]["observations"]],
                         [self.config.phase(role).model for role in ("structure", "writing", "structure")])
        self.assertEqual(len(self.logs(output / "calls.jsonl")), 19)
        self.assertEqual(json.loads((output / "schema-02.json").read_text(encoding="utf-8"))["content"], '{"Scenes": []}')
        self.assertFalse(report["quality_evaluated"])

    def test_probe_without_thinking_options_does_not_claim_success(self):
        report = run_probes(self.config, {}, self.root / "verify", "入力", ["thinking"],
                            gateway_factory=lambda **kwargs: self.fail("Must not call API"))
        self.assertTrue(all(item["status"] == "not_run" for item in report["U2"]["observations"]))

    def test_baseline_suite_cli_runs_each_fixture_twice_and_records_failures(self):
        inputs = self.root / "prompts/tests"
        inputs.mkdir(parents=True)
        for name, text in (("concrete_01.txt", "具体入力"), ("vague_01.txt", "曖昧入力")):
            (inputs / name).write_text(text, encoding="utf-8")
        report = {"U2": {"observations": []}, "U3": {"api_errors": 0, "schema_violations": 0},
                  "U4": {"observations": []}, "U7": {"measurements": []}}
        count = 0
        def responder(request):
            nonlocal count
            count += 1
            if count == 2:
                return sdk_http.Response(500, json={"error": {"message": "private-secret"}})
            return sdk_http.Response(200, json=completion())
        factory = self.factory(responder)
        def generate(path, **kwargs):
            return baseline(path, output_root=self.root / "baselines", gateway_factory=factory, **kwargs)
        with patch.object(verify_backend, "PROJECT_ROOT", self.root), \
             patch.object(verify_backend, "run_probes", return_value=report), \
             patch.object(verify_backend, "baseline", side_effect=generate), \
             contextlib.redirect_stdout(io.StringIO()):
            code = verify_backend.main(["--config", str(self.config_path), "--input", str(self.input),
                                        "--thinking-options", str(self.options_path), "--baseline-suite"])
        self.assertEqual(code, 1)
        self.assertEqual([body["messages"][-1]["content"] for body in self.requests],
                         ["具体入力", "具体入力", "曖昧入力", "曖昧入力"])
        self.assertEqual([item["status"] for item in report["baselines"]],
                         ["generated", "error", "generated", "generated"])
        saved = next((self.root / "creations").glob("verify-*/verification.json"))
        self.assertNotIn("private-secret", saved.read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.root / "baselines").glob("*/baseline.md"))), 3)

    def test_history_is_not_mutated_or_shared(self):
        history = [{"role": "assistant", "content": "前文"}]
        result = create_message(history=history)
        result.append({"role": "user", "content": "別の文"})
        self.assertEqual(len(history), 1)
        self.assertEqual(len(create_message()), 2)

    def test_cli_help_and_import_do_not_load_tavily_or_read_secrets(self):
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name in ("util.tools", "util.settings", "tavily"):
                raise AssertionError("M1 must not import legacy secret/search modules")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded), patch("builtins.input", side_effect=AssertionError):
            runpy.run_path(str(PROJECT_ROOT / "main.py"), run_name="import_test")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                main(["--help"])
        self.assertEqual(result.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
