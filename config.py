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


_CLAUDE_API_KEY_NAMES = (
    "CLAUDE_SONNET_4_API_KEY",
    "CLAUDE_SONNET_4_API_KEY_2",
    "CLAUDE_SONNET_4_API_KEY_3",
)


def get_claude_api_keys() -> list[str]:
    """Return configured OpenRouter Claude Sonnet 4 keys in fallback order (1→2→3)."""
    keys: list[str] = []
    for name in _CLAUDE_API_KEY_NAMES:
        value = get_secret(name)
        if value and str(value).strip():
            keys.append(str(value).strip())
    return keys
