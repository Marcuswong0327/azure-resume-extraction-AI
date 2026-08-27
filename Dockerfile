# Resume Parser 2.0 — Streamlit app with legacy .doc support (antiword).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: antiword for legacy .doc extraction (see packages.txt).
RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ai_parser.py api.py api_key_auth.py api_key_rotator.py \
     blob_uploader.py config.py cosmos_store.py excel_exporter.py \
     pdf_processor.py resume_service.py text_processor.py word_processor.py \
     ./

RUN mkdir -p /app/.streamlit

# 8501 = Streamlit UI, 8000 = integration API (see compose.yaml).
EXPOSE 8501 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false", \
     "--server.enableCORS=false", \
     "--server.enableXsrfProtection=false"]
