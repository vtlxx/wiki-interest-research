"""Data providers. Only Wikimedia projects exist in v0.1."""
from __future__ import annotations

from ..net import HttpClient


def get_provider(source: str | None, http: HttpClient):
    from .wikimedia import WikimediaProvider

    return WikimediaProvider(source or "wikipedia", http)
