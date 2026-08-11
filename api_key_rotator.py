"""Cycle through LLM API keys on failure (SRP: key selection only)."""

from __future__ import annotations


class ApiKeyRotator:
    """Round-robin pool: on failure, advance to the next key; wraps to the first."""

    def __init__(self, keys: list[str]):
        cleaned = [k.strip() for k in keys if k and str(k).strip()]
        if not cleaned:
            raise ValueError("At least one API key is required")
        self._keys = cleaned
        self._index = 0

    @property
    def current(self) -> str:
        return self._keys[self._index]

    def advance(self) -> str:
        self._index = (self._index + 1) % len(self._keys)
        return self.current

    def __len__(self) -> int:
        return len(self._keys)
