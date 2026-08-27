"""Failing tests for the exposed resume-parsing HTTP endpoint (TDD red).

Requirement: other systems POST resume files to a public endpoint and
authenticate with a shared API key sent in the request.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api import create_app
from api_key_auth import ApiKeyVerifier
from resume_service import NoTextExtractedError, UnsupportedFileTypeError

VALID_KEY = "sk_test_valid"
ENDPOINT = "/v1/resumes/parse"


class StubService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def parse(self, filename, data, country):
        self.calls.append((filename, data, country))
        if self.error:
            raise self.error
        return {
            "full name": "Ada Lovelace",
            "email": "ada@example.com",
            "filename": "https://blob/AU/hash.pdf",
            "blob_path": "AU/hash.pdf",
        }


def build_client(service=None, verifier=None):
    service = service or StubService()
    app = create_app(
        service_provider=lambda: service,
        verifier_provider=lambda: verifier or ApiKeyVerifier({VALID_KEY: "linktal-os"}),
    )
    return TestClient(app), service


def upload(name="cv.pdf", content=b"%PDF-1.4"):
    return {"files": (name, content, "application/pdf")}


class TestHealthEndpoint(unittest.TestCase):
    def test_health_is_public(self):
        client, _ = build_client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")


class TestApiKeyEnforcement(unittest.TestCase):
    def test_rejects_request_without_api_key(self):
        client, service = build_client()
        response = client.post(ENDPOINT, files=upload(), data={"country": "AU"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(service.calls, [])

    def test_rejects_wrong_api_key(self):
        client, service = build_client()
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "AU"},
            headers={"X-API-Key": "sk_wrong"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(service.calls, [])

    def test_accepts_key_in_x_api_key_header(self):
        client, _ = build_client()
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "AU"},
            headers={"X-API-Key": VALID_KEY},
        )
        self.assertEqual(response.status_code, 200)

    def test_accepts_key_as_bearer_token(self):
        client, _ = build_client()
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "AU"},
            headers={"Authorization": f"Bearer {VALID_KEY}"},
        )
        self.assertEqual(response.status_code, 200)

    def test_returns_503_when_no_keys_configured(self):
        client, _ = build_client(verifier=ApiKeyVerifier({}))
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "AU"},
            headers={"X-API-Key": VALID_KEY},
        )
        self.assertEqual(response.status_code, 503)


class TestParseEndpoint(unittest.TestCase):
    def test_returns_parsed_candidates(self):
        client, service = build_client()
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "AU"},
            headers={"X-API-Key": VALID_KEY},
        )
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["country"], "AU")
        self.assertEqual(body["parsed"], 1)
        self.assertEqual(body["candidates"][0]["full_name"], "Ada Lovelace")
        self.assertEqual(body["candidates"][0]["source_file"], "https://blob/AU/hash.pdf")
        self.assertEqual(body["errors"], [])

    def test_passes_file_bytes_and_country_to_service(self):
        client, service = build_client()
        client.post(
            ENDPOINT,
            files=upload(name="ada.pdf", content=b"RAWBYTES"),
            data={"country": "MY"},
            headers={"X-API-Key": VALID_KEY},
        )
        self.assertEqual(service.calls, [("ada.pdf", b"RAWBYTES", "MY")])

    def test_defaults_country_to_au(self):
        client, service = build_client()
        client.post(ENDPOINT, files=upload(), headers={"X-API-Key": VALID_KEY})
        self.assertEqual(service.calls[0][2], "AU")

    def test_rejects_unknown_country(self):
        client, service = build_client()
        response = client.post(
            ENDPOINT,
            files=upload(),
            data={"country": "SG"},
            headers={"X-API-Key": VALID_KEY},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.calls, [])

    def test_reports_per_file_errors_without_failing_whole_batch(self):
        class MixedService(StubService):
            def parse(self, filename, data, country):
                if filename.endswith(".png"):
                    raise UnsupportedFileTypeError("Unsupported file type '.png'.")
                return super().parse(filename, data, country)

        client, _ = build_client(service=MixedService())
        response = client.post(
            ENDPOINT,
            files=[
                ("files", ("cv.pdf", b"%PDF-1.4", "application/pdf")),
                ("files", ("photo.png", b"\x89PNG", "image/png")),
            ],
            headers={"X-API-Key": VALID_KEY},
        )
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["parsed"], 1)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(body["errors"][0]["filename"], "photo.png")

    def test_returns_422_when_every_file_fails(self):
        client, _ = build_client(
            service=StubService(error=NoTextExtractedError("no text"))
        )
        response = client.post(
            ENDPOINT,
            files=upload(),
            headers={"X-API-Key": VALID_KEY},
        )
        self.assertEqual(response.status_code, 422)

    def test_rejects_batch_over_the_limit(self):
        from api import MAX_FILES_PER_REQUEST

        client, service = build_client()
        too_many = [
            ("files", (f"cv{i}.pdf", b"%PDF-1.4", "application/pdf"))
            for i in range(MAX_FILES_PER_REQUEST + 1)
        ]
        response = client.post(ENDPOINT, files=too_many, headers={"X-API-Key": VALID_KEY})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
