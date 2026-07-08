"""Resolve config from environment variables (Railway, Docker) or Streamlit secrets.toml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Load project-root .env into os.environ for local development.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return a secret value: ``os.environ`` first, then ``st.secrets``."""
    value = os.environ.get(key)
    if value:
        return value

    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass

    return default
