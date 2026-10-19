"""モデル切り替え(D39)。実 API と lms は使わない。"""

import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from openai.types.chat import ChatCompletion

from test.test_m1 import completion
from util.gateway import OpenAICompatibleGateway
from util.models import ModelSwitchError, prepare_local_model


def model(key, *ids, kind="llm"):
    return {"key": key, "type": kind, "loaded_instances": [{"id": item} for item in ids]}


class ModelSwitchTest(unittest.TestCase):
    def prepare(self, *snapshots, target="gemma"):
        responses = [Mock(json=Mock(return_value={"models": models})) for models in snapshots]
        with patch("util.models.httpx.Client") as client, patch("util.models.subprocess.run") as command:
            client.return_value.__enter__.return_value.get.side_effect = responses
            prepare_local_model("http://localhost:1234/v1", "private-key", target)
            return command.call_args_list

    def test_actual_loaded_instances_are_unloaded_even_across_processes(self):
        calls = self.prepare([model("qwen", "qwen-instance"), model("gemma", "gemma-instance")],
                             [model("qwen"), model("gemma", "gemma-instance")])
        self.assertEqual(calls[0].args[0], ["lms", "unload", "qwen-instance"])
        self.assertEqual(len(calls), 1)

    def test_same_model_or_instance_alias_is_retained_and_embeddings_are_untouched(self):
        self.assertEqual(self.prepare([model("gemma", "alias"), model("embedding", "embed", kind="embedding")]), [])
        self.assertEqual(self.prepare([model("gemma", "alias")], target="alias"), [])
        self.assertEqual(self.prepare([]), [])

    def test_multiple_previous_instances_are_all_unloaded(self):
        calls = self.prepare([model("qwen", "one", "two")], [])
        self.assertEqual([call.args[0][-1] for call in calls], ["one", "two"])

    def test_unload_failures_stop_without_exposing_command_output(self):
        response = Mock(json=Mock(return_value={"models": [model("qwen", "old")]}))
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("lms", 120),
                      subprocess.CalledProcessError(1, "lms", output="private-output")):
            with patch("util.models.httpx.Client") as client, patch("util.models.subprocess.run", side_effect=error):
                client.return_value.__enter__.return_value.get.return_value = response
                with self.assertRaises(ModelSwitchError) as caught:
                    prepare_local_model("http://localhost:1234/v1", "private-key", "gemma")
                self.assertNotIn("private", str(caught.exception))

    def test_still_loaded_previous_model_stops(self):
        with self.assertRaises(ModelSwitchError):
            self.prepare([model("qwen", "old")], [model("qwen", "old")])

    def test_unreadable_snapshot_or_nonlocal_backend_stops(self):
        for payload in ({}, {"models": None}, {"models": [{"type": "llm"}]}):
            with patch("util.models.httpx.Client") as client:
                client.return_value.__enter__.return_value.get.return_value.json.return_value = payload
                with self.assertRaises(ModelSwitchError):
                    prepare_local_model("http://localhost:1234/v1", "private-key", "gemma")
        with patch("util.models.httpx.Client") as client, self.assertRaises(ModelSwitchError):
            prepare_local_model("https://example.com/v1", "private-key", "gemma")
        client.assert_not_called()


class GatewaySwitchTest(unittest.TestCase):
    def test_default_local_client_prepares_before_generation_once_per_gateway(self):
        events = []
        client = Mock()
        client.chat.completions.create.side_effect = lambda **kwargs: (
            events.append("generate") or ChatCompletion.model_validate(completion()))
        with tempfile.TemporaryDirectory() as temp, patch("openai.OpenAI", return_value=client), \
                patch("util.gateway.prepare_local_model", side_effect=lambda *args: events.append("prepare")):
            with OpenAICompatibleGateway(model="gemma", base_url="http://localhost:1234/v1", api_key="private-key",
                                         log_path=Path(temp) / "calls.jsonl", phase="writing") as gateway:
                gateway.text([])
                gateway.text([])
        self.assertEqual(events, ["prepare", "generate", "generate"])

    def test_preparation_failure_is_logged_and_never_calls_generation(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as temp, patch("openai.OpenAI", return_value=client), \
                patch("util.gateway.prepare_local_model", side_effect=ModelSwitchError("Cannot unload")):
            path = Path(temp) / "calls.jsonl"
            with OpenAICompatibleGateway(model="gemma", base_url="http://localhost:1234/v1", api_key="private-key",
                                         log_path=path, phase="writing") as gateway:
                with self.assertRaises(ModelSwitchError):
                    gateway.text([])
            client.chat.completions.create.assert_not_called()
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["error_type"], "ModelSwitchError")
            self.assertIsNone(record["input_tokens"])

    def test_remote_client_does_not_use_lms(self):
        client = Mock()
        client.chat.completions.create.return_value = ChatCompletion.model_validate(completion())
        with tempfile.TemporaryDirectory() as temp, patch("openai.OpenAI", return_value=client), \
                patch("util.gateway.prepare_local_model") as prepare:
            with OpenAICompatibleGateway(model="gemma", base_url="https://remote.invalid/v1", api_key="private-key",
                                         log_path=Path(temp) / "calls.jsonl", phase="writing", backend="remote") as gateway:
                gateway.text([])
            prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
