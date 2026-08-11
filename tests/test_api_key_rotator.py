"""Failing tests for Claude Sonnet 4 API key fallback rotation (TDD red)."""

from __future__ import annotations

import unittest

from api_key_rotator import ApiKeyRotator


class TestApiKeyRotator(unittest.TestCase):
    def test_requires_at_least_one_key(self):
        with self.assertRaises(ValueError):
            ApiKeyRotator([])

    def test_current_is_first_key(self):
        rotator = ApiKeyRotator(["k1", "k2", "k3"])
        self.assertEqual(rotator.current, "k1")

    def test_advance_cycles_through_keys_then_wraps(self):
        rotator = ApiKeyRotator(["k1", "k2", "k3"])
        self.assertEqual(rotator.advance(), "k2")
        self.assertEqual(rotator.current, "k2")
        self.assertEqual(rotator.advance(), "k3")
        self.assertEqual(rotator.advance(), "k1")
        self.assertEqual(rotator.advance(), "k2")

    def test_len_matches_pool_size(self):
        self.assertEqual(len(ApiKeyRotator(["a", "b"])), 2)


if __name__ == "__main__":
    unittest.main()
