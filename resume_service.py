from __future__ import annotations

from io import BytesIO
from typing import Callable, Mapping, Optional

SUPPORTED_EXTENSIONS = ("pdf", "docx", "doc", "txt")


class ResumeServiceError(Exception):
    """Base error for problems with a single submitted file."""


class UnsupportedFileTypeError(ResumeServiceError):
    """The file extension has no registered text extractor."""


class NoTextExtractedError(ResumeServiceError):
    """The file yielded no usable text (e.g. a scanned PDF)."""


class InMemoryUpload:
    """Adapter giving raw bytes the ``.name`` / ``.read()`` shape the processors expect."""

    def __init__(self, filename: str, data: bytes):
        self.name = filename
        self._stream = BytesIO(data)

    def read(self, *args, **kwargs) -> bytes:
        return self._stream.read(*args, **kwargs)

    def getvalue(self) -> bytes:
        return self._stream.getvalue()

    def seek(self, *args, **kwargs) -> int:
        return self._stream.seek(*args, **kwargs)


def default_extractors() -> dict[str, Callable[[InMemoryUpload], str]]:
    """Build the extension -> extractor registry from the existing processors."""
    from pdf_processor import PDFProcessor
    from text_processor import TextProcessor
    from word_processor import WordProcessor

    pdf_processor = PDFProcessor()
    word_processor = WordProcessor()
    text_processor = TextProcessor()

    return {
        "pdf": pdf_processor.process_pdf_file,
        "docx": word_processor.process_word_file,
        "doc": word_processor.process_word_file,
        "txt": text_processor.process_text_file,
    }


class ResumeParsingService:
    """Parse one uploaded resume into the structured candidate record."""

    def __init__(
        self,
        parser_factory: Callable[[str], object],
        extractors: Mapping[str, Callable[[InMemoryUpload], str]],
        archiver: Optional[object] = None,
        store: Optional[object] = None,
    ):
        self._parser_factory = parser_factory
        self._extractors = dict(extractors)
        self._archiver = archiver
        self._store = store

    @classmethod
    def from_settings(cls) -> "ResumeParsingService":
        from ai_parser import AIParser
        from blob_uploader import BlobUploader
        from config import get_claude_api_keys
        import cosmos_store 
        
        api_keys = get_claude_api_keys()
        if not api_keys: 
            raise RuntimeError("No API key is configured.")

        try:
            archiver = BlobUploader.from_settings()
        except Exception: 
            archiver = None 
        
        if cosmos_store.is_configured():
            store = cosmos_store or None
        
        return cls(
            parser_factory=lambda country: AIParser(api_keys, country), 
            extractors=default_extractors(),
            archiver=archiver, 
            store=store,
        )

    def parse(self, filename:str, data: bytes, country: str) -> dict: 
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        extractor = self._extractors.get(extension)
        if extractor is None: 
            raise UnsupportedFileTypeError(
                f"Unsupported file type '.{extension}' "
                f"Supported file type: {','.join(SUPPORTED_EXTENSIONS)}"
            )
        
        permanent_url, blob_path = self._archive(filename, data, country)
        text = extractor(InMemoryUpload(filename, data)) or "" 
        if not text.strip():
            raise NoTextExtractedError(f"No text can be extracted from '{filename}'")
        
        parsed = self._parser_factory(country).parse_resume(text)
        parsed["filename"] = permanent_url or filename 
        parsed["blob_path"] = blob_path or f"{country}/local/{filename}"

        self._persist(parsed, country)
        return parsed


    def _archive(self, filename: str, data:bytes , country: str): 
        # Archive for upload to azure blob storage
        if self._archiver is None: 
            return None, None 
        
        try: 
            return self._archiver.upsert(data,filename, country)
        except Exception:
            return None, None 
    
    def _persist(self, parsed:dict, country: str) -> None:
        if self._store is None: 
            return 
        try: 
            self._store.save_candidate(parsed,country)
        except Exception:
            pass
