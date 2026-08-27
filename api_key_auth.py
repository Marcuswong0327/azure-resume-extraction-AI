"""API key authentication for the integration endpoint.

External systems send a shared secret on every request. Keys are configured in
``RESUME_API_KEYS``
"""

from __future__ import annotations

import hmac
from typing import Mapping, Optional

from config import get_secret

SETTING_NAME = "RESUME_API_KEYS"


def get_configured_api_keys() -> dict[str, str]:
    """Return {api_key: client_name} map from configuration."""
    raw = get_secret("RESUME_API_KEYS") or "" 
    credentials: dict[str, str] = {} 
    for segment in str(raw).split(","): 
        segment = segment.strip()
        if not segment:
            continue
        if ":" in segment: 
            name,key = segment.split(":" , 1)
            name, key = name.strip(), key.strip() 
        else:
            name, key = "", segment 
        if not key: 
            continue
        credentials[key] = name or f"client-{len(credentials) + 1}"
    return credentials


class ApiKeyVerifier: 
    #Verify a API key from current exisitng credentials 

    def __init__(self, credentials:Mapping[str,str]):
        self._credentials=dict(credentials)

    @classmethod
    def from_settings(cls) -> "ApiKeyVerifier":
        return cls(get_configured_api_keys())
    
    @property
    def is_enabled(self) -> bool : 
        # True when at least one key is configured, otherwise auth not applicable 
        return bool(self._credentials)
    
    def identify(self, presented_key: Optional[str]) -> Optional[str]:
        """Return the client name for a valid key, or None when it is rejected."""
        candidate = (presented_key or "").strip()
        if not candidate:
            return None

        # Compare against every key so timing does not reveal which one matched.
        matched: Optional[str] = None
        for key, client_name in self._credentials.items():
            if hmac.compare_digest(candidate, key):
                matched = client_name
        return matched