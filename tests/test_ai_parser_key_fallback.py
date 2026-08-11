"""Tests: on API failure, AIParser tries next Claude key immediately, then wraps."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

# Avoid importing a broken/local Streamlit stack during unit tests.
sys.modules.setdefault("streamlit", MagicMock())

from ai_parser import AIParser  # noqa: E402


class TestAIParserKeyFallback(unittest.TestCase):
    def test_init_accepts_list_of_keys(self):
        parser = AIParser(["k1", "k2", "k3"], country="AU")
        self.assertEqual(parser.api_key, "k1")

    def test_init_rejects_empty_key_list(self):
        with self.assertRaises(ValueError):
            AIParser([], country="AU")

    @patch("ai_parser.time.sleep")
    @patch("ai_parser.requests.post")
    def test_on_failure_tries_second_then_third_then_wraps_to_first(
        self, mock_post, _mock_sleep
    ):
        """key1 fail → key2 fail → key3 fail → key1 success (wrap)."""
        fail = MagicMock(status_code=429, text="rate limited")
        fail.json.side_effect = Exception("no json")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {
            "choices": [{"message": {"content": '{"first name": "Ada"}'}}]
        }
        mock_post.side_effect = [fail, fail, fail, ok]

        parser = AIParser(["k1", "k2", "k3"], country="AU")
        content = parser._make_api_call_with_retry("prompt", max_rounds=2)

        self.assertIsNotNone(content)
        auth_headers = [
            call.kwargs["headers"]["Authorization"] for call in mock_post.call_args_list
        ]
        self.assertEqual(
            auth_headers,
            ["Bearer k1", "Bearer k2", "Bearer k3", "Bearer k1"],
        )

    @patch("ai_parser.time.sleep")
    @patch("ai_parser.requests.post")
    def test_all_keys_exhausted_across_rounds_returns_none(self, mock_post, _mock_sleep):
        fail = MagicMock(status_code=500, text="error")
        fail.json.side_effect = Exception("no json")
        mock_post.return_value = fail

        parser = AIParser(["k1", "k2", "k3"], country="AU")
        result = parser._make_api_call_with_retry("prompt", max_rounds=2)

        self.assertIsNone(result)
        self.assertEqual(mock_post.call_count, 6)  # 3 keys × 2 rounds


if __name__ == "__main__":
    unittest.main()
