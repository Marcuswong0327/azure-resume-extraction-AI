"""Failing tests for integration API key verification (TDD red).

Requirement: external systems authenticate to the exposed resume-parsing
endpoint with a shared secret sent on every request. Keys are configured as
``RESUME_API_KEYS`` and each key maps to a client name for audit logging.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api_key_auth import ApiKeyVerifier, get_configured_api_keys


class TestGetConfiguredApiKeys(unittest.TestCase):
    def test_returns_empty_when_not_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESUME_API_KEYS", None)
            self.assertEqual(get_configured_api_keys(), {})

    def test_parses_named_keys(self):
        with patch.dict(os.environ, {"RESUME_API_KEYS": "ats:sk_one,hris:sk_two"}):
            self.assertEqual(
                get_configured_api_keys(),
                {"sk_one": "ats", "sk_two": "hris"},
            )

    def test_unnamed_keys_get_positional_client_names(self):
        with patch.dict(os.environ, {"RESUME_API_KEYS": "sk_plain"}):
            self.assertEqual(get_configured_api_keys(), {"sk_plain": "client-1"})

    def test_ignores_blank_segments_and_whitespace(self):
        with patch.dict(os.environ, {"RESUME_API_KEYS": " ats : sk_one , , hris:sk_two ,"}):
            self.assertEqual(
                get_configured_api_keys(),
                {"sk_one": "ats", "sk_two": "hris"},
            )


class TestApiKeyVerifier(unittest.TestCase):
    def test_identifies_client_for_valid_key(self):
        verifier = ApiKeyVerifier({"sk_one": "ats"})
        self.assertEqual(verifier.identify("sk_one"), "ats")

    def test_rejects_unknown_key(self):
        verifier = ApiKeyVerifier({"sk_one": "ats"})
        self.assertIsNone(verifier.identify("sk_wrong"))

    def test_rejects_missing_key(self):
        verifier = ApiKeyVerifier({"sk_one": "ats"})
        self.assertIsNone(verifier.identify(None))
        self.assertIsNone(verifier.identify(""))
        self.assertIsNone(verifier.identify("   "))

    def test_is_enabled_reflects_configured_keys(self):
        self.assertTrue(ApiKeyVerifier({"sk_one": "ats"}).is_enabled)
        self.assertFalse(ApiKeyVerifier({}).is_enabled)

    def test_verifier_with_no_keys_rejects_everything(self):
        verifier = ApiKeyVerifier({})
        self.assertIsNone(verifier.identify("sk_one"))

    def test_from_settings_reads_configuration(self):
        with patch.dict(os.environ, {"RESUME_API_KEYS": "ats:sk_one"}):
            verifier = ApiKeyVerifier.from_settings()
        self.assertEqual(verifier.identify("sk_one"), "ats")


if __name__ == "__main__":
    unittest.main()
