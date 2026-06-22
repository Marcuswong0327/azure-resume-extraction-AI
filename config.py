"""Resolve config from environment variables (Railway, Docker) or Streamlit secrets.toml."""

from __future__ import annotations

import os
from typing import Optional


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
