"""Failing tests for the headless resume-parsing service (TDD red).

Requirement: the exposed endpoint must run the same pipeline as the Streamlit
app (archive -> extract text -> AI parse -> persist) without depending on
Streamlit UI calls, so it is injected with collaborators it can be tested with.
"""

from __future__ import annotations

import unittest

from resume_service import (
    NoTextExtractedError,
    ResumeParsingService,
    UnsupportedFileTypeError,
)


class FakeParser:
    def __init__(self, country="AU"):
        self.country = country
        self.seen_text = None

    def parse_resume(self, text):
        self.seen_text = text
        return {"full name": "Ada Lovelace", "email": "ada@example.com"}


class FakeArchiver:
    def __init__(self, url="https://blob/AU/hash.pdf", path="AU/hash.pdf", error=None):
        self.url = url
        self.path = path
        self.error = error
        self.calls = []

    def upsert(self, data, filename, country):
        self.calls.append((data, filename, country))
        if self.error:
            raise self.error
        return self.url, self.path


class RecordingStore:
    def __init__(self):
        self.saved = []

    def save_candidate(self, parsed_data, country):
        self.saved.append((parsed_data, country))
        return None


def build_service(**overrides):
    defaults = dict(
        parser_factory=lambda country: FakeParser(country),
        extractors={"pdf": lambda upload: "resume text"},
        archiver=None,
        store=None,
    )
    defaults.update(overrides)
    return ResumeParsingService(**defaults)


class TestResumeParsingService(unittest.TestCase):
    def test_returns_parsed_fields_for_supported_file(self):
        service = build_service()
        result = service.parse(filename="cv.pdf", data=b"%PDF-", country="AU")
        self.assertEqual(result["full name"], "Ada Lovelace")

    def test_routes_by_extension_case_insensitively(self):
        service = build_service(extractors={"pdf": lambda upload: "text from pdf"})
        parsers = []

        def factory(country):
            parser = FakeParser(country)
            parsers.append(parser)
            return parser

        service = build_service(
            extractors={"pdf": lambda upload: "text from pdf"},
            parser_factory=factory,
        )
        service.parse(filename="CV.PDF", data=b"%PDF-", country="AU")
        self.assertEqual(parsers[0].seen_text, "text from pdf")

    def test_extractor_receives_upload_with_name_and_read(self):
        seen = {}

        def extractor(upload):
            seen["name"] = upload.name
            seen["data"] = upload.read()
            return "text"

        service = build_service(extractors={"pdf": extractor})
        service.parse(filename="cv.pdf", data=b"bytes", country="AU")
        self.assertEqual(seen["name"], "cv.pdf")
        self.assertEqual(seen["data"], b"bytes")

    def test_rejects_unsupported_file_type(self):
        service = build_service()
        with self.assertRaises(UnsupportedFileTypeError):
            service.parse(filename="cv.png", data=b"x", country="AU")

    def test_rejects_file_without_extractable_text(self):
        service = build_service(extractors={"pdf": lambda upload: "   "})
        with self.assertRaises(NoTextExtractedError):
            service.parse(filename="cv.pdf", data=b"x", country="AU")

    def test_uses_country_specific_parser(self):
        parsers = []

        def factory(country):
            parser = FakeParser(country)
            parsers.append(parser)
            return parser

        service = build_service(parser_factory=factory)
        service.parse(filename="cv.pdf", data=b"x", country="MY")
        self.assertEqual(parsers[0].country, "MY")

    def test_archives_file_and_reports_permanent_url(self):
        archiver = FakeArchiver()
        service = build_service(archiver=archiver)
        result = service.parse(filename="cv.pdf", data=b"x", country="AU")
        self.assertEqual(archiver.calls[0], (b"x", "cv.pdf", "AU"))
        self.assertEqual(result["filename"], "https://blob/AU/hash.pdf")
        self.assertEqual(result["blob_path"], "AU/hash.pdf")

    def test_without_archiver_falls_back_to_original_filename(self):
        service = build_service()
        result = service.parse(filename="cv.pdf", data=b"x", country="AU")
        self.assertEqual(result["filename"], "cv.pdf")
        self.assertEqual(result["blob_path"], "AU/local/cv.pdf")

    def test_archive_failure_is_fail_soft(self):
        archiver = FakeArchiver(error=RuntimeError("azure down"))
        service = build_service(archiver=archiver)
        result = service.parse(filename="cv.pdf", data=b"x", country="AU")
        self.assertEqual(result["filename"], "cv.pdf")
        self.assertEqual(result["full name"], "Ada Lovelace")

    def test_persists_candidate_when_store_provided(self):
        store = RecordingStore()
        service = build_service(store=store)
        service.parse(filename="cv.pdf", data=b"x", country="AU")
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(store.saved[0][1], "AU")

    def test_store_failure_does_not_break_parsing(self):
        class FailingStore:
            def save_candidate(self, parsed_data, country):
                raise RuntimeError("cosmos down")

        service = build_service(store=FailingStore())
        result = service.parse(filename="cv.pdf", data=b"x", country="AU")
        self.assertEqual(result["full name"], "Ada Lovelace")


if __name__ == "__main__":
    unittest.main()
