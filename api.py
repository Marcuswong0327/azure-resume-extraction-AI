"""Exposed HTTP API for external systems to submit resumes for parsing.

Authentication is a shared API key sent on every request, {X-API-Key: <key>}. Keys are configured in {RESUME_API_KEYS}

"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from api_key_auth import ApiKeyVerifier
from resume_service import ResumeParsingService, ResumeServiceError

logger = logging.getLogger(__name__)

API_VERSION = "1.0.0"
SUPPORTED_COUNTRIES = ("AU", "MY")
MAX_FILES_PER_REQUEST = 300

# Response field names use snake_case; the pipeline emits spaced keys.
_RESPONSE_FIELDS = {
    "role type": "role_type",
    "full name": "full_name",
    "first name": "first_name",
    "last name": "last_name",
    "mobile": "mobile",
    "email": "email",
    "duration 1": "duration_1",
    "job title 1": "job_title_1",
    "company 1": "company_1",
    "duration 2": "duration_2",
    "job title 2": "job_title_2",
    "company 2": "company_2",
    "duration 3": "duration_3",
    "job title 3": "job_title_3",
    "company 3": "company_3",
    "location": "location",
    "filename": "source_file",
    "blob_path": "blob_path",
}


def to_response_record(parsed:dict) -> dict:
    return {
        response_key: parsed.get(parsed_key, "")
        for parsed_key, response_key in _RESPONSE_FIELDS.items()
    }


def create_app(
    service_provider: Optional[Callable[[], ResumeParsingService]] = None,
    verifier_provider: Optional[Callable[[], ApiKeyVerifier]] = None,
) -> FastAPI:
    """Build the API. Providers are injected so the app is testable without Azure."""
    build_service = service_provider or _cached(ResumeParsingService.from_settings)
    build_verifier = verifier_provider or ApiKeyVerifier.from_settings

    app = FastAPI(
        title="Resume Parser API",
        version=API_VERSION,
        description=(
            "Submit resume files (pdf, docx, doc, txt) and receive structured "
            "candidate data. Authenticate with your API key in the X-API-Key header."
        ),
    )

    def require_api_key(
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
        authorization: Optional[str] = Header(default=None),
    ) -> str:
        verifier = build_verifier()
        if not verifier.is_enabled:
            raise HTTPException(
                status_code=503,
                detail="API keys are not configured on the server.",
            )

        presented = x_api_key
        if not presented and authorization and authorization.lower().startswith("bearer "):
            presented = authorization[7:]

        client_name = verifier.identify(presented)
        if client_name is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return client_name

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": API_VERSION}

    @app.post("/v1/resumes/parse", tags=["resumes"])
    def parse_resumes(
        files: list[UploadFile] = File(..., description="Resume files to parse"),
        country: str = Form("AU", description="AU or MY"),
        client_name: str = Depends(require_api_key),
    ) -> JSONResponse:
        country = (country or "AU").strip().upper()
        if country not in SUPPORTED_COUNTRIES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported country '{country}'. Use one of: "
                f"{', '.join(SUPPORTED_COUNTRIES)}.",
            )

        if len(files) > MAX_FILES_PER_REQUEST:
            raise HTTPException(
                status_code=413,
                detail=f"At most {MAX_FILES_PER_REQUEST} files per request; "
                f"received {len(files)}.",
            )

        try:
            service = build_service()
        except Exception as exc:
            logger.exception("Resume service unavailable")
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        candidates: list[dict] = []
        errors: list[dict] = []

        for upload_file in files:
            filename = upload_file.filename or "unnamed"
            try:
                data = upload_file.file.read()
                parsed = service.parse(filename=filename, data=data, country=country)
                candidates.append(to_response_record(parsed))
            except ResumeServiceError as exc:
                errors.append({"filename": filename, "error": str(exc)})
            except Exception as exc:
                logger.exception("Failed to parse %s", filename)
                errors.append({"filename": filename, "error": str(exc)})

        logger.info(
            "client=%s country=%s parsed=%d failed=%d",
            client_name,
            country,
            len(candidates),
            len(errors),
        )

        body = {
            "country": country,
            "parsed": len(candidates),
            "failed": len(errors),
            "candidates": candidates,
            "errors": errors,
        }
        status_code = 422 if candidates == [] and errors else 200
        return JSONResponse(status_code=status_code, content=body)

    return app


def _cached(factory: Callable[[], ResumeParsingService]) -> Callable[[], ResumeParsingService]:
    """Build the service once per process; each request would otherwise re-create clients."""
    holder: dict[str, ResumeParsingService] = {}

    def provider() -> ResumeParsingService:
        if "instance" not in holder:
            holder["instance"] = factory()
        return holder["instance"]

    return provider


app = create_app()
