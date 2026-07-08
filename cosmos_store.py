"""Global candidate storage and search backed by Azure Cosmos DB.

Saves parsed resume fields and powers the Global Search tab.
Uses the Cosmos DB NoSQL API with upsert by blob_path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

from config import get_secret

_MAX_ROWS = 20000
_CACHE_TTL_SECONDS = 300

DEFAULT_DATABASE = "resume-db"
DEFAULT_CONTAINER = "candidates"


def get_database_name() -> str:
    return get_secret("COSMOS_DATABASE", DEFAULT_DATABASE)


def get_container_name() -> str:
    return get_secret("COSMOS_CONTAINER", DEFAULT_CONTAINER)


def is_configured() -> bool:
    return bool(get_secret("COSMOS_ENDPOINT") and get_secret("COSMOS_KEY"))


@st.cache_resource(show_spinner=False)
def _get_cosmos_container_cached(endpoint: str, key: str, database: str, container: str):
    """Cached Cosmos container client; cache key includes credentials."""
    from azure.cosmos import CosmosClient, PartitionKey

    client = CosmosClient(endpoint, key)
    db = client.create_database_if_not_exists(id=database)
    return db.create_container_if_not_exists(
        id=container,
        partition_key=PartitionKey(path="/country"),
    )


def get_cosmos_container():
    """Return the Cosmos DB container client, or None when not configured."""
    endpoint = get_secret("COSMOS_ENDPOINT")
    key = get_secret("COSMOS_KEY")
    if not endpoint or not key:
        return None

    return _get_cosmos_container_cached(
        endpoint,
        key,
        get_database_name(),
        get_container_name(),
    )


def clear_cache() -> None:
    """Drop cached Cosmos clients and loaded candidate data."""
    _get_cosmos_container_cached.clear()
    load_candidates.clear()


@st.cache_data(ttl=_CACHE_TTL_SECONDS, show_spinner=False)
def load_candidates() -> pd.DataFrame:
    """Fetch all candidate documents as a DataFrame."""
    container = get_cosmos_container()
    if container is None:
        raise RuntimeError("Cosmos DB is not configured.")

    rows = list(
        container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
            max_item_count=_MAX_ROWS,
        )
    )
    return pd.DataFrame(rows)


def _parse_boolean_query(query: str) -> list[dict]:
    """Parse a boolean query string into a list of clause dicts.

    Supports:
      AND  — both sides must match (default when no operator given)
      OR   — either side must match
      NOT  — term must NOT appear

    Examples:
      account manager OR banker
      python AND KL NOT junior
      "senior executive" OR director

    Returns a list of {"op": "AND"|"OR"|"NOT", "term": str}.
    """
    import re

    # Tokenise: quoted phrases stay together, operators are keywords
    tokens = re.findall(r'"[^"]+"|NOT|AND|OR|\S+', query, flags=re.IGNORECASE)

    clauses: list[dict] = []
    pending_op = "AND"  # default connector between bare terms

    for token in tokens:
        upper = token.upper()
        if upper in ("AND", "OR", "NOT"):
            if upper == "NOT":
                pending_op = "NOT"
            else:
                pending_op = upper
        else:
            term = token.strip('"').lower()
            clauses.append({"op": pending_op, "term": term})
            # After a NOT the next bare term goes back to AND
            if pending_op == "NOT":
                pending_op = "AND"

    return clauses


def search_candidates(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Boolean search across all columns.

    Supports AND, OR, NOT operators and quoted phrases.
    Plain words without operators are treated as AND.

    Examples
    --------
    account manager                     → both words must appear
    account manager OR banker           → account+manager OR banker
    python AND kuala lumpur NOT junior  → python AND KL but not junior
    "senior executive"                  → exact phrase match
    """
    if not query.strip() or df.empty:
        return df

    clauses = _parse_boolean_query(query)
    if not clauses:
        return df

    haystack = df.astype(str).apply(" | ".join, axis=1).str.lower()

    # Start with all-False for OR-first logic, all-True for AND-first
    # Build the mask clause by clause
    mask = None
    for clause in clauses:
        op = clause["op"]
        term_mask = haystack.str.contains(clause["term"], regex=False)

        if op == "NOT":
            combined = ~term_mask
            mask = combined if mask is None else (mask & combined)
        elif op == "OR":
            mask = term_mask if mask is None else (mask | term_mask)
        else:  # AND (default)
            mask = term_mask if mask is None else (mask & term_mask)

    return df[mask] if mask is not None else df


def candidate_to_document(parsed_data: dict, country: str) -> dict:
    """Map an AI-parsed candidate dict to a Cosmos DB document."""
    blob_path = parsed_data.get("blob_path", "")
    doc_id = hashlib.sha256(blob_path.encode("utf-8")).hexdigest()

    return {
        "id": doc_id,
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
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
        "blob_path": blob_path,
    }


def save_candidate(parsed_data: dict, country: str) -> Optional[str]:
    """Upsert one parsed candidate into Cosmos DB.

    Returns an error message on failure, or None on success.
    """
    container = get_cosmos_container()
    if container is None:
        return None

    if not parsed_data.get("blob_path"):
        return "missing blob_path"

    document = candidate_to_document(parsed_data, country)
    try:
        container.upsert_item(document)
        load_candidates.clear()
        return None
    except Exception as exc:
        return str(exc)
