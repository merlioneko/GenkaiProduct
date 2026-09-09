import os
import unittest
from unittest.mock import patch

from util.gateway import OpenRouterGateWay
from util.settings import ModelConfig, get_openrouter_base_url, get_required_secret
from util.tools import Tavily


class SettingsTest(unittest.TestCase):
    def test_model_config_uses_public_default_config(self):
        config = ModelConfig()

        self.assertTrue(config.get_writer())
        self.assertTrue(config.get_editor())
        self.assertEqual(config.config_file.name, "models.json")
        self.assertEqual(config.config_file.parent.name, "config")

    def test_missing_secret_has_actionable_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError, "Copy .env.example to .env"
            ):
                get_required_secret("OPENROUTER_API_KEY")

    def test_secret_is_read_from_environment(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-value"}, clear=True):
            self.assertEqual(get_required_secret("TAVILY_API_KEY"), "test-value")

    def test_openrouter_base_url_has_default_and_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_openrouter_base_url(), "https://openrouter.ai/api/v1"
            )

        with patch.dict(
            os.environ,
            {"OPENROUTER_BASE_URL": "https://example.invalid/v1"},
            clear=True,
        ):
            self.assertEqual(
                get_openrouter_base_url(), "https://example.invalid/v1"
            )

    def test_openrouter_uses_environment_key(self):
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "openrouter-test-key"},
            clear=True,
        ), patch("util.gateway.OpenAI") as openai:
            OpenRouterGateWay("test-model").connect()

        openai.assert_called_once_with(
            base_url="https://openrouter.ai/api/v1",
            api_key="openrouter-test-key",
        )

    def test_tavily_uses_environment_key(self):
        with patch.dict(
            os.environ,
            {"TAVILY_API_KEY": "tavily-test-key"},
            clear=True,
        ), patch("util.tools.TavilyClient") as tavily_client:
            Tavily()

        tavily_client.assert_called_once_with(api_key="tavily-test-key")


if __name__ == "__main__":
    unittest.main()
