"""Global candidate search backed by Supabase.

The Global Search tab pulls candidate rows from Supabase once (cached for a
few minutes), then filters them in memory. This keeps repeated searches
instant and works across every column regardless of the exact table schema,
so no column names need to be hardcoded here.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config import get_secret

# Page size for paginated fetches, plus a hard cap so an unexpectedly huge
# table cannot exhaust memory.
_PAGE_SIZE = 1000
_MAX_ROWS = 20000
_CACHE_TTL_SECONDS = 300

DEFAULT_TABLE = "candidates"


def get_table_name() -> str:
    """Supabase table to search; override with SUPABASE_TABLE."""
    return get_secret("SUPABASE_TABLE", DEFAULT_TABLE)


def is_configured() -> bool:
    return get_supabase_client() is not None


@st.cache_resource(show_spinner=False)
def get_supabase_client():
    """Return a Supabase client singleton, or None when not configured."""
    url = get_secret("SUPABASE_URL")
    key = (
        get_secret("SUPABASE_KEY")
        or get_secret("SUPABASE_ANON_KEY")
        or get_secret("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not url or not key:
        return None

    from supabase import create_client

    return create_client(url, key)


@st.cache_data(ttl=_CACHE_TTL_SECONDS, show_spinner=False)
def load_candidates(table_name: str) -> pd.DataFrame:
    """Fetch all rows from the Supabase table (paginated) as a DataFrame.

    Raises on connection/query errors so failures are shown to the user
    instead of being cached as an empty result.
    """
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase is not configured.")

    rows: list[dict] = []
    start = 0
    while start < _MAX_ROWS:
        end = min(start + _PAGE_SIZE, _MAX_ROWS) - 1
        response = client.table(table_name).select("*").range(start, end).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE

    return pd.DataFrame(rows)


def search_candidates(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Case-insensitive search across all columns.

    The query is split into terms; a row matches when every term appears
    somewhere in the row (so "account manager" finds rows containing both
    words, e.g. in the job title column).
    """
    terms = [t for t in query.strip().lower().split() if t]
    if not terms or df.empty:
        return df

    haystack = df.astype(str).apply(" | ".join, axis=1).str.lower()
    mask = pd.Series(True, index=df.index)
    for term in terms:
        mask &= haystack.str.contains(term, regex=False)
    return df[mask]


def candidate_to_row(parsed_data: dict, country: str) -> dict:
    """Map an AI-parsed candidate dict to a Supabase candidates row."""
    return {
        "country": country,
        "role_type": parsed_data.get("role type", ""),
        "full_name": parsed_data.get("full name", ""),
        "first_name": parsed_data.get("first name", ""),
        "last_name": parsed_data.get("last name", ""),
        "mobile": parsed_data.get("mobile", ""),
        "email": parsed_data.get("email", ""),
        "duration_1": parsed_data.get("duration 1", ""),
        "job_title_1": parsed_data.get("job title 1", ""),
        "company_1": parsed_data.get("company 1", ""),
        "duration_2": parsed_data.get("duration 2", ""),
        "job_title_2": parsed_data.get("job title 2", ""),
        "company_2": parsed_data.get("company 2", ""),
        "duration_3": parsed_data.get("duration 3", ""),
        "job_title_3": parsed_data.get("job title 3", ""),
        "company_3": parsed_data.get("company 3", ""),
        "location": parsed_data.get("location", ""),
        "source_file": parsed_data.get("filename", ""),
        "blob_path": parsed_data.get("blob_path", ""),
    }


def save_candidate(parsed_data: dict, country: str) -> Optional[str]:
    """Upsert one parsed candidate into Supabase.

    Returns an error message on failure, or None on success. Skips silently
    when Supabase is not configured so AU/MY processing is unaffected.
    """
    client = get_supabase_client()
    if client is None:
        return None

    blob_path = parsed_data.get("blob_path")
    if not blob_path:
        return "missing blob_path"

    row = candidate_to_row(parsed_data, country)
    try:
        client.table(get_table_name()).upsert(
            row, on_conflict="blob_path"
        ).execute()
        load_candidates.clear()
        return None
    except Exception as exc:
        return str(exc)
