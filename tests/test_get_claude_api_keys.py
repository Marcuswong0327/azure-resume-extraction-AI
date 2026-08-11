"""Failing tests for collecting up to three Claude Sonnet 4 API keys from config."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import get_claude_api_keys


class TestGetClaudeApiKeys(unittest.TestCase):
    def test_returns_ordered_nonempty_keys(self):
        env = {
            "CLAUDE_SONNET_4_API_KEY": "primary",
            "CLAUDE_SONNET_4_API_KEY_2": "fallback2",
            "CLAUDE_SONNET_4_API_KEY_3": "fallback3",
        }
        with patch.dict(os.environ, env, clear=False):
            for k in env:
                os.environ[k] = env[k]
            keys = get_claude_api_keys()
        self.assertEqual(keys, ["primary", "fallback2", "fallback3"])

    def test_skips_missing_fallback_keys(self):
        with patch.dict(os.environ, {"CLAUDE_SONNET_4_API_KEY": "only"}, clear=False):
            os.environ.pop("CLAUDE_SONNET_4_API_KEY_2", None)
            os.environ.pop("CLAUDE_SONNET_4_API_KEY_3", None)
            os.environ["CLAUDE_SONNET_4_API_KEY"] = "only"
            keys = get_claude_api_keys()
        self.assertEqual(keys, ["only"])

    def test_returns_empty_when_none_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_SONNET_4_API_KEY", None)
            os.environ.pop("CLAUDE_SONNET_4_API_KEY_2", None)
            os.environ.pop("CLAUDE_SONNET_4_API_KEY_3", None)
            keys = get_claude_api_keys()
        self.assertEqual(keys, [])


if __name__ == "__main__":
    unittest.main()
